"""질문 루프(next_round → reassess)를 점검한다. AI 호출을 가짜 함수로 바꿔서 무료.

실행: python scripts/check_reassess.py
- S004 환자의 평가 세트 시험 2개 + 저장된 v3 판정으로 bundle을 만들고
- 질문 생성·판정 AI를 가짜로 바꿔, 파이프라인이 형식대로 기록하고 관련 기준만 다시 판정하는지 본다
- 7~9번: 질문 코드(src/question_builder.py)가 기준 원문을 넘기고, AI 결과를 검사·정리하는지
실제 AI로 돌리는 건 scripts/run_reassess_demo.py (비용 발생)
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import re

import src.agents.matcher as matcher
import src.pipeline as pipeline
import src.question_builder as qb
from src.agents.matcher import build_user_message, final_judgment
from src.testing.goldset_bundle import make_bundle

failures = 0


def check(name: str, ok: bool) -> None:
    global failures
    print(f"  [{'OK' if ok else '실패'}] {name}")
    failures += not ok


# ── 가짜 AI ────────────────────────────────────────────────
match_calls = []


def fake_match(profile, criteria, case_text=None, system_prompt=None, answers=None):
    """받은 기준을 기록하고 전부 pass로 판정."""
    match_calls.append({"ids": [c["id"] for c in criteria], "answers": answers, "case_text": case_text})
    return [{"criterion_id": c["id"], "verdict": "pass", "evidence": "fake"} for c in criteria]


question_inputs = []


def parse_question_input(user: str) -> dict[str, list[str]]:
    """질문 AI 입력에서 {시험: [기준 ID]}를 읽는다."""
    out, trial = {}, None
    for line in user.splitlines():
        m = re.match(r"\[시험 \d+: (NCT\d+)", line)
        if m:
            trial = m.group(1)
            out[trial] = []
        m = re.match(r"([IE]\d+)\. ", line)
        if m and trial:
            out[trial].append(m.group(1))
    return out


def fake_question_ai(system, user):
    """시험마다 '모름' 기준을 2개씩 묶어 질문 하나로 (시험 순서대로 이어 붙여서 돌려줌)."""
    question_inputs.append(user)
    qs = []
    for trial, ids in parse_question_input(user).items():
        qs += [{"question": f"질문 {ids[i:i + 2]}", "needed_info": "",
                "resolves": [{"trial": trial, "criteria": ids[i:i + 2]}]} for i in range(0, len(ids), 2)]
    return {"questions": qs, "not_asked": []}


def main() -> int:
    matcher.match = fake_match                         # 이 점검 안에서만 가짜 AI 사용
    qb.ask_json = fake_question_ai
    bundle = make_bundle("S004")
    trials = {t["nct_id"]: t for t in bundle["trials"]}
    print("bundle: S004 × " + ", ".join(f"{n}({t['final_judgment']})" for n, t in trials.items()))
    eligible_trials = [n for n, t in trials.items() if t["final_judgment"] != "ineligible"]
    ineligible = [n for n, t in trials.items() if t["final_judgment"] == "ineligible"]

    print("\n1. 답변이 없으면 판정 요청이 v3 평가 때와 같음")
    t0 = bundle["trials"][0]
    check("답변 블록 없음", "PATIENT ANSWERS" not in build_user_message(bundle["profile"], t0["criteria"], "x"))
    check("답변을 넣으면 답변 블록 있음",
          "PATIENT ANSWERS" in build_user_message(bundle["profile"], t0["criteria"], "x", [{"id": "Q1"}]))

    print("\n2. next_round: 질문 만들기")
    qs = pipeline.next_round(bundle, max_questions=3)
    print("  " + "; ".join(f"{q['id']} → {q['resolves']}" for q in qs))
    check("ID가 Q1부터 통번호", [q["id"] for q in qs] == [f"Q{i}" for i in range(1, len(qs) + 1)])
    check("최대 3개", 0 < len(qs) <= 3)
    check("시험별로 번갈아 고름 (앞의 두 질문이 서로 다른 시험)",
          len(qs) >= 2 and qs[0]["resolves"][0]["trial"] != qs[1]["resolves"][0]["trial"])
    check("priority가 1부터 순서대로", [q["priority"] for q in qs] == list(range(1, len(qs) + 1)))
    check("부적격 시험은 질문 안 함", all(r["trial"] not in ineligible for q in qs for r in q["resolves"]))
    check("rounds에 1라운드 기록", len(bundle["rounds"]) == 1 and bundle["rounds"][0]["round"] == 1)

    print("\n3. reassess: Q1만 답함 (Q2는 빈 답)")
    q1 = qs[0]
    target = q1["resolves"][0]
    t = trials[target["trial"]]
    before = {j["criterion_id"]: j["verdict"] for j in t["judgments"]}
    other_before = {n: [j["verdict"] for j in x["judgments"]] for n, x in trials.items() if n != target["trial"]}
    changed = pipeline.reassess(bundle, [{"question_id": "Q1", "answer": "아니요, 없어요"},
                                         {"question_id": "Q2", "answer": "  "}])
    after = {j["criterion_id"]: j["verdict"] for j in t["judgments"]}
    call = match_calls[-1]
    print(f"  다시 판정한 기준: {call['ids']} / 바뀐 판정: {[(c['criterion_id'], c['from'], c['to']) for c in changed]}")
    check("판정 호출 1번 (Q1이 걸린 시험만)", len(match_calls) == 1)
    check("Q1의 resolves 기준만 다시 판정", sorted(call["ids"]) == sorted(target["criteria"]))
    check("판정에 원문과 Q1 답변이 들어감",
          call["case_text"] == bundle["case_text"] and [a["id"] for a in call["answers"]] == ["Q1"])
    check("관련 없는 기준은 그대로",
          all(after[c] == before[c] for c in before if c not in target["criteria"]))
    check("다른 시험은 그대로",
          all([j["verdict"] for j in trials[n]["judgments"]] == v for n, v in other_before.items()))
    check("바뀐 판정에 근거 질문(Q1) 기록",
          changed and all(c["source"] == ["Q1"] for c in changed) and bundle["rounds"][-1]["changed"] == changed)
    check("빈 답(Q2)은 기록 안 함", [a["question_id"] for a in bundle["rounds"][0]["answers"]] == ["Q1"])
    check("최종 판단 다시 계산", t["final_judgment"] == final_judgment(t["judgments"]))
    check("판정 순서가 기준 순서와 같음", [j["criterion_id"] for j in t["judgments"]] == [c["id"] for c in t["criteria"]])

    print("\n4. 2라운드: 이미 물어본 기준은 다시 안 물음")
    asked_before = pipeline.asked_criteria(bundle)
    qs2 = pipeline.next_round(bundle, max_questions=3)
    print("  " + "; ".join(f"{q['id']} → {q['resolves']}" for q in qs2))
    check("ID가 이어짐", not qs2 or qs2[0]["id"] == f"Q{len(qs) + 1}")
    check("이미 물어본 기준 없음",
          all(c not in asked_before.get(r["trial"], set()) for q in qs2 for r in q["resolves"] for c in r["criteria"]))

    print("\n5. 부적격 시험이 있는 환자 (S001)")
    b1 = make_bundle("S001")
    inel = [t["nct_id"] for t in b1["trials"] if t["final_judgment"] == "ineligible"]
    qs1 = pipeline.next_round(b1, max_questions=5)
    print(f"  부적격 시험: {inel}, 질문이 걸린 시험: {sorted({r['trial'] for q in qs1 for r in q['resolves']})}")
    check("부적격 시험이 실제로 있음", bool(inel))
    check("부적격 시험에는 질문 안 함", all(r["trial"] not in inel for q in qs1 for r in q["resolves"]))

    print("\n6. 오류 처리와 전체 재판정")
    try:
        pipeline.reassess(bundle, [{"question_id": "Q99", "answer": "네"}])
        check("없는 질문 ID → 오류", False)
    except ValueError:
        check("없는 질문 ID → 오류", True)
    match_calls.clear()
    pipeline.final_check(bundle)
    check("final_check(전체 재판정)면 모든 시험의 모든 기준 재판정",
          sorted(sum((c["ids"] for c in match_calls), [])) == sorted(c["id"] for x in bundle["trials"] for c in x["criteria"]))

    print("\n7. 질문 코드: AI 입력에 기준 원문과 답변이 들어감")
    check("기준 원문이 들어감 (S004 I3 원문)", "papillary tumor" in question_inputs[0])
    check("1라운드에는 이미 받은 답변 없음", "[이미 받은 답변]" not in question_inputs[0])
    check("2라운드 입력에 1라운드 답변이 들어감", "아니요, 없어요" in question_inputs[1])
    check("2라운드 입력에 이미 물어본 기준 없음",
          all(c not in parse_question_input(question_inputs[1]).get(r["trial"], [])
              for q in qs for r in q["resolves"] for c in r["criteria"]))

    print("\n8. 질문 코드: AI 결과 검사·정리 (S005)")
    b5 = json.loads((ROOT / "data" / "handoff" / "S005.json").read_text(encoding="utf-8"))
    A, B = "NCT04063540", "NCT07348783"
    messy = {"questions": [
        {"question": "A 약 질문", "resolves": [{"trial": A, "criteria": ["E3"]}]},
        {"question": "지금 드시는 약을 모두 알려 주세요.", "needed_info": "지금 먹는 약",
         "resolves": [{"trial": A, "criteria": ["E3", "E6", "Z9"]}, {"trial": B, "criteria": ["E4"]},
                      {"trial": "NCT99999999", "criteria": ["I1"]}]},
        {"question": "A E6만 다시", "resolves": [{"trial": A, "criteria": ["E6"]}]},
        {"question": "  ", "resolves": [{"trial": B, "criteria": ["I6"]}]},
        {"question": "B 진단 질문", "resolves": [{"trial": B, "criteria": ["I1"]}]},
        {"question": "A 진단 질문", "resolves": [{"trial": A, "criteria": ["I1"]}]},
        {"question": "없는 기준만", "resolves": [{"trial": A, "criteria": ["I99"]}]},
    ], "not_asked": [{"trial": B, "criterion_id": "E5", "reason": "질문 수 제한으로 보류"}]}
    qb.ask_json = lambda system, user: messy
    r5 = qb.build_questions(b5, top_k=5)
    print("  " + "; ".join(f"{q['priority']}. {q['text']} → {q['resolves']}" for q in r5["questions"]))
    check("여러 시험에 걸친 질문이 맨 앞", r5["questions"][0]["text"].startswith("지금 드시는 약"))
    check("없는 기준 번호(Z9, 없는 시험)는 버림",
          r5["questions"][0]["resolves"] == [{"trial": A, "criteria": ["E3", "E6"]}, {"trial": B, "criteria": ["E4"]}])
    check("이미 다룬 기준만 있는 질문, 빈 질문, 없는 기준만 있는 질문은 뺌",
          sorted(q["text"] for q in r5["questions"]) == sorted(["지금 드시는 약을 모두 알려 주세요.", "B 진단 질문", "A 진단 질문"]))
    check("priority 1부터", [q["priority"] for q in r5["questions"]] == [1, 2, 3])
    check("질문하지 않은 기준(not_asked)도 넘겨줌", r5["not_asked"] == messy["not_asked"])
    qb.ask_json = lambda system, user: messy["questions"][:2]
    check("AI가 목록만 줘도 처리", len(qb.build_questions(b5, top_k=5)["questions"]) == 1)
    qb.ask_json = lambda system, user: messy
    check("최대 개수로 자름", len(qb.questions_for_round(b5, max_questions=1)) == 1)

    print("\n9. 질문 코드: AI 없이 (use_llm=False, 무료 흐름 확인용)")
    from functools import partial
    builder = partial(qb.questions_for_round, use_llm=False)
    hq = pipeline.next_round(b5, build_questions=builder, max_questions=5)
    print("  " + "; ".join(f"{q['id']} → {q['resolves']}" for q in hq))
    check("질문 5개, 시험별로 번갈아", len(hq) == 5 and hq[0]["resolves"][0]["trial"] != hq[1]["resolves"][0]["trial"])
    hq2 = pipeline.next_round(b5, build_questions=builder, max_questions=5)
    asked = {(r["trial"], c) for q in hq for r in q["resolves"] for c in r["criteria"]}
    check("2라운드: ID가 이어지고 이미 물어본 기준 없음",
          bool(hq2) and hq2[0]["id"] == "Q6"
          and not any((r["trial"], c) in asked for q in hq2 for r in q["resolves"] for c in r["criteria"]))

    print(f"\n{'모두 통과' if failures == 0 else f'실패 {failures}개'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
