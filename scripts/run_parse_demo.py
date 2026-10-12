"""기준 파싱 에이전트 데모.

S005(조짐 편두통, 킥오프 문서의 첫 연습 케이스) 환자용으로 수집한
임상시험 1건의 eligibility criteria를 개별 조건으로 분해해서 출력한다.

실행: python scripts/run_parse_demo.py
필요: ANTHROPIC_API_KEY 환경변수 또는 .env 파일
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.criteria_parser import parse_criteria


def main() -> None:
    trials_path = ROOT / "data" / "raw" / "trials" / "S005.json"
    data = json.loads(trials_path.read_text(encoding="utf-8"))
    trial = data["trials"][0]

    print(f"시험: {trial['nct_id']} — {trial['title']}\n")
    print("=== 기준 원문 (앞부분) ===")
    print(trial["eligibility_criteria"][:500], "...\n")

    print("=== 파싱 결과 ===")
    criteria = parse_criteria(trial["eligibility_criteria"])
    for c in criteria:
        print(f"[{c['id']}] ({c['type']}/{c.get('category', '?')}) {c['text']}")
        for sub in c.get("sub_conditions", []):
            print(f"      └ 하위 조건: {sub}")
        print(f"      필요한 환자 정보: {', '.join(c.get('needed_info', []))}")

    out_path = ROOT / "data" / "processed" / f"criteria_{trial['nct_id']}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(criteria, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
