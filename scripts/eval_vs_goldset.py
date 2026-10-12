"""goldset_v1.json (회의 확정 정답셋) 기준 매칭 에이전트 평가.

- v1 프롬프트 결과: data/processed/eval_cache/match_*.json (규칙 반영 전 캐시 재활용, 무료)
- v2 프롬프트 결과: data/processed/goldset_cache/ 에 새로 생성 (규칙 반영 후, claude-opus-5로 생성됨)
- v3 프롬프트 결과: data/processed/goldset_cache_v3_<모델>/ (환자 원문 입력 + goldset v1.1 결정, 2026-10-12)
  모델별로 폴더가 달라 Opus 결과와 섞이지 않는다. --skip-v3 이면 API를 부르지 않고 캐시만 채점
- 골드셋 결정 3에 따라, 기준 목록에 없는 나이 조건은 하드 필터로 최종 판단에 반영

실행: python scripts/eval_vs_goldset.py            # v1·v2(캐시) + v3(없으면 새로 생성)
      python scripts/eval_vs_goldset.py --skip-v3  # 캐시만 채점 (무료)
비용: v3 첫 실행 시 매칭 15회 (Sonnet 5.5 기준 약 $1). 재실행은 캐시라 무료.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.matcher import final_judgment, match
from src.llm import MODEL

_CANDIDATES = [ROOT / "goldset_v1.json", ROOT / "goldset" / "goldset_v1.json"]
GOLD = next(p for p in _CANDIDATES if p.exists())
V1_CACHE = ROOT / "data" / "processed" / "eval_cache"      # 규칙 반영 전 판정 (베이스라인)
V2_CACHE = ROOT / "data" / "processed" / "goldset_cache"   # 규칙 반영 후 판정 (claude-opus-5)
V3_CACHE = ROOT / "data" / "processed" / f"goldset_cache_v3_{MODEL}"  # v3 프롬프트 + 환자 원문

EN2KO = {"pass": "통과", "fail": "탈락", "unknown": "모름", "post_enrollment": "등록 후 확인"}
FINAL_EN2KO = {"eligible": "적격", "probably_eligible": "적격 가능 (등록 후 확인 필요)",
               "insufficient_info": "정보 부족", "ineligible": "부적격"}


def age_out_of_range(case: dict, profile: dict) -> bool:
    """기준 헤더의 'Age X Years - Y Years'와 환자 나이를 대조 (결정 3: 하드 필터 역할)."""
    m = re.search(r"Age ([\d.]+) (Year|Month)s? - ([\d.]+) (Year|Month)s?", case["criteria"])
    if not m:
        return False
    to_years = lambda v, u: float(v) / (12 if u == "Month" else 1)
    lo, hi = to_years(m.group(1), m.group(2)), to_years(m.group(3), m.group(4))
    age = profile.get("age")
    if age is None:
        return False
    if profile.get("age_unit") == "months":
        age = age / 12
    return not (lo <= age <= hi)


def get_profile(patient_id: str) -> dict:
    return json.loads((V1_CACHE / f"profile_{patient_id}.json").read_text(encoding="utf-8"))


def evaluate(label: str, get_judgments) -> dict:
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    agree = total = finals_agree = 0
    noq_ok = noq_total = 0
    n_evaluated = 0
    disagreements = []

    for case in gold["cases"]:
        profile = get_profile(case["patient_id"])
        criteria = [{"id": r["id"], "type": r["kind"], "text": r["original"]} for r in case["rows"]]
        judgments = get_judgments(case, profile, criteria)
        if judgments is None:
            continue
        n_evaluated += 1
        by_id = {j["criterion_id"]: j for j in judgments}

        for cid, expected_ko in case["expected"].items():
            j = by_id.get(cid)
            total += 1
            got_ko = EN2KO[j["verdict"]] if j else "(누락)"   # AI가 기준을 빠뜨리면 틀림으로 센다
            if got_ko == expected_ko:
                agree += 1
            else:
                disagreements.append({"case": case["id"], "criterion_id": cid,
                                      "gold": expected_ko, "agent": got_ko,
                                      "evidence": (j["evidence"][:90] if j else "AI 출력에 이 기준이 없음")})

        agent_final = final_judgment(judgments)
        if agent_final != "ineligible" and age_out_of_range(case, profile):
            agent_final = "ineligible"  # 결정 3: 나이 하드 필터
        expected_final = case["expected_final"]
        expected_final = expected_final[0] if isinstance(expected_final, list) else expected_final
        if FINAL_EN2KO[agent_final] == expected_final:
            finals_agree += 1

        if case.get("expect_no_questions"):
            noq_total += 1
            if agent_final == "ineligible":  # 코드 규칙상 부적격이면 질문 생성 안 함
                noq_ok += 1

    n_cases = n_evaluated  # 실제로 채점한 케이스 수 (결과가 없는 케이스는 제외)
    print(f"\n== {label} ==")
    if total == 0:
        print("결과 없음 (캐시가 없고 --skip-v3 이거나 아직 실행 전)")
    else:
        print(f"기준 일치: {agree}/{total} ({agree / total:.1%})")
    print(f"최종 판단 일치: {finals_agree}/{n_cases}")
    print(f"탈락 확정 시 질문 억제: {noq_ok}/{noq_total}")
    return {"label": label, "criteria": f"{agree}/{total}", "finals": f"{finals_agree}/{n_cases}",
            "no_questions": f"{noq_ok}/{noq_total}", "disagreements": disagreements}


def v1_judgments(case, profile, criteria):
    """규칙 반영 전 캐시 (eval_vs_manual.py가 만든 것) — 없으면 건너뜀."""
    path = V1_CACHE / f"match_{case['patient_id']}_{case['trial']}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def v2_judgments(case, profile, criteria):
    """규칙 반영 후 새 판정 (케이스별 캐시)."""
    V2_CACHE.mkdir(parents=True, exist_ok=True)
    path = V2_CACHE / f"match_{case['id']}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    print(f"  매칭 중: {case['id']}")
    judgments = match(profile, criteria)
    path.write_text(json.dumps(judgments, ensure_ascii=False, indent=2), encoding="utf-8")
    return judgments


def v3_judgments(case, profile, criteria):
    """v3 프롬프트 + 환자 원문 입력 (모델별 캐시). 프로필은 v1 캐시를 그대로 써서 판정 차이만 본다."""
    V3_CACHE.mkdir(parents=True, exist_ok=True)
    path = V3_CACHE / f"match_{case['id']}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if SKIP_V3:
        return None
    print(f"  매칭 중 (v3, {MODEL}): {case['id']}")
    judgments = match(profile, criteria, case_text=case["patient"])
    path.write_text(json.dumps(judgments, ensure_ascii=False, indent=2), encoding="utf-8")
    return judgments


SKIP_V3 = "--skip-v3" in sys.argv


def main() -> None:
    r1 = evaluate("v1 프롬프트 (회의 전 규칙)", v1_judgments)
    r2 = evaluate("v2 프롬프트 (회의 결정 반영, claude-opus-5)", v2_judgments)
    r3 = evaluate(f"v3 프롬프트 (원문 입력 + goldset v1.1, {MODEL})", v3_judgments)
    last = r3 if not r3["criteria"].startswith("0/") else r2

    print(f"\n== {last['label']}에서 남은 불일치 ==")
    for d in last["disagreements"]:
        print(f"[{d['case']} {d['criterion_id']}] 정답={d['gold']} vs AI={d['agent']}")
        print(f"   AI 근거: {d['evidence']}")

    out = ROOT / "data" / "processed" / "eval_vs_goldset.json"
    out.write_text(json.dumps({"v1": r1, "v2": r2, "v3": r3}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
