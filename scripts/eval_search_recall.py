"""검색 재현율 평가 — 골드셋의 정답 시험 15개가 검색에 잡히는가?

매칭 정확도(93.1%)는 "주어진 시험을 잘 판정하나"지만, 실전 첫 관문은 검색이다.
검색이 정답 시험을 못 집어오면 판정이 완벽해도 추천할 수 없다. 단계별로 잰다:

  ① 검색 풀: 검색어(LLM 결정)로 API를 돌려 모은 전체 후보에 들어오나
  ② 하드 필터 후: 나이·성별 필터가 정답을 떨어뜨리진 않나
  ③ (--relevance) 관련성 필터 후: 싼 모델 필터가 정답을 떨어뜨리진 않나
  ④ 상위 N (기본 5): 실제로 스크리닝되는 범위에 드나

미스 원인도 분류한다: 모집 종료(검색 조건상 제외) / 검색어 불일치 / 필터 탈락 / 상위 N 밖.

실행: python scripts/eval_search_recall.py [--relevance] [--top 5] [--per-query 50]
비용: 환자당 검색어 결정 1회(캐시됨) + (--relevance 시) Haiku 1회. 나머지는 무료 API.
"""

import argparse
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.trial_searcher import collect_pool, hard_filter, plan_queries
from src.llm import spent

CACHE = ROOT / "data" / "processed" / "eval_cache"


def get_profile(pid: str) -> dict:
    return json.loads((CACHE / f"profile_{pid}.json").read_text(encoding="utf-8"))


def get_queries(pid: str, profile: dict) -> list[str]:
    """검색어 결정 (LLM 1회, 캐시)."""
    path = CACHE / f"queries_{pid}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["queries"]
    plan = plan_queries(profile)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan["queries"]


def trial_status(nct_id: str) -> str:
    """미스 원인 분류용: 시험의 현재 모집 상태 (무료 API)."""
    try:
        r = requests.get(f"https://clinicaltrials.gov/api/v2/studies/{nct_id}",
                         params={"fields": "OverallStatus"}, timeout=20)
        return r.json()["protocolSection"]["statusModule"]["overallStatus"]
    except Exception:
        return "UNKNOWN"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--relevance", action="store_true", help="관련성 필터(Haiku)까지 측정")
    ap.add_argument("--top", type=int, default=5, help="상위 N 기준 (기본 5)")
    ap.add_argument("--per-query", type=int, default=50, help="검색어당 가져올 시험 수 (기본 50)")
    ap.add_argument("--patient", help="한 명만 (예: S004) — 스모크 테스트용")
    args = ap.parse_args()

    gold = json.loads((ROOT / "goldset" / "goldset_v1.json").read_text(encoding="utf-8"))
    by_patient: dict[str, list[str]] = {}
    expected_final: dict[tuple, str] = {}
    for c in gold["cases"]:
        by_patient.setdefault(c["patient_id"], []).append(c["trial"])
        f = c.get("expected_final")
        expected_final[(c["patient_id"], c["trial"])] = f[0] if isinstance(f, list) else f
    if args.patient:
        by_patient = {args.patient: by_patient[args.patient]}

    stages = ["검색 풀", "하드 필터", "관련성 필터", f"상위 {args.top}"]
    hit = {s: 0 for s in stages}
    total = 0
    misses = []

    for pid, gold_ncts in sorted(by_patient.items()):
        profile = get_profile(pid)
        queries = get_queries(pid, profile)
        pool = collect_pool(queries, per_query=args.per_query)

        age = profile.get("age")
        if age is not None and profile.get("age_unit") == "months":
            age = age / 12
        filtered = hard_filter(list(pool.values()), age, profile.get("sex"))

        if args.relevance and filtered:
            from src.agents.relevance_filter import filter_relevant
            kept, dropped = filter_relevant(profile, filtered)
        else:
            kept, dropped = filtered, []

        kept_ids = [t["nct_id"] for t in kept]
        print(f"\n{pid} — 검색어 {queries} → 풀 {len(pool)}건, 필터 후 {len(filtered)}건"
              + (f", 관련성 후 {len(kept)}건 (거름 {len(dropped)})" if args.relevance else ""))
        for nct in gold_ncts:
            total += 1
            in_pool = nct in pool
            in_filtered = any(t["nct_id"] == nct for t in filtered)
            in_kept = nct in kept_ids
            in_top = nct in kept_ids[:args.top]
            for s, ok in zip(stages, [in_pool, in_filtered, in_kept, in_top]):
                hit[s] += ok
            if in_top:
                print(f"  O {nct} (상위 {kept_ids.index(nct) + 1}위)")
                continue
            if not in_pool:
                status = trial_status(nct)
                reason = f"모집 상태 {status} (검색은 RECRUITING만)" if status != "RECRUITING" \
                    else "검색어로 안 잡힘"
            elif not in_filtered:
                if expected_final.get((pid, nct)) == "부적격":
                    reason = "하드 필터 제외 — 정답도 부적격 (올바른 동작, 미스 아님)"
                    for s in ("하드 필터", "관련성 필터", f"상위 {args.top}"):
                        hit[s] += 1  # 부적격 시험을 미리 거른 건 성공으로 집계
                else:
                    reason = "나이·성별 하드 필터 탈락 ⚠"
            elif not in_kept:
                reason = "관련성 필터 탈락 ⚠"
            else:
                reason = f"상위 {args.top} 밖 ({kept_ids.index(nct) + 1}위)"
            misses.append({"patient": pid, "nct": nct, "reason": reason})
            print(f"  X {nct} — {reason}")

    print("\n" + "=" * 52)
    print(f"== 검색 재현율 (정답 시험 {total}개 기준) ==")
    for s in stages:
        if s == "관련성 필터" and not args.relevance:
            continue
        print(f"{s}: {hit[s]}/{total} ({hit[s] / total:.0%})")
    print(f"\nLLM 비용: {spent['calls']}회, ${spent['usd']:.3f}")

    out = ROOT / "data" / "processed" / "eval_search_recall.json"
    out.write_text(json.dumps({"top": args.top, "relevance": args.relevance,
                               "recall": {s: f"{hit[s]}/{total}" for s in stages},
                               "misses": misses}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
