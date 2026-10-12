"""로드맵 4단계: 질문 루프 — 답변 → 프로필 갱신 → 재평가.

S004(방광암 의심, 기준이 가장 복잡) × 임상시험 1개로 검증:

  [1] 프로필 → [3] 파싱 → [4] 매칭 (1차)
  → [5] 질문 생성 → (환자 답변) → [5b] 프로필 갱신 → [4] 재평가 (2차)
  → 판정 변화 "이전 → 이후" 출력

환자 답변은 기본적으로 시뮬레이터(가상 사실관계)가 자동 생성.
--interactive 옵션을 주면 터미널에서 직접 답할 수 있다.

실행: python scripts/run_interactive_demo.py [--interactive]
비용: LLM 호출 약 7회
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.criteria_parser import parse_criteria
from src.agents.matcher import final_judgment, match
from src.agents.patient_profiler import profile_patient
from src.agents.profile_updater import update_profile
from src.agents.question_generator import generate_questions
from src.testing.patient_simulator import S004_FACT_SHEET, answer_questions

PATIENT_ID = "S004"
TRIAL_INDEX = 0
MAX_ROUNDS = 2  # 1차 평가 + 질문 1라운드 + 재평가

VERDICT_KO = {"pass": "통과", "fail": "탈락", "unknown": "모름", "post_enrollment": "등록 후 확인"}
FINAL_KO = {
    "eligible": "적격",
    "probably_eligible": "적격 가능 (등록 후 확인 필요)",
    "insufficient_info": "정보 부족",
    "ineligible": "부적격",
}


def print_sheet(criteria: list[dict], judgments: list[dict]) -> None:
    crit_by_id = {c["id"]: c for c in criteria}
    for j in judgments:
        c = crit_by_id.get(j["criterion_id"], {})
        print(f"  [{j['criterion_id']}] {VERDICT_KO.get(j['verdict'], j['verdict'])}"
              f" — {c.get('text', '')[:55]}")


def print_diff(old: list[dict], new: list[dict]) -> None:
    """재평가에서 바뀐 판정만 '이전 → 이후'로 표시 (킥오프 재평가 에이전트 요구사항)."""
    old_by_id = {j["criterion_id"]: j for j in old}
    changed = 0
    for j in new:
        prev = old_by_id.get(j["criterion_id"])
        if prev and prev["verdict"] != j["verdict"]:
            changed += 1
            print(f"  [{j['criterion_id']}] {VERDICT_KO[prev['verdict']]} → "
                  f"{VERDICT_KO[j['verdict']]} | 근거: {j['evidence'][:90]}")
    print(f"  (판정 변경 {changed}건, 유지 {len(new) - changed}건)")


def main() -> None:
    interactive = "--interactive" in sys.argv

    # ── 입력 로드 ─────────────────────────────────────────────
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

    # ── [1] 프로필 ────────────────────────────────────────────
    print("[1] 환자 정보 이해 에이전트 실행 중...")
    profile = profile_patient(case_text)
    profile["id"] = PATIENT_ID

    # ── [3] 기준 파싱 (캐시) ──────────────────────────────────
    criteria_path = ROOT / "data" / "processed" / f"criteria_{trial['nct_id']}.json"
    if criteria_path.exists():
        criteria = json.loads(criteria_path.read_text(encoding="utf-8"))
        print(f"[3] 기준 파싱: 캐시 재사용 ({len(criteria)}개)")
    else:
        print("[3] 기준 파싱 에이전트 실행 중...")
        criteria = parse_criteria(trial["eligibility_criteria"])
        criteria_path.write_text(json.dumps(criteria, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"    조건 {len(criteria)}개")

    rounds = []
    judgments = None
    for round_no in range(1, MAX_ROUNDS + 1):
        # ── [4] 매칭 (1차/재평가) ────────────────────────────
        label = "1차 평가" if round_no == 1 else f"재평가 (라운드 {round_no})"
        print(f"\n[4] 매칭·추론 — {label} 중...")
        new_judgments = match(profile, criteria)
        judgment = final_judgment(new_judgments)

        if round_no == 1:
            print_sheet(criteria, new_judgments)
        else:
            print("  == 판정 변화 (이전 → 이후) ==")
            print_diff(judgments, new_judgments)
        judgments = new_judgments
        print(f"  최종 판단: {FINAL_KO[judgment]}")
        rounds.append({"round": round_no, "judgments": judgments, "final_judgment": judgment,
                       "profile_snapshot": json.loads(json.dumps(profile))})

        if judgment != "insufficient_info" or round_no == MAX_ROUNDS:
            break

        # ── [5] 질문 생성 ────────────────────────────────────
        print("\n[5] 질문 생성 에이전트 실행 중...")
        questions = generate_questions(criteria, judgments)
        qa_pairs = []
        if interactive:
            for q in questions:
                print(f"\nQ. {q['question']}")
                answer = input("A. ")
                qa_pairs.append({"question": q["question"], "answer": answer})
        else:
            print("    (환자 시뮬레이터가 자동 응답)")
            qa_pairs = answer_questions(S004_FACT_SHEET, questions)
            for qa in qa_pairs:
                print(f"\n  Q. {qa['question']}\n  A. {qa['answer']}")
        rounds[-1]["questions"] = questions
        rounds[-1]["answers"] = qa_pairs

        # ── [5b] 프로필 갱신 ─────────────────────────────────
        print("\n[5b] 프로필 갱신 에이전트 실행 중...")
        profile = update_profile(profile, qa_pairs)
        print(json.dumps(profile, ensure_ascii=False, indent=2))

    # ── 저장 ──────────────────────────────────────────────────
    out_path = ROOT / "data" / "processed" / f"interactive_{PATIENT_ID}_{trial['nct_id']}.json"
    out_path.write_text(
        json.dumps({"patient_id": PATIENT_ID, "nct_id": trial["nct_id"], "rounds": rounds},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n저장: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
