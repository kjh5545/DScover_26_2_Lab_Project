"""[2b] 관련성 필터·랭킹 — 검색이 집어온 "엉뚱한 시험" 거르기/줄세우기.

두 모드: filter_relevant(keep/drop, 튜토리얼 Step 3·1위 팀 방식)
       rank_relevant(0~10점 랭킹, 실험 3 — 큰 풀에서 상위 N 재현율 올리기)

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


RANK_SYSTEM_PROMPT = """You rank clinical-trial search results for ONE patient.

You see the patient's age, sex, suspected diagnosis and key findings, plus a
list of trials (id, title, target conditions only — no eligibility text).
Score each trial 0-10 for how likely it is to be meant for this patient:

- 8-10: targets the patient's (suspected) disease itself.
- 4-7: targets its direct work-up/treatment/observation, or a broader
  disease group that clearly includes this patient.
- 1-3: same organ or same symptom only — probably a different disease.
- 0: ONLY when the trial is clearly about a different disease or population
  this patient cannot belong to. Never give 0 because information is
  missing; if unsure, give 3 or more.

Respond with ONLY a JSON array, one entry per trial, same order:
[{"nct_id": "...", "score": <0-10>}, ...]"""


def _patient_summary(profile: dict) -> dict:
    return {
        "age": profile.get("age"), "age_unit": profile.get("age_unit"),
        "sex": profile.get("sex"),
        "suspected_diagnosis": profile.get("suspected_diagnosis")
                               or profile.get("suspected_diagnoses"),
        "findings": profile.get("findings", [])[:6],
    }


def rank_relevant(profile: dict, candidates: list[dict],
                  chunk_size: int = 150) -> tuple[list[dict], list[dict]]:
    """(관련도 점수순 시험, 0점으로 제외된 시험) 반환. 각 시험에 _relevance 점수가 붙는다.

    filter_relevant와 입력이 같고 출력만 keep/drop 대신 점수라, 거의 같은 비용으로
    "무관 제거"에 더해 "유관 순위"까지 얻는다 (실험 3 — 큰 풀에서 상위 N 재현율 올리기).
    같은 점수끼리는 검색 순서(구체적 검색어 먼저)가 유지된다. 채점 실패분은 중립 5점.
    풀이 크면 chunk_size개씩 나눠 호출한다 (응답 길이 한도 때문).
    """
    patient = _patient_summary(profile)
    scores: dict[str, int] = {}
    for i in range(0, len(candidates), chunk_size):
        part = candidates[i:i + chunk_size]
        trials = [{"nct_id": t["nct_id"], "title": t.get("title", ""),
                   "conditions": t.get("conditions", [])} for t in part]
        user = ("PATIENT:\n" + json.dumps(patient, ensure_ascii=False)
                + "\n\nTRIALS:\n" + json.dumps(trials, ensure_ascii=False, indent=1))
        try:
            verdicts = ask_json(RANK_SYSTEM_PROMPT, user, model=FILTER_MODEL)
            for v in verdicts:
                if isinstance(v, dict) and v.get("nct_id"):
                    try:
                        scores[v["nct_id"]] = max(0, min(10, int(v.get("score", 5))))
                    except (TypeError, ValueError):
                        pass
        except Exception as e:  # 채점 실패 시 해당 묶음은 중립 유지 (떨어뜨리지 않음)
            print(f"  관련도 채점 실패 → 묶음 {i // chunk_size + 1} 중립(5점) 유지: {e}")

    scored = [dict(t, _relevance=scores.get(t["nct_id"], 5)) for t in candidates]
    scored.sort(key=lambda t: -t["_relevance"])  # 안정 정렬 — 동점은 검색 순서 유지
    kept = [t for t in scored if t["_relevance"] > 0]
    dropped = [dict(t, _drop_reason="관련도 0점 (명백한 무관)")
               for t in scored if t["_relevance"] == 0]
    return kept, dropped


def filter_relevant(profile: dict, candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """(남긴 시험, 거른 시험) 반환. 거른 시험에는 _drop_reason이 붙는다."""
    patient = _patient_summary(profile)
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
