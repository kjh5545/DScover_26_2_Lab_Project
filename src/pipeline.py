"""에이전트 1~4번 파이프라인 (담당: 해준).

[1] 환자 정보 이해 → [2] 후보 검색 + 하드 필터 → [3] 기준 파싱 → [4] 매칭·추론

단일 진입점 run_intake() 가 전 단계를 실행하고, 결과를 표준 전달 형식으로
data/handoff/{patient_id}.json 에 저장한다. 이후 단계(질문 생성·추천) 담당
팀원은 이 파일만 읽으면 된다. 형식 명세: docs/HANDOFF.md

사용 예:
    from src.pipeline import run_intake
    bundle = run_intake("A 34-year-old woman ...", patient_id="S005")
"""

import datetime
import json
from pathlib import Path

from src.agents.criteria_parser import parse_criteria
from src.agents.matcher import final_judgment, match
from src.agents.patient_profiler import profile_patient
from src.agents.trial_searcher import search_candidates
from src.llm import MODEL

ROOT = Path(__file__).resolve().parent.parent
PROMPT_VERSION = "v3"  # 2026-10-12: goldset v1.1 결정 + 환자 원문 입력 (v2: 2026-10-08 회의 결정)


# ── 단계별 함수 (개별 호출도 가능) ──────────────────────────

def understand_patient(case_text: str, patient_id: str | None = None) -> dict:
    """[1] 환자 줄글 → 구조화 프로필 (환자 ID가 있으면 디스크 캐시 사용)."""
    cache = ROOT / "data" / "processed" / "eval_cache" / f"profile_{patient_id}.json" \
        if patient_id else None
    if cache and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    profile = profile_patient(case_text)
    if patient_id:
        profile["id"] = patient_id
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


def find_candidates(profile: dict, max_candidates: int = 3) -> dict:
    """[2] 프로필 → 검색어 결정(LLM) → ClinicalTrials.gov 검색 → 나이·성별 하드 필터."""
    return search_candidates(profile, max_candidates=max_candidates)


def parse_trial(trial: dict) -> list[dict]:
    """[3] 시험의 eligibility criteria 원문 → 원자 조건 목록 (NCT ID별 디스크 캐시)."""
    path = ROOT / "data" / "processed" / f"criteria_{trial['nct_id']}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    criteria = parse_criteria(trial["eligibility_criteria"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(criteria, ensure_ascii=False, indent=2), encoding="utf-8")
    return criteria


def screen(profile: dict, criteria: list[dict], case_text: str | None = None) -> tuple[list[dict], str]:
    """[4] 조건별 4단계 판정 + 근거 → (판정 목록, 최종 판단). case_text: 환자 원문 (v3)."""
    judgments = match(profile, criteria, case_text=case_text)
    return judgments, final_judgment(judgments)


# ── 단일 진입점 ─────────────────────────────────────────────

def run_intake(case_text: str, patient_id: str = "CUSTOM",
               max_candidates: int = 3, do_screen: bool = True,
               save: bool = True) -> dict:
    """1→2→3(→4) 전체 실행 후 전달 형식(bundle)을 반환·저장한다.

    do_screen=False 면 매칭([4])을 건너뛰고 파싱까지만 수행
    (질문 생성 담당이 매칭을 직접 돌려보고 싶을 때).
    """
    profile = understand_patient(case_text, patient_id)
    search = find_candidates(profile, max_candidates=max_candidates)

    trials = []
    for t in search["candidates"]:
        entry = {
            "nct_id": t["nct_id"],
            "title": t["title"],
            "eligibility_criteria": t["eligibility_criteria"],
            "minimum_age": t.get("minimum_age"),
            "maximum_age": t.get("maximum_age"),
            "sex": t.get("sex"),
            "criteria": parse_trial(t),
        }
        if do_screen:
            entry["judgments"], entry["final_judgment"] = screen(profile, entry["criteria"], case_text)
        trials.append(entry)

    bundle = {
        "patient_id": patient_id,
        "case_text": case_text,
        "profile": profile,
        "search": {k: v for k, v in search.items() if k != "candidates"},
        "trials": trials,
        "meta": {
            "model": MODEL,
            "prompt_version": PROMPT_VERSION,
            "created": datetime.date.today().isoformat(),
            "stages": "1-4" if do_screen else "1-3",
        },
    }
    if save:
        out = ROOT / "data" / "handoff" / f"{patient_id}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return bundle
