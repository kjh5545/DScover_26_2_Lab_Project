"""로드맵 2단계 (첫 마일스톤): 환자 1명 × 임상시험 1개 파이프라인.

S005(조짐 편두통 의심) × NCT07022496 를 대상으로
[1] 환자 정보 이해 → [3] 기준 파싱 → [4] 매칭·추론 → 최종 판단
→ (정보 부족이면) [5] 질문 생성
을 함수 호출로 직선으로 이어붙인다. 프레임워크 없음.

실행: python scripts/run_pipeline_demo.py
비용: LLM 호출 2~3회 (기준 파싱은 캐시가 있으면 재사용)
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.criteria_parser import parse_criteria
from src.agents.matcher import final_judgment, match
from src.agents.patient_profiler import profile_patient
from src.agents.question_generator import generate_questions

PATIENT_ID = "S005"
TRIAL_INDEX = 0  # S005.json 안에서 몇 번째 시험을 쓸지

VERDICT_KO = {
    "pass": "통과",
    "fail": "탈락",
    "unknown": "모름",
    "post_enrollment": "등록 후 확인",
}
FINAL_KO = {
    "eligible": "적격",
    "probably_eligible": "적격 가능 (등록 후 확인 필요)",
    "insufficient_info": "정보 부족 (확인 질문 필요)",
    "ineligible": "부적격",
}


def main() -> None:
    # ── 입력 데이터 로드 ──────────────────────────────────────
    patients = json.loads(
        (ROOT / "data" / "raw" / "official_synthetic_patients.json").read_text(encoding="utf-8")
    )
    case_text = next(t["title"] for t in patients["topics"] if t["num"] == PATIENT_ID)

    trials = json.loads(
        (ROOT / "data" / "raw" / "trials" / f"{PATIENT_ID}.json").read_text(encoding="utf-8")
    )
    trial = trials["trials"][TRIAL_INDEX]
    print(f"환자 {PATIENT_ID}: {case_text}\n")
    print(f"시험 {trial['nct_id']}: {trial['title']}\n")

    # ── [1] 환자 정보 이해 ────────────────────────────────────
    print("[1] 환자 정보 이해 에이전트 실행 중...")
    profile = profile_patient(case_text)
    profile["id"] = PATIENT_ID
    print(json.dumps(profile, ensure_ascii=False, indent=2), "\n")

    # ── [3] 기준 파싱 (캐시 재사용) ───────────────────────────
    criteria_path = ROOT / "data" / "processed" / f"criteria_{trial['nct_id']}.json"
    if criteria_path.exists():
        print(f"[3] 기준 파싱: 캐시 재사용 ({criteria_path.name})")
        criteria = json.loads(criteria_path.read_text(encoding="utf-8"))
    else:
        print("[3] 기준 파싱 에이전트 실행 중...")
        criteria = parse_criteria(trial["eligibility_criteria"])
        criteria_path.parent.mkdir(parents=True, exist_ok=True)
        criteria_path.write_text(
            json.dumps(criteria, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"    조건 {len(criteria)}개\n")

    # ── [4] 매칭·추론 ─────────────────────────────────────────
    print("[4] 매칭·추론 에이전트 실행 중...")
    judgments = match(profile, criteria)

    print("\n=== 스크리닝 시트 ===")
    crit_by_id = {c["id"]: c for c in criteria}
    for j in judgments:
        c = crit_by_id.get(j["criterion_id"], {})
        verdict = VERDICT_KO.get(j["verdict"], j["verdict"])
        print(f"[{j['criterion_id']}] ({c.get('type', '?')}) {c.get('text', '')[:60]}")
        print(f"      판정: {verdict} | 근거: {j['evidence']}")

    # ── 최종 판단 (코드 규칙) ─────────────────────────────────
    judgment = final_judgment(judgments)
    print(f"\n=== 최종 판단: {FINAL_KO[judgment]} ===\n")

    # ── [5] 질문 생성 (탈락 확정이면 호출하지 않음 — 규칙 9) ──
    questions = []
    if judgment == "insufficient_info":
        print("[5] 질문 생성 에이전트 실행 중...")
        questions = generate_questions(criteria, judgments)
        print("\n=== 환자에게 물을 확인 질문 ===")
        for i, q in enumerate(questions, 1):
            print(f"{i}. {q['question']}   (관련 기준: {', '.join(q['criterion_ids'])})")
    elif judgment == "ineligible":
        print("[5] 질문 생성: 건너뜀 (탈락 확정 시 질문하지 않음)")

    # ── 결과 저장 ─────────────────────────────────────────────
    result = {
        "patient_id": PATIENT_ID,
        "nct_id": trial["nct_id"],
        "profile": profile,
        "judgments": judgments,
        "final_judgment": judgment,
        "questions": questions,
    }
    out_path = ROOT / "data" / "processed" / f"screening_{PATIENT_ID}_{trial['nct_id']}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
