"""질문 루프(next_round → reassess)를 점검한다. AI 호출을 가짜 함수로 바꿔서 무료.

실행: python scripts/check_reassess.py
- S004 환자의 평가 세트 시험 2개 + 저장된 v3 판정으로 bundle을 만들고
- 질문 생성·판정 AI를 가짜로 바꿔, 파이프라인이 형식대로 기록하고 관련 기준만 다시 판정하는지 본다
실제 AI로 돌리는 건 scripts/run_reassess_demo.py (비용 발생)
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import src.agents.matcher as matcher
import src.pipeline as pipeline
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


def fake_generate_questions(criteria, judgments):
    """unknown 기준을 2개씩 묶어 질문 하나로."""
    ids = [j["criterion_id"] for j in judgments if j["verdict"] == "unknown"]
    return [{"criterion_ids": ids[i:i + 2], "question": f"질문 {ids[i:i + 2]}"} for i in range(0, len(ids), 2)]


def main() -> int:
    matcher.match = fake_match                         # 이 점검 안에서만 가짜 AI 사용
    pipeline.generate_questions = fake_generate_questions
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
    pipeline.reassess(bundle, [], full=True)
    check("full=True면 모든 시험의 모든 기준 재판정",
          sorted(sum((c["ids"] for c in match_calls), [])) == sorted(c["id"] for x in bundle["trials"] for c in x["criteria"]))

    print(f"\n{'모두 통과' if failures == 0 else f'실패 {failures}개'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
