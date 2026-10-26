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
- Give 1-3 search queries (condition names in English), most specific first.
  e.g. "migraine with aura" before "migraine".
- Base queries on the suspected diagnosis and key findings only.

Respond with ONLY a JSON object, no other text:
{"queries": ["<condition query>", ...], "rationale": "<one sentence why>"}"""


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
    """프로필 → 검색어 1~3개 결정 (LLM 1회). 반환: {"queries": [...], "rationale": "..."}"""
    return ask_json(SYSTEM_PROMPT, json.dumps(profile, ensure_ascii=False))


def collect_pool(queries: list[str], per_query: int = 20, pool_cap: int | None = None) -> dict[str, dict]:
    """검색어들로 API를 돌려 중복 제거한 후보 풀을 만든다. pool_cap이 차면 추가 검색 생략."""
    seen: dict[str, dict] = {}
    for query in queries:
        for t in search_trials(query, max_results=per_query):
            if t["nct_id"] not in seen:
                seen[t["nct_id"]] = t
        if pool_cap and len(seen) >= pool_cap:
            break
    return seen


def search_candidates(profile: dict, max_candidates: int = 3, relevance: bool = False) -> dict:
    """프로필 → 검색어 결정(LLM) → API 검색 → 하드 필터 → (옵션) 관련성 필터 → 후보 반환.

    relevance=True면 제목·질환명만 보고 "정말 이 환자의 병에 관한 시험인가"를
    싼 모델로 한 번 거른다 (src/agents/relevance_filter.py — 1위 팀 방식).
    """
    plan = plan_queries(profile)
    seen = collect_pool(plan["queries"], pool_cap=max_candidates * 5 if not relevance else None)

    age = profile.get("age")
    if age is not None and profile.get("age_unit") == "months":
        age = age / 12
    candidates = hard_filter(list(seen.values()), age, profile.get("sex"))

    dropped = []
    if relevance and candidates:
        from src.agents.relevance_filter import filter_relevant
        candidates, dropped = filter_relevant(profile, candidates)

    return {
        "queries": plan["queries"],
        "rationale": plan.get("rationale", ""),
        "total_found": len(seen),
        "after_hard_filter": len(candidates) + len(dropped),
        "after_relevance": len(candidates) if relevance else None,
        "dropped_irrelevant": [{"nct_id": d["nct_id"], "reason": d.get("_drop_reason", "")}
                               for d in dropped],
        "candidates": candidates[:max_candidates],
    }
