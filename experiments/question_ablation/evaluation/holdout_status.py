"""확인 실험 후보 환자의 상세 시트 준비 상태 점검 (API 호출 없음, 무료).

평가자가 결과를 보아도 되도록 **개수와 여부만** 출력한다. 환자 설명, 판정값, 근거, 질문 문장, 시험별 최종 판단 값은
출력하지 않는다. 판정값 분포(통과·탈락 개수 등)도 출력하지 않는다.

  python experiments/question_ablation/evaluation/holdout_status.py [--ref origin/main|HEAD|WORKTREE]
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

from src.testing.detailed_sheet import parse_sheet  # noqa: E402

HOLDOUT = ("S002", "S010", "N001", "N002")
SHEET_DIR = "screening/detailed/주희"
REVIEW_WORDS = ("교차 검수", "검수자", "승인", "버전 고정", "잠금")


def sheet_text(pid: str, ref: str) -> str:
    rel = f"{SHEET_DIR}/{pid}_detailed_sheet.md"
    if ref == "WORKTREE":
        return (ROOT / rel).read_text(encoding="utf-8")
    out = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=ROOT, capture_output=True)
    if out.returncode:
        raise FileNotFoundError(f"{ref}:{rel}")
    return out.stdout.decode("utf-8")


def blob(pid: str, ref: str) -> str:
    rel = f"{SHEET_DIR}/{pid}_detailed_sheet.md"
    args = ["git", "hash-object", rel] if ref == "WORKTREE" else ["git", "rev-parse", f"{ref}:{rel}"]
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True).stdout.strip()


def status(pid: str, ref: str) -> dict:
    text = sheet_text(pid, ref)
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / f"{pid}_detailed_sheet.md"
        f.write_text(text, encoding="utf-8")
        s = parse_sheet(f)
    rows = [r for t in s["trials"] for r in t["rows"]]
    probs = s["problems"]
    kind = lambda p: ("id" if ("기준 ID" in p or "없는 시험" in p) else "verdict" if ": 판정 " in p  # noqa: E731
                      else "final" if "최종 판단" in p else "detailed" if "상세" in p else "other")
    # 표 밖 문장에서만 검수 기록을 찾는다 (표 안 근거 문장은 검수 기록이 아님)
    prose = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("|"))
    return {
        "patient": pid, "ref": ref, "blob": blob(pid, ref)[:12],
        "short_text": bool(s["short_text"]), "detailed_text": bool(s["detailed_text"]),
        "trials": len(s["trials"]), "criteria": len(rows),
        "verdict_filled": sum(r["verdict"] is not None for r in rows),
        "verdict_missing_or_invalid": sum(r["verdict"] is None for r in rows),
        "evidence_empty": sum(not r["evidence"].strip() for r in rows),
        "unknown_without_question": sum(r["verdict"] == "unknown" and not r["question"].strip() for r in rows),
        "trial_final_filled": sum(t["final"] is not None for t in s["trials"]),
        "parse_problems": {k: sum(kind(p) == k for p in probs) for k in ("id", "verdict", "final", "detailed", "other")},
        "review_record_in_sheet": [w for w in REVIEW_WORDS if w in prose],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", default="origin/main", help="git ref 또는 WORKTREE (작업 폴더)")
    args = ap.parse_args()
    for pid in HOLDOUT:
        try:
            print(json.dumps(status(pid, args.ref), ensure_ascii=False))
        except FileNotFoundError as e:
            print(json.dumps({"patient": pid, "ref": args.ref, "error": f"파일 없음 {e}"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
