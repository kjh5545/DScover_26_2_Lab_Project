"""[2] 후보 검색 에이전트 + 하드 필터.

LLM이 환자 프로필을 보고 ClinicalTrials.gov 검색어를 정하고,
API를 도구로 호출해 모집 중인 후보 시험을 가져온다.
나이·성별은 LLM 판정에 맡기지 않고 **코드로 먼저 거른다** (하드 필터).

킥오프 제안 2 근거: "장소를 기준처럼 판정하기도, 메모로만 다루기도 함"
→ 기계적으로 확정 가능한 조건(나이·성별)은 코드가 거르면 LLM 호출 수도 줄고 흔들림도 없다.
"""

import json
import re

from src.llm import ask_json
from src.tools.clinicaltrials_api import search_trials

SYSTEM_PROMPT = """You are a clinical trial search agent.

Given a structured patient profile, decide what to search on
ClinicalTrials.gov to find trials this patient might join.

Rules:
- Give 5-8 search queries (English), most specific first:
  1. the suspected diagnosis, specific then general
     (e.g. "migraine with aura", then "migraine")
  2. common synonyms or alternative medical names for the same diagnosis
     (e.g. "infantile hypertrophic pyloric stenosis" / "pyloric stenosis")
  3. 1-3 key symptoms or findings usable as standalone search terms
     (e.g. "projectile vomiting", "chronic cough")
- Base every query on the profile only. Do not invent a diagnosis
  that the findings do not support.

Respond with ONLY a JSON object, no other text:
{"queries": ["<query>", ...], "rationale": "<one sentence why>"}"""


def _parse_age_years(age_str: str | None) -> float | None:
    """'18 Years', '6 Months' 같은 API 나이 문자열을 '년' 단위 숫자로 변환."""
    if not age_str:
        return None
    m = re.match(r"([\d.]+)\s*(Year|Month|Week|Day)", age_str, re.IGNORECASE)
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2).lower()
    per_year = {"year": 1, "month": 12, "week": 52, "day": 365}[unit]
    return value / per_year if unit != "year" else value


def hard_filter(trials: list[dict], age_years: float | None, sex: str | None) -> list[dict]:
    """나이·성별로 기계적으로 확정되는 시험을 걸러낸다 (LLM 불필요)."""
    kept = []
    for t in trials:
        if not t.get("eligibility_criteria"):
            continue  # 기준 원문이 없으면 판정 불가 → 제외
        if age_years is not None:
            min_age = _parse_age_years(t.get("minimum_age"))
            max_age = _parse_age_years(t.get("maximum_age"))
            if min_age is not None and age_years < min_age:
                continue
            if max_age is not None and age_years > max_age:
                continue
        trial_sex = (t.get("sex") or "ALL").upper()
        if sex and trial_sex != "ALL":
            if (sex == "M" and trial_sex == "FEMALE") or (sex == "F" and trial_sex == "MALE"):
                continue
        kept.append(t)
    return kept


def plan_queries(profile: dict) -> dict:
    """프로필 → 검색어 5~8개 결정 (LLM 1회). 반환: {"queries": [...], "rationale": "..."}

    검색어 하나로는 표기 차이(동의어)나 증상 중심 등록 시험을 놓친다 —
    재현율 측정에서 미스의 한 축이 "검색어로 안 잡힘"이었다 (TrialGPT도 다중 키워드).
    """
    return ask_json(SYSTEM_PROMPT, json.dumps(profile, ensure_ascii=False))


def collect_pool(queries: list[str], per_query: int = 200, pool_cap: int | None = None) -> dict[str, dict]:
    """검색어들로 API를 돌려 중복 제거한 후보 풀을 만든다. pool_cap이 차면 추가 검색 생략.

    per_query 기본 200: 50에서는 페이지 한도로 정답 3건을 놓쳤다 (재현율 측정에서 검증).
    API는 무료라 늘려도 비용은 그대로다.
    """
    seen: dict[str, dict] = {}
    for query in queries:
        for t in search_trials(query, max_results=per_query):
            if t["nct_id"] not in seen:
                seen[t["nct_id"]] = t
        if pool_cap and len(seen) >= pool_cap:
            break
    return seen


def search_candidates(profile: dict, max_candidates: int = 3, relevance: bool = False,
                      rank: bool = False) -> dict:
    """프로필 → 검색어 결정(LLM) → API 검색 → 하드 필터 → (옵션) 관련성 거르기/랭킹 → 후보.

    relevance=True: 제목·질환명만 보고 확신 있는 무관만 거른다 (keep/drop).
    rank=True: 같은 입력으로 관련도 0~10점을 매겨 점수순 정렬, 0점만 제외 (실험 3).
      풀이 커져도(검색어 5~8개 × 200건) 정답이 상위 N에 들 수 있게 하는 핵심.
      둘 다 켜면 rank가 우선. 어느 쪽도 Haiku라 비용은 거의 같다.
    """
    plan = plan_queries(profile)
    llm_screen = rank or relevance
    seen = collect_pool(plan["queries"], pool_cap=None if llm_screen else max_candidates * 5)

    age = profile.get("age")
    if age is not None and profile.get("age_unit") == "months":
        age = age / 12
    candidates = hard_filter(list(seen.values()), age, profile.get("sex"))

    dropped = []
    if candidates and rank:
        from src.agents.relevance_filter import rank_relevant
        candidates, dropped = rank_relevant(profile, candidates)
    elif candidates and relevance:
        from src.agents.relevance_filter import filter_relevant
        candidates, dropped = filter_relevant(profile, candidates)

    return {
        "queries": plan["queries"],
        "rationale": plan.get("rationale", ""),
        "total_found": len(seen),
        "after_hard_filter": len(candidates) + len(dropped),
        "after_relevance": len(candidates) if llm_screen else None,
        "dropped_irrelevant": [{"nct_id": d["nct_id"], "reason": d.get("_drop_reason", "")}
                               for d in dropped],
        "candidates": candidates[:max_candidates],
    }
