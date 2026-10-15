"""goldset_v1.json (회의 확정 정답셋) 기준 매칭 에이전트 평가.

- v1 프롬프트 결과: data/processed/eval_cache/match_*.json (규칙 반영 전 캐시 재활용, 무료)
- v2 프롬프트 결과: data/processed/goldset_cache/ 에 새로 생성 (규칙 반영 후, claude-opus-5로 생성됨)
- v3 프롬프트 결과: data/processed/goldset_cache_v3_<모델>/ (환자 원문 입력 + goldset v1.1 결정, 2026-10-12)
  모델별로 폴더가 달라 Opus 결과와 섞이지 않는다. --skip-v3 이면 API를 부르지 않고 캐시만 채점
- 골드셋 결정 3에 따라, 기준 목록에 없는 나이 조건은 하드 필터로 최종 판단에 반영

실행: python scripts/eval_vs_goldset.py            # v1·v2(캐시) + v3(없으면 새로 생성)
      python scripts/eval_vs_goldset.py --skip-v3  # 캐시만 채점 (무료)
      python scripts/eval_vs_goldset.py --compare-v2  # v2 프롬프트도 현재 모델로 돌려 비교 (추가 약 $1)
      python scripts/eval_vs_goldset.py --batch    # 새로 돌릴 판정을 배치 API로 한 번에 (비용 50% 할인, 몇 분~1시간 대기)
결과마다 "+ 코드 판정" 줄은 나이·임신 기준을 코드가 덮어쓴 점수 (파이프라인과 같은 방식)
비용: v3 첫 실행 시 매칭 15회 (Sonnet 5.5 기준 약 $1). 재실행은 캐시라 무료.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.matcher import (SYSTEM_PROMPT, SYSTEM_PROMPT_V2, build_user_message, final_judgment, match,
                                validate_judgments, validate_shape)
from src.llm import MODEL, batch_ask_json
from src.tools.rule_checks import apply_code_checks, code_judgments

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


def evaluate(label: str, get_judgments, use_code: bool = False) -> dict:
    """use_code=True면 LLM 판정 위에 코드 판정(나이·임신)과 출력 검사를 더해 채점한다 (파이프라인과 같은 방식)."""
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    agree = total = finals_agree = 0
    noq_ok = noq_total = 0
    n_evaluated = 0
    n_fixed = 0   # 출력 검사(validate_judgments)가 고친 기준 수
    disagreements = []

    for case in gold["cases"]:
        profile = get_profile(case["patient_id"])
        criteria = [{"id": r["id"], "type": r["kind"], "text": r["original"]} for r in case["rows"]]
        judgments = get_judgments(case, profile, criteria)
        if judgments is None:
            continue
        n_evaluated += 1
        if use_code:
            judgments, _ = apply_code_checks(validate_shape(judgments), code_judgments(profile, criteria))
            judgments, fixes = validate_judgments(criteria, judgments)
            n_fixed += len(fixes)
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
    if use_code and total:
        print(f"출력 검사로 고친 기준: {n_fixed}")
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
    if SKIP_V3 or BATCH:   # 배치에서 실패한 건을 정가로 다시 돌리지 않음
        return None
    print(f"  매칭 중 (v3, {MODEL}): {case['id']}")
    judgments = match(profile, criteria, case_text=case["patient"])
    path.write_text(json.dumps(judgments, ensure_ascii=False, indent=2), encoding="utf-8")
    return judgments


SKIP_V3 = "--skip-v3" in sys.argv
BATCH = "--batch" in sys.argv             # 배치 API (50% 할인). 실패한 건은 다음 실행 때 다시 시도
COMPARE_V2 = "--compare-v2" in sys.argv   # v2 프롬프트도 현재 모델로 돌려 모델 효과와 프롬프트 효과를 나눠 본다 (약 $1)
V2_NOW_CACHE = ROOT / "data" / "processed" / f"goldset_cache_v2_{MODEL}"


def v2_now_judgments(case, profile, criteria):
    """v2 프롬프트를 현재 모델(MODEL)로. 원문 입력 없이 v2 방식 그대로."""
    V2_NOW_CACHE.mkdir(parents=True, exist_ok=True)
    path = V2_NOW_CACHE / f"match_{case['id']}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if SKIP_V3 or BATCH or not COMPARE_V2:
        return None
    print(f"  매칭 중 (v2, {MODEL}): {case['id']}")
    judgments = match(profile, criteria, system_prompt=SYSTEM_PROMPT_V2)
    path.write_text(json.dumps(judgments, ensure_ascii=False, indent=2), encoding="utf-8")
    return judgments


def run_batch() -> None:
    """캐시에 없는 v3(와 --compare-v2면 v2) 판정을 배치 API로 한 번에 만들어 캐시에 저장한다."""
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    jobs = [("v3", V3_CACHE, SYSTEM_PROMPT, True)]
    if COMPARE_V2:
        jobs.append(("v2", V2_NOW_CACHE, SYSTEM_PROMPT_V2, False))
    requests, paths = {}, {}
    for tag, cache, system, with_text in jobs:
        cache.mkdir(parents=True, exist_ok=True)
        for case in gold["cases"]:
            path = cache / f"match_{case['id']}.json"
            if path.exists():
                continue
            criteria = [{"id": r["id"], "type": r["kind"], "text": r["original"]} for r in case["rows"]]
            cid = f"{tag}-{re.sub(r'[^A-Za-z0-9_-]', '_', case['id'])}"
            user = build_user_message(get_profile(case["patient_id"]), criteria,
                                      case["patient"] if with_text else None)
            requests[cid], paths[cid] = (system, user), path
    if not requests:
        print("배치: 새로 돌릴 판정 없음 (모두 캐시에 있음)")
        return
    results, cost = batch_ask_json(requests)
    for cid, judgments in results.items():
        if judgments is not None:
            paths[cid].write_text(json.dumps(judgments, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"배치 완료: {sum(v is not None for v in results.values())}/{len(requests)}건 저장, 실제 비용 약 ${cost:.2f}")


def main() -> None:
    if BATCH and not SKIP_V3:
        run_batch()
    r1 = evaluate("v1 프롬프트 (회의 전 규칙)", v1_judgments)
    r2 = evaluate("v2 프롬프트 (회의 결정 반영, claude-opus-5)", v2_judgments)
    r2c = evaluate("v2 + 코드 판정 (claude-opus-5)", v2_judgments, use_code=True)
    r2n = evaluate(f"v2 프롬프트 ({MODEL}, --compare-v2)", v2_now_judgments)
    r3 = evaluate(f"v3 프롬프트 (원문 입력 + goldset v1.1, {MODEL})", v3_judgments)
    r3c = evaluate(f"v3 + 코드 판정 ({MODEL}) ← 파이프라인과 같은 방식", v3_judgments, use_code=True)
    last = r3c if not r3c["criteria"].startswith("0/") else r2c

    print(f"\n== {last['label']}에서 남은 불일치 ==")
    for d in last["disagreements"]:
        print(f"[{d['case']} {d['criterion_id']}] 정답={d['gold']} vs AI={d['agent']}")
        print(f"   AI 근거: {d['evidence']}")

    out = ROOT / "data" / "processed" / "eval_vs_goldset.json"
    out.write_text(json.dumps({"v1": r1, "v2": r2, "v2_code": r2c, "v2_now": r2n, "v3": r3, "v3_code": r3c},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
