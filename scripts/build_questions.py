"""질문 파일 생성 (튜토리얼 Step 2): handoff/<환자>.json → questions/<환자>.json

사용법:
    python scripts/build_questions.py S005            # AI가 서현 v2.1 규칙으로 묶어서 질문 작성 (호출 1회, 약 $0.01~0.02)
    python scripts/build_questions.py S005 --no-llm   # needed_info 글자가 같은 것끼리 묶고 임시 문장, 무료 (흐름 확인용)
    python scripts/build_questions.py S005 --top 5    # 질문 수 (기본 5)
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.question_builder import build_questions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("patient", help="환자 ID (data/handoff/<ID>.json 필요)")
    parser.add_argument("--top", type=int, default=5, help="질문 수 상한 (기본 5)")
    parser.add_argument("--no-llm", action="store_true", help="LLM 없이 임시 문장으로 (무료)")
    args = parser.parse_args()

    handoff_path = ROOT / "data" / "handoff" / f"{args.patient}.json"
    if not handoff_path.exists():
        sys.exit(f"없음: {handoff_path} — 먼저 python scripts/run_intake.py {args.patient}")
    bundle = json.loads(handoff_path.read_text(encoding="utf-8"))

    result = build_questions(bundle, top_k=args.top, use_llm=not args.no_llm)

    for q in result["questions"]:
        covered = ", ".join(f"{r['trial']}({len(r['criteria'])}개)" for r in q["resolves"])
        print(f"{q['priority']}. {q['text']}")
        print(f"   ↳ 해결 대상: {covered}")
    for n in result["not_asked"]:
        print(f"   (질문 안 함) {n.get('trial')} {n.get('criterion_id')} — {n.get('reason')}")

    out = ROOT / "questions" / f"{args.patient}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
