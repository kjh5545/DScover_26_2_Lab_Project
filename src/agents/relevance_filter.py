"""[2b] 관련성 필터 — 검색이 집어온 "엉뚱한 시험" 거르기 (튜토리얼 Step 3, 1위 팀 방식).

키워드 검색은 같은 장기·같은 증상이라는 이유로 무관한 시험을 끌고 온다
(예: 생후 3개월 유문협착증 영아에게 성인 악성 위 출구 폐쇄 수술 시험).
제목·대상 질환명만 보고 "정말 이 환자의 병을 대상으로 한 시험인가"를
싼 모델(Haiku) 호출 1번으로 판단한다 — 기준 원문을 읽는 정밀 스크리닝보다 훨씬 싸다.

원칙: 확신 있는 무관만 거른다. 애매하면 남긴다 (정답 시험을 떨어뜨리는 게 더 큰 손해).
판단 실패(JSON 파싱 등) 시에도 전부 남긴다.
"""

import json

from src.llm import ask_json

FILTER_MODEL = "claude-haiku-4-5"  # 제목만 보는 가벼운 판단 — 가장 싼 모델로 충분

SYSTEM_PROMPT = """You screen clinical-trial search results for ONE patient.

You see the patient's age, sex, suspected diagnosis and key findings, plus a
list of trials (id, title, target conditions only — no eligibility text).
Mark each trial KEEP or DROP:

- KEEP if the trial targets the patient's (suspected) disease or its direct
  work-up/treatment/observation.
- DROP only when the trial is clearly about a DIFFERENT disease or population
  that this patient cannot belong to (e.g. a surgical trial for adult cancer
  obstruction offered to an infant with pyloric stenosis). Same organ or same
  symptom alone does NOT make it relevant.
- If unsure, KEEP. Never drop because information is missing.

Respond with ONLY a JSON array, one entry per trial, same order:
[{"nct_id": "...", "keep": true/false, "reason": "<one short sentence in Korean>"}, ...]"""


def filter_relevant(profile: dict, candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """(남긴 시험, 거른 시험) 반환. 거른 시험에는 _drop_reason이 붙는다."""
    patient = {
        "age": profile.get("age"), "age_unit": profile.get("age_unit"),
        "sex": profile.get("sex"),
        "suspected_diagnosis": profile.get("suspected_diagnosis")
                               or profile.get("suspected_diagnoses"),
        "findings": profile.get("findings", [])[:6],
    }
    trials = [{"nct_id": t["nct_id"], "title": t.get("title", ""),
               "conditions": t.get("conditions", [])} for t in candidates]
    user = ("PATIENT:\n" + json.dumps(patient, ensure_ascii=False)
            + "\n\nTRIALS:\n" + json.dumps(trials, ensure_ascii=False, indent=1))
    try:
        verdicts = ask_json(SYSTEM_PROMPT, user, model=FILTER_MODEL)
        by_id = {v["nct_id"]: v for v in verdicts if isinstance(v, dict)}
    except Exception as e:  # 판단 실패 시 거르지 않음 (안전한 쪽)
        print(f"  관련성 필터 실패 → 전부 유지: {e}")
        return candidates, []

    kept, dropped = [], []
    for t in candidates:
        v = by_id.get(t["nct_id"], {"keep": True})
        if v.get("keep", True):
            kept.append(t)
        else:
            dropped.append(dict(t, _drop_reason=v.get("reason", "")))
    return kept, dropped
