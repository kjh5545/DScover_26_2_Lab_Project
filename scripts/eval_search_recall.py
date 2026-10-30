"""검색 재현율 평가 — 골드셋의 정답 시험 15개가 검색에 잡히는가?

매칭 정확도(93.1%)는 "주어진 시험을 잘 판정하나"지만, 실전 첫 관문은 검색이다.
검색이 정답 시험을 못 집어오면 판정이 완벽해도 추천할 수 없다. 단계별로 잰다:

  ① 검색 풀: 검색어(LLM 결정)로 API를 돌려 모은 전체 후보에 들어오나
  ② 하드 필터 후: 나이·성별 필터가 정답을 떨어뜨리진 않나
  ③ (--relevance | --rank) 관련성 단계 후: 싼 모델이 정답을 떨어뜨리진 않나
  ④ 상위 N (기본 5): 실제로 스크리닝되는 범위에 드나

미스 원인도 분류한다: 모집 종료(검색 조건상 제외) / 검색어 불일치 / 필터 탈락 / 상위 N 밖.

실험 3 추가분:
  --rank   관련성 keep/drop 대신 Haiku 0~10점 랭킹으로 정렬 (비용 비슷)
  --curve  recall@k 곡선 (k=1,3,5,10,15,20,30,50) — 후보 수 N 결정 근거
  검색어 프롬프트가 1~3개→5~8개로 바뀌어 검색어 캐시는 v2로 새로 만든다.

실행: python scripts/eval_search_recall.py [--rank --curve] [--top 5] [--per-query 200]
비용: 환자당 검색어 결정 1회(캐시됨) + (--relevance/--rank 시) Haiku 호출. 나머지는 무료 API.
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
    """검색어 결정 (LLM 1회, 캐시). v2 = 5~8개 다양화 프롬프트 (v1 캐시와 분리)."""
    path = CACHE / f"queries_v2_{pid}.json"
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
    ap.add_argument("--relevance", action="store_true", help="관련성 필터(keep/drop, Haiku)까지 측정")
    ap.add_argument("--rank", action="store_true", help="관련도 랭킹(0~10점, Haiku)으로 정렬해 측정")
    ap.add_argument("--curve", action="store_true", help="recall@k 곡선 출력 (N 결정 근거)")
    ap.add_argument("--top", type=int, default=5, help="상위 N 기준 (기본 5)")
    ap.add_argument("--per-query", type=int, default=200, help="검색어당 가져올 시험 수 (기본 200)")
    ap.add_argument("--patient", help="한 명만 (예: S004) — 스모크 테스트용")
    args = ap.parse_args()
    llm_screen = args.rank or args.relevance

    gold = json.loads((ROOT / "goldset" / "goldset_v1.json").read_text(encoding="utf-8"))
    by_patient: dict[str, list[str]] = {}
    expected_final: dict[tuple, str] = {}
    for c in gold["cases"]:
        by_patient.setdefault(c["patient_id"], []).append(c["trial"])
        f = c.get("expected_final")
        expected_final[(c["patient_id"], c["trial"])] = f[0] if isinstance(f, list) else f
    if args.patient:
        by_patient = {args.patient: by_patient[args.patient]}

    stages = ["검색 풀", "하드 필터", "관련성 단계", f"상위 {args.top}"]
    hit = {s: 0 for s in stages}
    total = 0
    misses = []
    placements = []  # recall@k 곡선용: 정답마다 {"rank": 순위 or None, "auto_ok": 부적격 사전 제외}

    for pid, gold_ncts in sorted(by_patient.items()):
        profile = get_profile(pid)
        queries = get_queries(pid, profile)
        pool = collect_pool(queries, per_query=args.per_query)

        age = profile.get("age")
        if age is not None and profile.get("age_unit") == "months":
            age = age / 12
        filtered = hard_filter(list(pool.values()), age, profile.get("sex"))

        if args.rank and filtered:
            from src.agents.relevance_filter import rank_relevant
            kept, dropped = rank_relevant(profile, filtered)
        elif args.relevance and filtered:
            from src.agents.relevance_filter import filter_relevant
            kept, dropped = filter_relevant(profile, filtered)
        else:
            kept, dropped = filtered, []

        kept_ids = [t["nct_id"] for t in kept]
        score_of = {t["nct_id"]: t.get("_relevance") for t in kept}
        if args.rank:  # 분석용: 정답을 이기는 상위 시험들 저장
            (CACHE / f"ranked_{pid}.json").write_text(json.dumps(
                [{"rank": i + 1, "nct_id": t["nct_id"], "score": t.get("_relevance"),
                  "title": t.get("title", "")} for i, t in enumerate(kept[:30])],
                ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n{pid} — 검색어 {queries} → 풀 {len(pool)}건, 필터 후 {len(filtered)}건"
              + (f", 관련성 후 {len(kept)}건 (거름 {len(dropped)})" if llm_screen else ""))
        for nct in gold_ncts:
            total += 1
            in_pool = nct in pool
            in_filtered = any(t["nct_id"] == nct for t in filtered)
            in_kept = nct in kept_ids
            in_top = nct in kept_ids[:args.top]
            for s, ok in zip(stages, [in_pool, in_filtered, in_kept, in_top]):
                hit[s] += ok
            rank = kept_ids.index(nct) + 1 if in_kept else None
            score_s = f", 관련도 {score_of[nct]}점" if in_kept and score_of.get(nct) is not None else ""
            placements.append({"patient": pid, "nct": nct, "rank": rank,
                               "score": score_of.get(nct), "auto_ok": False})
            if in_top:
                print(f"  O {nct} (상위 {rank}위{score_s})")
                continue
            if not in_pool:
                status = trial_status(nct)
                reason = f"모집 상태 {status} (검색은 RECRUITING만)" if status != "RECRUITING" \
                    else "검색어로 안 잡힘"
            elif not in_filtered:
                if expected_final.get((pid, nct)) == "부적격":
                    reason = "하드 필터 제외 — 정답도 부적격 (올바른 동작, 미스 아님)"
                    for s in ("하드 필터", "관련성 단계", f"상위 {args.top}"):
                        hit[s] += 1  # 부적격 시험을 미리 거른 건 성공으로 집계
                    placements[-1]["auto_ok"] = True
                else:
                    reason = "나이·성별 하드 필터 탈락 ⚠"
            elif not in_kept:
                reason = "관련성 단계 탈락 ⚠"
            else:
                reason = f"상위 {args.top} 밖 ({rank}위{score_s})"
            misses.append({"patient": pid, "nct": nct, "reason": reason})
            print(f"  X {nct} — {reason}")

    print("\n" + "=" * 52)
    print(f"== 검색 재현율 (정답 시험 {total}개 기준) ==")
    for s in stages:
        if s == "관련성 단계" and not llm_screen:
            continue
        print(f"{s}: {hit[s]}/{total} ({hit[s] / total:.0%})")

    curve = {}
    if args.curve:
        print(f"\n== recall@k 곡선 (랭킹 {'ON' if args.rank else 'OFF — 검색 순서 기준'}) ==")
        for k in (1, 3, 5, 10, 15, 20, 30, 50):
            ok = sum(1 for p in placements
                     if p["auto_ok"] or (p["rank"] is not None and p["rank"] <= k))
            curve[f"recall@{k}"] = f"{ok}/{total}"
            print(f"  상위 {k:>2}개 안: {ok}/{total} ({ok / total:.0%})")

    print(f"\nLLM 비용: {spent['calls']}회, ${spent['usd']:.3f}")

    out = ROOT / "data" / "processed" / "eval_search_recall.json"
    out.write_text(json.dumps({"top": args.top, "relevance": args.relevance, "rank": args.rank,
                               "per_query": args.per_query,
                               "recall": {s: f"{hit[s]}/{total}" for s in stages},
                               "curve": curve, "placements": placements,
                               "misses": misses}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
