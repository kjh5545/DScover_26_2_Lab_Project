"""[5] 질문 준비 코드 (해준 PR #1 → 10/17 주희: 서현 v2.1 프롬프트로 묶기·문장을 AI에 맡김).

handoff bundle을 받아, 환자 단위로 "여러 시험에 공통으로 걸린 정보부터" 묻는 질문을 만든다.
"코드가 고르고 → AI가 묶어서 쓰고 → 코드가 검사"

  ① collect_materials : 모든 후보 시험의 unknown 판정 수집
                        (부적격 시험, post_enrollment 항목, 지난 라운드에 이미 물어본 기준 제외)
  ② write_questions   : AI(서현 v2.1 규칙)가 기준 원문을 보고 뜻이 같은 정보끼리 묶어 질문을 쓰고,
                        질문마다 푸는 기준(resolves)을 적는다. 시험마다 needed_info 문구가 달라도
                        ("current medication list" / "antihypertensive medication use") 뜻으로 묶인다.
     group_materials  : use_llm=False일 때 대신 쓰는 묶기 (needed_info 글자가 같은 것끼리, 임시 문장, 무료)
  ③ arrange           : AI 결과 검사·정리 — 후보에 없는 기준 번호 버리기, 새로 풀리는 기준이 없는 질문 빼기,
                        여러 시험에 걸친 질문 먼저 → 같으면 시험별로 번갈아, 최대 개수로 자르기

출력 형식은 docs/HANDOFF.md "질문 파일 형식 제안"을 따른다.
질문 루프(pipeline.next_round)는 questions_for_round를 쓴다 (질문 목록만 반환).
"""

import json
from collections import defaultdict

from src.llm import ask_json

FINAL_KO = {"eligible": "적격(eligible)", "probably_eligible": "적격 가능(probably_eligible)",
            "insufficient_info": "정보 부족(insufficient_info)", "ineligible": "부적격(ineligible)"}

# ② 질문 프롬프트 — 서현 v2.1 (10/17). 규칙 문장은 그대로 두고, 코드와 나눠 맡는 부분만 고쳤다:
#   규칙 1 개수는 입력의 [질문 수]로, 규칙 9 후보 고르기는 코드가 이미 함, 규칙 11·출력 형식은 JSON으로,
#   규칙 2에 resolves 적는 법, 규칙 13(이미 받은 답변) 추가.
QUESTION_SYSTEM_PROMPT = """당신은 임상시험 사전 스크리닝에서 환자에게 확인 질문을 만드는 담당자입니다.
입력은 한 환자의 후보 임상시험들에서 "모름"으로 판정된 기준 목록입니다. 이 기준들을 확인하기 위해 환자에게 물어볼 질문을 만드세요.

[질문 규칙]
1. 질문은 입력의 [질문 수]에 적힌 개수를 넘기지 마세요. 판정에 영향이 큰 질문부터 순서대로 쓰세요.
2. 여러 시험이나 여러 기준에 공통으로 필요한 정보는 질문 하나로 묶으세요. 걸린 시험·기준이 많은 정보일수록 먼저 묻습니다. 시험마다 표현이 달라도 환자에게 묻는 내용이 같으면 묶으세요 (예: 지금 먹는 약 목록과 혈압약 복용 여부는 "지금 드시는 약" 질문 하나로). 질문마다 그 답으로 확인할 수 있는 기준을 시험별로 모두 resolves에 적으세요.
3. 한 질문에는 한 가지 주제만 담으세요. 한 질문은 두 문장을 넘기지 마세요.
4. 환자가 이해하기 쉬운 한국어로 간결하게 쓰세요. 방광내시경·혈뇨처럼 비교적 익숙한 검사명·증상명은 그대로 사용할 수 있습니다. 낯선 전문 용어나 약어는 쉬운 말로 바꾸거나 짧은 설명을 덧붙이세요. 모든 의학 용어를 긴 묘사로 풀어 쓰지는 마세요.
5. 검사 수치를 기억으로 묻지 마세요. 대신 검사를 받은 적이 있는지, 결과지가 있는지를 물으세요.
6. 진단명보다 증상이나 경험을 물으세요. (예: "OO병 진단을 받았나요?"보다 "OO 증상이 있었나요?"가 더 답하기 쉬우면 증상으로)
7. 환자에게 적격인지 아닌지 말하지 마세요.
8. 민감한 질문(임신, 정신 건강, 법적 신분 등)은 부드럽게 쓰고 다른 질문과 묶지 마세요.
9. 입력에 적힌 기준만 질문 후보입니다 (모두 '모름'이고, 부적격 시험과 '등록 후 확인' 기준은 이미 빠져 있습니다). '모름'인 기준을 의료진이 판단할 항목이라는 이유만으로 질문 후보에서 제외하지 마세요. 환자가 알려줄 수 있는 경험·일상생활 정보나 기존 검사 결과지의 보유 여부를 확인할 수 있습니다. 질문하지 않은 기준은 '질문 수 제한으로 보류'와 '검사·기록 또는 의료진의 추가 확인 필요'를 구분해 이유를 적으세요.
10. 원문에 없는 사실·조건·기간 제한을 추가하지 마세요. 특히 현재 사건이나 검사를 제외한다는 명시가 없다면, "이번 일이 생기기 전", "현재 검사 이전" 같은 제한을 질문에 넣지 마세요. 기준 사이의 AND/OR 관계나 시험기관의 향후 확인 절차도 추정하지 마세요. 다른 기준을 충족할 것 같다는 이유로 기준을 생략하지 마세요.
11. 질문을 만들거나 기준 ID를 연결한 것만으로 해당 기준이 확인·해결되었다고 표현하지 마세요. 환자 답변을 받기 전에는 모두 미확인 상태입니다. 아래 JSON 외에 "모든 기준이 확인된다", "핵심 등록 기준이 확인된다" 같은 결론을 쓰지 마세요.
12. 쉬운 말로 바꾸거나 질문을 줄이더라도, 기준에 명시된 신체 부위와 검사·치료 대상을 생략하지 마세요. 앞 문장의 맥락에만 의존하지 말고, 무엇에 관한 질문인지 명확하게 쓰세요. 예: 방광 종양에 관한 기준이라면 "종양 제거 수술"보다 "방광 종양 제거 수술"처럼 대상을 명시하세요. 단, 원문에 없는 부위나 치료 대상을 추가해서는 안 됩니다.
13. [이미 받은 답변]이 있으면 그 답으로 알 수 있는 내용은 다시 묻지 마세요.

[출력 형식]
JSON 하나만 출력하세요.
{"questions": [{"question": "<환자에게 물을 한국어 질문>", "needed_info": "<무엇을 묻는지 짧게>",
                "resolves": [{"trial": "<시험 번호>", "criteria": ["<기준 ID>", ...]}, ...]}, ...],
 "not_asked": [{"trial": "<시험 번호>", "criterion_id": "<기준 ID>",
                "reason": "질문 수 제한으로 보류" 또는 "검사·기록 또는 의료진의 추가 확인 필요"}, ...]}"""


def collect_materials(bundle: dict) -> list[dict]:
    """① 질문 재료 수집. 반환 항목: {trial, title, final_judgment, criterion_id, criterion_text, needed_info(리스트)}"""
    from src.pipeline import asked_criteria

    asked = asked_criteria(bundle)  # 지난 라운드에 물어본 기준 (답이 없었어도 다시 묻지 않음)
    materials = []
    for trial in bundle.get("trials", []):
        if trial.get("final_judgment") == "ineligible":
            continue  # 탈락 확정 시험에 대한 질문은 무의미 (팀 규칙)
        crit_by_id = {c["id"]: c for c in trial.get("criteria", [])}
        for j in trial.get("judgments", []):
            if j.get("verdict") != "unknown":
                continue  # post_enrollment 등은 지금 물어도 답할 수 없음
            if j.get("criterion_id") in asked.get(trial["nct_id"], set()):
                continue
            c = crit_by_id.get(j.get("criterion_id"), {})
            materials.append({
                "trial": trial["nct_id"],
                "title": trial.get("title", ""),
                "final_judgment": trial.get("final_judgment"),
                "criterion_id": j["criterion_id"],
                "criterion_text": c.get("text", ""),
                "needed_info": c.get("needed_info") or [],
            })
    return materials


def question_input(bundle: dict, materials: list[dict], max_questions: int) -> str:
    """② AI에게 넘길 입력: 환자 원문 + 이미 받은 답변 + 시험별 '모름' 기준 원문 (서현 v2.1 입력 모양)."""
    from src.pipeline import all_answers

    parts = [f"[질문 수]\n최대 {max_questions}개", f"[환자]\n{bundle.get('case_text', '')}"]
    answered = all_answers(bundle)
    if answered:
        parts.append("[이미 받은 답변]\n" + "\n".join(f"{a['id']}. {a['question']} → {a['answer']}" for a in answered))
    by_trial: dict[str, list[dict]] = defaultdict(list)
    for m in materials:
        by_trial[m["trial"]].append(m)
    for i, (nct, ms) in enumerate(by_trial.items(), 1):
        title = f" · {ms[0]['title']}" if ms[0]["title"] and ms[0]["title"] != nct else ""
        lines = [f"[시험 {i}: {nct}{title}]",
                 f"최종 판단: {FINAL_KO.get(ms[0]['final_judgment'], ms[0]['final_judgment'])}",
                 "아래 기준은 모두 모름(unknown)입니다.", ""]
        for m in ms:
            info = f"  (필요한 정보: {', '.join(m['needed_info'])})" if m["needed_info"] else ""
            lines.append(f"{m['criterion_id']}. {m['criterion_text']}{info}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def write_questions(bundle: dict, materials: list[dict], max_questions: int) -> tuple[list[dict], list[dict]]:
    """② AI가 묶어서 질문을 쓴다 (호출 1번). 반환: (질문 [{text, needed_info, resolves}], 질문하지 않은 기준)"""
    out = ask_json(QUESTION_SYSTEM_PROMPT, question_input(bundle, materials, max_questions))
    if isinstance(out, list):  # {"questions": ...} 대신 목록만 준 경우
        out = {"questions": out}
    questions = [{"text": q.get("question", ""), "needed_info": q.get("needed_info", ""),
                  "resolves": q.get("resolves", [])} for q in out.get("questions", []) if isinstance(q, dict)]
    return questions, out.get("not_asked", [])


def group_materials(materials: list[dict]) -> list[dict]:
    """use_llm=False용 묶기: 같은 needed_info 문구끼리 (대소문자·공백 차이만 무시), 임시 문장.

    needed_info가 없으면 기준 원문 앞부분을 묶음 키로 쓴다. 걸린 시험 수 → 기준 수 많은 순으로 돌려준다.
    """
    groups: dict[str, dict] = {}
    for m in materials:
        for info in m["needed_info"] or [f"criterion: {m['criterion_text'][:60]}"]:
            key = " ".join(info.split()).casefold()
            g = groups.setdefault(key, {"needed_info": info, "resolves": defaultdict(list)})
            if m["criterion_id"] not in g["resolves"][m["trial"]]:
                g["resolves"][m["trial"]].append(m["criterion_id"])
    ranked = sorted(groups.values(),
                    key=lambda g: (-len(g["resolves"]), -sum(len(v) for v in g["resolves"].values())))
    return [{"text": f"{g['needed_info']} 에 대해 알려주세요. (임시 문장)", "needed_info": g["needed_info"],
             "resolves": [{"trial": t, "criteria": ids} for t, ids in g["resolves"].items()]} for g in ranked]


def arrange(questions: list[dict], materials: list[dict], top_k: int) -> list[dict]:
    """③ 검사·정리.

    - resolves에서 후보(①)에 없는 시험·기준은 버리고, 남는 게 없거나 문장이 빈 질문은 뺀다
    - 여러 시험에 걸친 질문 먼저 → 나머지는 시험별로 번갈아 (시험 A 하나, 시험 B 하나, ...;
      시험 안에서는 받은 순서). 한 시험에 질문이 몰리지 않게 (10/16 실제 실행에서 발견)
    - 앞 질문이 이미 다룬 기준만 있는 질문은 건너뛴다 (같은 기준에 질문을 여러 번 쓰지 않게)
    질문 하나로 일부만 채워져도, 6번 재평가가 원문 + 모든 답변으로 다시 판정하므로 문제없음.
    """
    valid = {(m["trial"], m["criterion_id"]) for m in materials}
    clean = []
    for q in questions:
        res: dict[str, list[str]] = {}
        for r in q.get("resolves") or []:
            if not isinstance(r, dict):
                continue
            for cid in r.get("criteria") or []:
                if (r.get("trial"), cid) in valid and cid not in res.get(r["trial"], []):
                    res.setdefault(r["trial"], []).append(cid)
        if res and str(q.get("text", "")).strip():
            clean.append(dict(q, resolves=res))

    pairs = lambda q: {(t, c) for t, ids in q["resolves"].items() for c in ids}  # noqa: E731
    queues = {t: [] for t in dict.fromkeys(m["trial"] for m in materials)}  # 시험 순서 유지
    multi = sorted([q for q in clean if len(q["resolves"]) > 1], key=lambda q: -len(q["resolves"]))
    for q in clean:
        if len(q["resolves"]) == 1:
            queues[next(iter(q["resolves"]))].append(q)

    picked, covered = [], set()

    def take(q: dict) -> bool:
        """새로 풀리는 기준이 있으면 고른다."""
        if len(picked) < top_k and not pairs(q) <= covered:
            picked.append(q)
            covered.update(pairs(q))
            return True
        return False

    for q in multi:                                  # 여러 시험에 걸친 질문 먼저
        take(q)
    while len(picked) < top_k and any(queues.values()):
        for qs in queues.values():                   # 시험 A 하나, 시험 B 하나, ...
            while qs and not take(qs.pop(0)):
                pass
    return [{"text": q["text"].strip(), "needed_info": q.get("needed_info", ""),
             "resolves": [{"trial": t, "criteria": ids} for t, ids in q["resolves"].items()]} for q in picked]


def build_questions(bundle: dict, top_k: int = 5, use_llm: bool = True) -> dict:
    """handoff bundle → questions/<환자>.json 내용물 (HANDOFF.md 형식 + 질문하지 않은 기준)."""
    materials = collect_materials(bundle)
    not_asked = []
    if not materials:
        questions = []
    elif use_llm:
        questions, not_asked = write_questions(bundle, materials, top_k)
    else:
        questions = group_materials(materials)
    return {
        "patient_id": bundle["patient_id"],
        "questions": [dict(q, priority=i) for i, q in enumerate(arrange(questions, materials, top_k), 1)],
        "not_asked": not_asked,
    }


def questions_for_round(bundle: dict, max_questions: int = 5, use_llm: bool = True) -> list[dict]:
    """질문 루프용 (pipeline.next_round의 기본값): 질문 목록만 돌려준다. ID(Q1, Q2, ...)는 next_round가 붙인다."""
    return build_questions(bundle, top_k=max_questions, use_llm=use_llm)["questions"]
