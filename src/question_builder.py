"""[5] 질문 준비 코드 (담당: 해준) — 튜토리얼 Step 2.

handoff/<환자>.json 을 받아, 환자 단위로 "여러 시험에 공통으로 걸린 정보부터"
묻도록 질문 재료를 모으고 묶는다. 질문 문장 생성(③)은 서현 담당 프롬프트 자리.

  ① collect_materials : 모든 후보 시험의 unknown 판정 + needed_info 수집
                        (부적격 시험, post_enrollment 항목, 지난 라운드에 이미 물어본 기준 제외)
  ② group_materials   : 같은 needed_info 끼리 묶고, 걸린 시험 수 많은 순 → 같으면 시험별로 번갈아,
                        새로 풀리는 기준이 없는 묶음은 건너뜀
  ③ phrase_questions  : 묶음별 질문 문장 생성 (LLM, 서현 프롬프트로 교체 예정.
                        LLM 없이도 임시 문장으로 동작 → use_llm=False)

출력 형식은 docs/HANDOFF.md "질문 파일 형식 제안"을 따른다.
질문 루프(pipeline.next_round)에서는 questions_for_round를 넘긴다 (질문 목록만 반환).
"""

import json
from collections import defaultdict

from src.llm import ask_json

# ③ 질문 문장 프롬프트 — ★ 서현 프롬프트가 나오면 이 상수만 교체 ★
PHRASE_SYSTEM_PROMPT = """You write screening questions for a clinical-trial
matching assistant, in Korean.

You receive groups of missing patient information. For EACH group write ONE
question a patient can understand and answer:
- plain language, no medical jargon unless the info requires a formal
  diagnosis name ("병원에서 ~ 진단을 받은 적이 있나요?" style)
- at most two sentences per question
- sensitive topics (pregnancy, psychiatric history, substance use) must be
  asked gently and never merged with other topics

Respond with ONLY a JSON array, same order as the groups:
[{"needed_info": "<group key as given>", "question": "<Korean question>"}, ...]"""


def collect_materials(bundle: dict) -> list[dict]:
    """① 질문 재료 수집. 반환 항목: {trial, criterion_id, criterion_text, needed_info(리스트)}"""
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
                "criterion_id": j["criterion_id"],
                "criterion_text": c.get("text", ""),
                "needed_info": c.get("needed_info") or [f"criterion: {c.get('text', '')[:60]}"],
            })
    return materials


def group_materials(materials: list[dict], top_k: int = 5) -> list[dict]:
    """② 같은 needed_info 문구끼리 묶는다 (대소문자·공백 차이만 무시).

    정렬: 걸린 시험 수 많은 순 → 같으면 시험별로 번갈아 (시험 A 1번, 시험 B 1번, A 2번, ...;
    한 시험 안에서는 걸린 기준 수 많은 순). 한 시험에 질문이 몰리지 않게 (10/16 실제 실행에서 발견).
    한 기준이 needed_info를 여러 개 가지면 각 묶음에 모두 들어가지만, 앞에서 고른 묶음이
    이미 다 다룬 기준만 남은 묶음은 건너뛴다 (같은 기준에 질문을 여러 번 쓰지 않게).
    질문 하나로 일부만 채워져도, 6번 재평가가 쌓인 정보 전체로 다시 판정하므로 문제없음.
    """
    groups: dict[str, dict] = {}
    for m in materials:
        for info in m["needed_info"]:
            key = " ".join(info.split()).casefold()
            g = groups.setdefault(key, {"needed_info": info, "resolves": defaultdict(list)})
            if m["criterion_id"] not in g["resolves"][m["trial"]]:
                g["resolves"][m["trial"]].append(m["criterion_id"])

    n_criteria = lambda g: sum(len(v) for v in g["resolves"].values())  # noqa: E731
    pairs = lambda g: {(t, c) for t, ids in g["resolves"].items() for c in ids}  # noqa: E731
    by_size = sorted(groups.values(), key=lambda g: (-len(g["resolves"]), -n_criteria(g)))
    multi = [g for g in by_size if len(g["resolves"]) > 1]
    queues = {t: [] for t in dict.fromkeys(m["trial"] for m in materials)}  # 시험 순서 유지
    for g in by_size:
        if len(g["resolves"]) == 1:
            queues[next(iter(g["resolves"]))].append(g)

    picked, covered = [], set()

    def take(g: dict) -> bool:
        """새로 풀리는 기준이 있으면 고른다."""
        if len(picked) < top_k and not pairs(g) <= covered:
            picked.append(g)
            covered.update(pairs(g))
            return True
        return False

    for g in multi:                                  # 여러 시험에 걸친 묶음 먼저
        take(g)
    while len(picked) < top_k and any(queues.values()):
        for q in queues.values():                    # 시험 A 하나, 시험 B 하나, ...
            while q and not take(q.pop(0)):
                pass
    return [
        {
            "needed_info": g["needed_info"],
            "resolves": [{"trial": t, "criteria": ids} for t, ids in g["resolves"].items()],
            "n_trials": len(g["resolves"]),
            "n_criteria": n_criteria(g),
        }
        for g in picked
    ]


def phrase_questions(groups: list[dict], use_llm: bool = True) -> list[str]:
    """③ 묶음별 질문 문장. use_llm=False면 임시 문장 (무료, 흐름 확인용)."""
    if not groups:
        return []
    if not use_llm:
        return [f"{g['needed_info']} 에 대해 알려주세요. (임시 문장)" for g in groups]
    payload = [{"needed_info": g["needed_info"],
                "example_criteria": [r["criteria"] for r in g["resolves"]][:2]} for g in groups]
    answers = ask_json(PHRASE_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False, indent=2))
    by_key = {a["needed_info"]: a["question"] for a in answers}
    return [by_key.get(g["needed_info"], f"{g['needed_info']} 에 대해 알려주세요.") for g in groups]


def build_questions(bundle: dict, top_k: int = 5, use_llm: bool = True) -> dict:
    """handoff bundle → questions/<환자>.json 내용물 (HANDOFF.md 형식)."""
    groups = group_materials(collect_materials(bundle), top_k=top_k)
    texts = phrase_questions(groups, use_llm=use_llm)
    return {
        "patient_id": bundle["patient_id"],
        "questions": [
            {
                "text": text,
                "needed_info": g["needed_info"],
                "resolves": g["resolves"],
                "priority": i,
            }
            for i, (g, text) in enumerate(zip(groups, texts), 1)
        ],
    }


def questions_for_round(bundle: dict, max_questions: int = 5, use_llm: bool = True) -> list[dict]:
    """질문 루프용: pipeline.next_round(bundle, build_questions=questions_for_round)로 넘긴다.

    next_round는 질문 목록만 받고 ID(Q1, Q2, ...)는 거기서 붙인다.
    """
    return build_questions(bundle, top_k=max_questions, use_llm=use_llm)["questions"]
