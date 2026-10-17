"""질문 루프 실제 실행: 질문 → 환자 시뮬레이터 답변 → 관련 기준만 재판정 (비용 발생).

실행: python scripts/run_reassess_demo.py                  # S004, 최대 2라운드 + 마지막 전체 재판정
      python scripts/run_reassess_demo.py --no-full-check  # 전체 재판정 생략 (부분 재판정만 보고 싶을 때)

- 시작 판정은 평가 세트의 저장된 v3 판정(S004 × 시험 2개)을 써서 1~4번 비용이 들지 않는다
- 답변은 src/testing/patient_simulator.py의 S004_FACT_SHEET로 시뮬레이터가 만든다
- 질문은 src/question_builder.py (서현 v2.1 프롬프트로 여러 시험에 걸친 정보를 묶어 질문, 10/17부터)
- AI 호출: 라운드마다 질문 생성 1 + 시뮬레이터 1 + 재판정(답이 걸린 시험 수만큼)
  + 마지막 전체 재판정(시험 수만큼). Sonnet 5.5 기준 약 $0.1~0.3. 실제 비용은 끝에 출력
결과: data/processed/reassess_demo_S004.json (handoff 형식 + rounds)
실행 기록: docs/질문루프_정리.md 6절 (10/16 첫 실행 결과 파일은 커밋 057ba65)
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.llm import spent  # noqa: E402
from src.pipeline import final_check, next_round, reassess  # noqa: E402
from src.testing.goldset_bundle import make_bundle  # noqa: E402
from src.testing.patient_simulator import S004_FACT_SHEET, answer_questions  # noqa: E402

KO = {"pass": "통과", "fail": "탈락", "unknown": "모름", "post_enrollment": "등록 후 확인", None: "(없음)"}
FINAL_KO = {"eligible": "적격", "probably_eligible": "적격 가능", "insufficient_info": "정보 부족", "ineligible": "부적격"}
MAX_ROUNDS = 2


def counts(bundle: dict) -> str:
    out = []
    for t in bundle["trials"]:
        n = sum(j["verdict"] == "unknown" for j in t["judgments"])
        out.append(f"{t['nct_id']} {FINAL_KO[t['final_judgment']]} (모름 {n})")
    return " / ".join(out)


def main() -> None:
    bundle = make_bundle("S004")
    print(f"시작: {counts(bundle)}")
    for _ in range(MAX_ROUNDS):
        questions = next_round(bundle, max_questions=5)
        if not questions:
            print("\n더 물을 것이 없음")
            break
        r = bundle["rounds"][-1]["round"]
        qa = answer_questions(S004_FACT_SHEET, [{"question": q["text"]} for q in questions])
        answers = [{"question_id": q["id"], "answer": a["answer"]} for q, a in zip(questions, qa)]
        print(f"\n── 라운드 {r} ──")
        for q, a in zip(questions, answers):
            print(f"{q['id']}. {q['text']}\n    → {a['answer']}   (관련: {q['resolves']})")
        changed = reassess(bundle, answers)
        print("바뀐 판정:")
        for c in changed:
            print(f"  {c['trial']} {c['criterion_id']}: {KO[c['from']]} → {KO[c['to']]} (근거 {', '.join(c['source'])})")
        print(f"지금: {counts(bundle)}")

    if "--no-full-check" not in sys.argv:
        changed = final_check(bundle)
        print(f"\n── 마지막 전체 재판정 ── 바뀐 판정 {len(changed)}개")
        for c in changed:
            print(f"  {c['trial']} {c['criterion_id']}: {KO[c['from']]} → {KO[c['to']]}")
        print(f"최종: {counts(bundle)}")

    out = ROOT / "data" / "processed" / "reassess_demo_S004.json"
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out.relative_to(ROOT)}")
    print(f"AI 호출 {spent['calls']}번, 비용 약 ${spent['usd']:.3f}")


if __name__ == "__main__":
    main()
