"""코드 판정(src/tools/rule_checks.py)을 평가 세트 정답과 대조한다. API를 쓰지 않아 무료.

실행: python scripts/check_rule_checks.py
- 코드가 판정한 기준마다 정답과 같은지 출력
- 계산 도구(수치 비교, 단위 변환, 날짜) 자체 점검
"""

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.tools.rule_checks import code_judgments, compare, convert, months_between, within_window

EN2KO = {"pass": "통과", "fail": "탈락", "unknown": "모름", "post_enrollment": "등록 후 확인"}
GOLD = ROOT / "goldset" / "goldset_v1.json"
PROFILES = ROOT / "data" / "processed" / "eval_cache"


def main() -> int:
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    total = agree = 0
    for case in gold["cases"]:
        profile = json.loads((PROFILES / f"profile_{case['patient_id']}.json").read_text(encoding="utf-8"))
        criteria = [{"id": r["id"], "type": r["kind"], "text": r["original"]} for r in case["rows"]]
        for cid, j in code_judgments(profile, criteria).items():
            expected = case["expected"][cid]
            got = EN2KO[j["verdict"]]
            ok = got == expected
            total += 1
            agree += ok
            text = next(r["original"] for r in case["rows"] if r["id"] == cid)
            print(f"{'OK ' if ok else 'XX '} {case['id']:<18} {cid:<4} 정답={expected:<6} 코드={got:<4} | {text[:60]}")
    print(f"\n코드 판정 {total}개 중 정답 일치 {agree}개")

    # 계산 도구 점검
    assert compare(1.1, "<", 1.5) and not compare(1.5, "<", 1.5) and compare(1.5, "이상", 1.5)
    assert abs(convert("creatinine", 1.1, "mg/dL", "µmol/L") - 97.24) < 0.01
    assert abs(months_between(date(2025, 4, 15), date(2026, 10, 12)) - 17.9) < 0.1
    assert within_window(date(2026, 10, 1), 14, ref=date(2026, 10, 12))
    assert not within_window(date(2026, 7, 1), 14, ref=date(2026, 10, 12))
    print("계산 도구 점검 통과 (수치 비교, 단위 변환, 날짜)")
    return 0 if agree == total else 1


if __name__ == "__main__":
    sys.exit(main())
