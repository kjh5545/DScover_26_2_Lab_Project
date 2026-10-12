"""에이전트 1~4번 파이프라인 실행 (담당: 해준).

사용법:
    python scripts/run_intake.py S005            # 예시 환자, 후보 3건, 매칭 포함
    python scripts/run_intake.py S005 --n 2      # 후보 2건만
    python scripts/run_intake.py S005 --no-screen  # 파싱([3])까지만, 매칭 생략

결과: data/handoff/{환자ID}.json  (형식: docs/HANDOFF.md)
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.pipeline import run_intake

FINAL_KO = {
    "eligible": "적격",
    "probably_eligible": "적격 가능 (등록 후 확인 필요)",
    "insufficient_info": "정보 부족",
    "ineligible": "부적격",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("patient", help="예시 환자 ID (S001~S010)")
    parser.add_argument("--n", type=int, default=3, help="스크리닝할 후보 수 (기본 3)")
    parser.add_argument("--no-screen", action="store_true", help="매칭([4]) 생략, 파싱까지만")
    args = parser.parse_args()

    patients = json.loads(
        (ROOT / "data" / "raw" / "official_synthetic_patients.json").read_text(encoding="utf-8")
    )
    case_text = next(t["title"] for t in patients["topics"] if t["num"] == args.patient)
    print(f"환자 {args.patient}: {case_text}\n")

    bundle = run_intake(case_text, patient_id=args.patient,
                        max_candidates=args.n, do_screen=not args.no_screen)

    print(f"[1] 프로필: 추정 진단 = {bundle['profile'].get('suspected_diagnosis')}")
    print(f"[2] 검색: {bundle['search']['queries']} → 필터 후 {bundle['search']['after_hard_filter']}건")
    for t in bundle["trials"]:
        line = f"[3] {t['nct_id']} 조건 {len(t['criteria'])}개"
        if "final_judgment" in t:
            line += f" → [4] {FINAL_KO[t['final_judgment']]}"
        print(f"{line} — {t['title'][:60]}")
    print(f"\n저장: data/handoff/{args.patient}.json (단계 {bundle['meta']['stages']})")


if __name__ == "__main__":
    main()
