"""2번 에이전트: 임상시험 후보 검색. PatientProfile → TrialCandidate 목록.

LLM 없이 코드로만 동작한다.
- 검색어: 1번이 추정한 진단명(name_en)을 그대로 쓴다
- ClinicalTrials.gov API v2에서 모집 중(RECRUITING) 시험을 가져온다
- 나이·성별은 코드로 거른다 (거른 이유는 filter_notes에 남김). 판정이 아니라 명백한 불일치만 제외

사용 예:
    python -m agents.search_agent --condition "acute pancreatitis" --age 54 --sex male
    python -m agents.search_agent --profiles outputs/patient_profiles.json      # 1번 결과로 전체 검색
"""

import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from .llm import ROOT
from .schemas import PatientProfile, TrialCandidate

API = "https://clinicaltrials.gov/api/v2/studies"
FIELDS = "NCTId|BriefTitle|ConditionsModule|DesignModule|EligibilityModule|ContactsLocationsModule"


def parse_age(text):
    """'18 Years' → 18.0, '6 Months' → 0.5. 값이 없으면 None (제한 없음)."""
    if not text:
        return None
    m = re.match(r"([\d.]+)\s*(Year|Month|Week|Day)", text)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2)
    return n / {"Year": 1, "Month": 12, "Week": 52.18, "Day": 365.25}[unit]


def fetch(condition: str, page_size: int = 50) -> list[dict]:
    q = urllib.parse.urlencode({
        "query.cond": condition,
        "filter.overallStatus": "RECRUITING",
        "pageSize": page_size,
        "fields": FIELDS,
    })
    with urllib.request.urlopen(f"{API}?{q}", timeout=60) as r:
        return json.load(r).get("studies", [])


def to_candidate(study: dict, query: str) -> TrialCandidate:
    p = study["protocolSection"]
    e = p.get("eligibilityModule", {})
    locs = p.get("contactsLocationsModule", {}).get("locations", [])
    nct = p["identificationModule"]["nctId"]
    return TrialCandidate(
        nct_id=nct,
        title=p["identificationModule"].get("briefTitle", ""),
        conditions=p.get("conditionsModule", {}).get("conditions", []),
        study_type=p.get("designModule", {}).get("studyType", ""),
        phases=p.get("designModule", {}).get("phases", []) or [],
        min_age_years=parse_age(e.get("minimumAge")),
        max_age_years=parse_age(e.get("maximumAge")),
        sex=e.get("sex", "ALL"),
        countries=list(dict.fromkeys(l.get("country", "") for l in locs if l.get("country"))),
        eligibility_text=e.get("eligibilityCriteria", ""),
        url=f"https://clinicaltrials.gov/study/{nct}",
        search_query=query,
    )


def hard_filter(c: TrialCandidate, age, sex) -> list[str]:
    """명백한 불일치만 찾는다. 빈 목록이면 통과."""
    notes = []
    if age is not None:
        if c.min_age_years is not None and age < c.min_age_years:
            notes.append(f"나이 {age:g}세 < 최소 {c.min_age_years:g}세")
        if c.max_age_years is not None and age > c.max_age_years:
            notes.append(f"나이 {age:g}세 > 최대 {c.max_age_years:g}세")
    if sex in ("male", "female") and c.sex not in ("ALL", sex.upper()):
        notes.append(f"성별 제한 {c.sex}")
    if not c.eligibility_text.strip():
        notes.append("기준 원문 없음")
    return notes


def search(conditions: list[str], age=None, sex="unknown", page_size: int = 50, interventional_only: bool = False):
    """여러 검색어로 찾고 NCT 번호로 중복을 없앤다. (통과 목록, 걸러진 목록) 반환."""
    seen, kept, dropped = set(), [], []
    for cond in conditions:
        for s in fetch(cond, page_size):
            c = to_candidate(s, cond)
            if c.nct_id in seen:
                continue
            seen.add(c.nct_id)
            c.filter_notes = hard_filter(c, age, sex)
            if interventional_only and c.study_type != "INTERVENTIONAL":
                c.filter_notes.append("중재 연구 아님")
            (dropped if c.filter_notes else kept).append(c)
    return kept, dropped


def search_for_profile(profile: PatientProfile, **kw):
    conds = [d.name_en for d in profile.suspected_diagnoses if d.confidence in ("high", "medium")] or \
            [d.name_en for d in profile.suspected_diagnoses[:1]]
    return search(conds, profile.age_years, profile.sex, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", nargs="*", help="검색어 직접 입력")
    ap.add_argument("--age", type=float)
    ap.add_argument("--sex", default="unknown")
    ap.add_argument("--profiles", help="1번 에이전트 결과 파일")
    ap.add_argument("--page-size", type=int, default=50)
    ap.add_argument("--out", default=str(ROOT / "outputs" / "trial_candidates.json"))
    args = ap.parse_args()

    results = {}
    if args.profiles:
        profiles = json.loads(Path(args.profiles).read_text(encoding="utf-8"))
        for pid, d in profiles.items():
            prof = PatientProfile(**d)
            kept, dropped = search_for_profile(prof, page_size=args.page_size)
            results[pid] = {"kept": [c.model_dump() for c in kept], "dropped": [c.model_dump() for c in dropped]}
            q = ", ".join(sorted({c.search_query for c in kept + dropped}))
            print(f"{pid} | 검색어: {q} | 후보 {len(kept)}개 (나이·성별로 제외 {len(dropped)}개)")
    else:
        kept, dropped = search(args.condition, args.age, args.sex, page_size=args.page_size)
        results["manual"] = {"kept": [c.model_dump() for c in kept], "dropped": [c.model_dump() for c in dropped]}
        print(f"후보 {len(kept)}개 · 제외 {len(dropped)}개")
        for c in kept[:10]:
            print(f"  {c.nct_id} | {c.min_age_years}-{c.max_age_years} {c.sex} | {c.title[:70]}")
        for c in dropped[:5]:
            print(f"  (제외) {c.nct_id} | {'; '.join(c.filter_notes)} | {c.title[:50]}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
