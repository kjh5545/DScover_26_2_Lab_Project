"""판정 출력 검사(src/agents/matcher.py의 validate_judgments)를 점검한다. API를 쓰지 않아 무료.

실행: python scripts/check_validate.py
1. 일부러 망가뜨린 AI 출력 (기준 누락, 이상한 판정값, 중복, 없는 ID, 객체로 감싼 응답)
2. 안전 오류 재현: 탈락 기준을 빠뜨리면 검사 전에는 "적격 가능"으로 잘못 나오고, 검사 후에는 "정보 부족"이 되는지
3. 저장된 실제 판정 결과(v1·v2·v3 캐시)에서 검사가 고친 것이 있는지
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.matcher import final_judgment, validate_judgments, validate_shape

GOLD = ROOT / "goldset" / "goldset_v1.json"
CACHES = {
    "v1": lambda c: ROOT / "data" / "processed" / "eval_cache" / f"match_{c['patient_id']}_{c['trial']}.json",
    "v2 (Opus 5)": lambda c: ROOT / "data" / "processed" / "goldset_cache" / f"match_{c['id']}.json",
    "v3 (Sonnet 5.5)": lambda c: ROOT / "data" / "processed" / "goldset_cache_v3_claude-sonnet-5-5" / f"match_{c['id']}.json",
}

failures = 0


def check(name: str, ok: bool) -> None:
    global failures
    print(f"  [{'OK' if ok else '실패'}] {name}")
    failures += not ok


def main() -> int:
    criteria = [{"id": i} for i in ["I1", "I2", "E1", "E2"]]

    print("1. 망가뜨린 출력")
    out, fixes = validate_judgments(criteria, [
        {"criterion_id": "I1", "verdict": "pass", "evidence": "a"},
        {"criterion_id": "i2 ", "verdict": "maybe", "evidence": "b"},   # 소문자·공백 + 이상한 값
        {"criterion_id": "I1", "verdict": "fail", "evidence": "dup"},   # 중복
        {"criterion_id": "E9", "verdict": "fail", "evidence": "x"},     # 없는 ID
    ])                                                                  # E1, E2 누락
    by = {j["criterion_id"]: j for j in out}
    check("기준 순서대로 4개 모두 있음", [j["criterion_id"] for j in out] == ["I1", "I2", "E1", "E2"])
    check("중복은 앞의 것(pass)만 남음", by["I1"]["verdict"] == "pass")
    check("이상한 판정값 → 모름", by["I2"]["verdict"] == "unknown" and by["I2"]["checked_by"] == "validator")
    check("누락된 E1, E2 → 모름", by["E1"]["verdict"] == by["E2"]["verdict"] == "unknown")
    check("고친 내역 5건 (값 1, 중복 1, 없는 ID 1, 누락 2)", len(fixes) == 5)
    check("객체로 감싼 응답도 목록으로 꺼냄",
          validate_shape({"judgments": [{"criterion_id": "I1", "verdict": "pass"}]})[0]["criterion_id"] == "I1")
    check("엉뚱한 응답(문자열)은 빈 목록 → 전부 모름",
          all(j["verdict"] == "unknown" for j in validate_judgments(criteria, "oops")[0]))

    print("\n2. 안전 오류 재현: 나머지는 통과·등록 후 확인인데 AI가 탈락 기준(E2)을 빠뜨린 경우")
    dropped = [{"criterion_id": "I1", "verdict": "pass"}, {"criterion_id": "I2", "verdict": "pass"},
               {"criterion_id": "E1", "verdict": "post_enrollment"}]          # E2(실제로는 탈락)가 빠짐
    before = final_judgment(dropped)
    after = final_judgment(validate_judgments(criteria, dropped)[0])
    print(f"  검사 전 최종 판단: {before}  →  검사 후: {after}")
    check("검사 전에는 '적격 가능'으로 잘못 나옴", before == "probably_eligible")
    check("검사 후에는 '정보 부족' → 질문으로 확인", after == "insufficient_info")

    gold = json.loads(GOLD.read_text(encoding="utf-8"))

    print("\n3. 저장된 실제 판정 결과")
    for label, path_of in CACHES.items():
        n_cases = n_fixes = 0
        for case in gold["cases"]:
            path = path_of(case)
            if not path.exists():
                continue
            n_cases += 1
            _, fixes = validate_judgments([{"id": r["id"]} for r in case["rows"]],
                                          json.loads(path.read_text(encoding="utf-8")))
            n_fixes += len(fixes)
            for f in fixes:
                print(f"    {case['id']} {f['criterion_id']}: {f['reason']}")
        print(f"  {label}: {n_cases}케이스, 고친 기준 {n_fixes}개")

    print(f"\n{'모두 통과' if failures == 0 else f'실패 {failures}개'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
