"""로드맵 3단계: 환자 1명 → 후보 검색 → 시험별 스크리닝 → 추천 순위.

흐름: [1] 프로필 (저장본 재사용) → [2] 검색+하드필터 → 시험마다 ([3] 파싱 → [4] 매칭)
      → [6] 순위 (코드) → [7] 설명 리포트 (LLM)

실행: python scripts/run_recommend_demo.py
비용: 검색 1회 + (새 시험 수 × 파싱 1회 + 매칭 1회) + 설명 1회
      기본 후보 3건 기준 LLM 호출 최대 8회
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.criteria_parser import parse_criteria
from src.agents.matcher import final_judgment, match
from src.agents.patient_profiler import profile_patient
from src.agents.recommender import explain, rank_trials
from src.agents.trial_searcher import search_candidates

PATIENT_ID = "S005"
MAX_CANDIDATES = 3

FINAL_KO = {
    "eligible": "적격",
    "probably_eligible": "적격 가능 (등록 후 확인 필요)",
    "insufficient_info": "정보 부족 (확인 질문 필요)",
    "ineligible": "부적격",
}


def get_profile() -> dict:
    """이전 단계에서 만든 프로필이 있으면 재사용 (LLM 호출 절약)."""
    for f in (ROOT / "data" / "processed").glob(f"screening_{PATIENT_ID}_*.json"):
        saved = json.loads(f.read_text(encoding="utf-8"))
        if "profile" in saved:
            print(f"[1] 프로필: 저장본 재사용 ({f.name})")
            return saved["profile"]
    patients = json.loads(
        (ROOT / "data" / "raw" / "official_synthetic_patients.json").read_text(encoding="utf-8")
    )
    case_text = next(t["title"] for t in patients["topics"] if t["num"] == PATIENT_ID)
    print("[1] 환자 정보 이해 에이전트 실행 중...")
    profile = profile_patient(case_text)
    profile["id"] = PATIENT_ID
    return profile


def get_criteria(trial: dict) -> list[dict]:
    """기준 파싱 (NCT ID별 캐시)."""
    path = ROOT / "data" / "processed" / f"criteria_{trial['nct_id']}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    criteria = parse_criteria(trial["eligibility_criteria"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(criteria, ensure_ascii=False, indent=2), encoding="utf-8")
    return criteria


def main() -> None:
    profile = get_profile()

    # ── [2] 후보 검색 + 하드 필터 ─────────────────────────────
    print("\n[2] 후보 검색 에이전트 실행 중...")
    search = search_candidates(profile, max_candidates=MAX_CANDIDATES)
    print(f"    검색어: {search['queries']} ({search['rationale']})")
    print(f"    검색 결과 {search['total_found']}건 → 하드 필터(나이·성별) 후 {search['after_hard_filter']}건 → 상위 {len(search['candidates'])}건 스크리닝")

    # ── 시험마다 [3] 파싱 → [4] 매칭 ──────────────────────────
    screenings = []
    for i, trial in enumerate(search["candidates"], 1):
        print(f"\n[{i}/{len(search['candidates'])}] {trial['nct_id']}: {trial['title'][:70]}")
        criteria = get_criteria(trial)
        print(f"    기준 {len(criteria)}개 → 매칭 중...")
        judgments = match(profile, criteria)
        judgment = final_judgment(judgments)
        print(f"    최종 판단: {FINAL_KO[judgment]}")
        screenings.append(
            {
                "nct_id": trial["nct_id"],
                "title": trial["title"],
                "criteria": criteria,
                "judgments": judgments,
                "final_judgment": judgment,
            }
        )

    # ── [6] 순위 (코드 규칙) ──────────────────────────────────
    ranking = rank_trials(screenings)
    print("\n=== 추천 순위 ===")
    if not ranking["recommended"]:
        print("추천할 수 있는 시험 없음")
    for i, s in enumerate(ranking["recommended"], 1):
        counts = {}
        for j in s["judgments"]:
            counts[j["verdict"]] = counts.get(j["verdict"], 0) + 1
        print(f"{i}위. {s['nct_id']} — {FINAL_KO[s['final_judgment']]} "
              f"(통과 {counts.get('pass', 0)} / 모름 {counts.get('unknown', 0)} / 등록후확인 {counts.get('post_enrollment', 0)})")
    for s in ranking["excluded"]:
        fails = [j["criterion_id"] for j in s["judgments"] if j["verdict"] == "fail"]
        print(f"제외. {s['nct_id']} — 부적격 (탈락 기준: {', '.join(fails)})")

    # ── [7] 결과 설명 리포트 (LLM) ────────────────────────────
    print("\n[7] 결과 설명 에이전트 실행 중...\n")
    report = explain(profile, ranking)
    print("=== 최종 리포트 ===")
    print(report)

    # ── 저장 ──────────────────────────────────────────────────
    result = {
        "patient_id": PATIENT_ID,
        "profile": profile,
        "search": {k: v for k, v in search.items() if k != "candidates"},
        "screenings": screenings,
        "ranking": {
            "recommended": [s["nct_id"] for s in ranking["recommended"]],
            "excluded": [s["nct_id"] for s in ranking["excluded"]],
        },
        "report": report,
    }
    out_path = ROOT / "data" / "processed" / f"recommendation_{PATIENT_ID}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
