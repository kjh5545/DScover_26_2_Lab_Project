"""판정 프롬프트 비교 실험 (10/26 중간발표 피드백: "어떤 프롬프트로 성능이 어떻게 변했는지 검증").

모델(src/llm.py MODEL)과 입력(환자 원문 + 프로필 + 기준)은 고정하고 판정 안내(시스템 프롬프트)만 바꿔서,
평가 세트(규칙을 고칠 때 본 데이터)와 상세 환자(규칙을 고칠 때 안 본 데이터)를 **따로** 채점한다.

조건 (experiments/judge_ablation/prompts/*.txt, v3·v3_r1112는 코드에서 만듦):
  p0        규칙 없음: 판정 4단계 정의와 출력 형식만
  p1        + 사전 실험(수동 스크리닝 ①)에서 나온 규칙
  p2        + 평가 세트 팀 결정(수동 스크리닝 ②): 등록 후 확인 범위, 기록에 없는 수치 = 모름
  v3        현재 판정 프롬프트 (+ 오류 분석 규칙) = src/agents/matcher.py SYSTEM_PROMPT
  v3_r1112  v3 + 규칙 11·12 (10/18 보류, experiments/judge_ablation/prompts/_rules_11_12.txt)
  prompts/에 .txt를 더 넣으면 (예: control.txt, 대조군) 이름 그대로 조건이 된다. "_"로 시작하는 파일은 제외

실행:
  python scripts/ablation_judge.py --dry-run                  # 무료: 할 일과 예상 비용만
  python scripts/ablation_judge.py                            # 기본 조건 전부 × 3회, 배치 API (50% 할인, 몇 분~1시간)
  python scripts/ablation_judge.py --conditions p0 v3 --repeats 1 --datasets goldset
  python scripts/ablation_judge.py --report                   # 무료: 저장된 결과만 다시 채점
  옵션: --no-batch (바로 호출, 정가) · --sheets <시트 경로...> (상세 환자 시트 직접 지정)

상세 환자는 모든 기준에 판정이 채워진 시트만 쓴다 (판정 중인 시트는 자동으로 빠짐).
같은 조건·프롬프트·회차는 저장된 결과를 재사용하므로, 중간에 끊겨도 다시 실행하면 남은 것만 돈다.
결과: data/processed/judge_ablation/
  cache/<조건>_<프롬프트 해시>/<데이터>__<케이스>__r<회차>.json
  summary.md    조건 × 데이터별 점수표 (AI만 / + 코드 판정)
  criteria.csv  기준별 전체 판정 (오류 분석용, 엑셀로 열기)
  changes.csv   이웃한 두 조건 사이에 다수결 판정이 바뀐 기준 (무엇이 고쳐지고 무엇이 망가졌나)
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from eval_detailed import base_bundle, gold_of  # noqa: E402
from eval_vs_goldset import EN2KO, FINAL_EN2KO, GOLD, age_out_of_range, get_profile  # noqa: E402
from src.agents.matcher import (SYSTEM_PROMPT, build_user_message, final_judgment,  # noqa: E402
                                validate_judgments, validate_shape)
from src.llm import BATCH_PRICE, MODEL, PRICE, ask_json, batch_ask_json, spent  # noqa: E402
from src.testing.detailed_sheet import parse_sheet  # noqa: E402
from src.tools.rule_checks import apply_code_checks, code_judgments  # noqa: E402

PROMPTS = ROOT / "experiments" / "judge_ablation" / "prompts"
OUT = ROOT / "data" / "processed" / "judge_ablation"
ORDER = ["p0", "p1", "p2", "v3", "v3_r1112"]   # 이 순서로 이웃한 조건끼리 비교 (changes.csv)
KO2EN = {v: k for k, v in EN2KO.items()}
FINAL_KO2EN = {v: k for k, v in FINAL_EN2KO.items()}
VERDICTS = ["pass", "fail", "unknown", "post_enrollment"]
# 예상 비용용 출력 토큰 수 (판정 1회, thinking 포함). 10/12 평가 세트 v3 배치 15회 $0.13에 맞춘 값
EST_OUT_TOKENS = 1300


def load_conditions() -> dict[str, str]:
    conds = {p.stem: p.read_text(encoding="utf-8").strip() for p in sorted(PROMPTS.glob("*.txt"))
             if not p.stem.startswith("_")}
    conds["v3"] = SYSTEM_PROMPT
    rules = (PROMPTS / "_rules_11_12.txt").read_text(encoding="utf-8").rstrip()
    head, sep, tail = SYSTEM_PROMPT.partition("\n\nRespond with ONLY")
    conds["v3_r1112"] = head + "\n" + rules + sep + tail
    return conds


def goldset_items() -> list[dict]:
    """평가 세트: 짧은 원래 설명 + v3 평가 때와 같은 프로필(eval_cache) + 평가 세트 기준."""
    items = []
    for case in json.loads(GOLD.read_text(encoding="utf-8"))["cases"]:
        final = case["expected_final"]
        final = final[0] if isinstance(final, list) else final
        items.append({"dataset": "goldset", "case": case["id"], "trial": case["trial"],
                      "case_text": case["patient"], "profile": get_profile(case["patient_id"]),
                      "criteria": [{"id": r["id"], "type": r["kind"], "text": r["original"]} for r in case["rows"]],
                      "gold": {cid: KO2EN[v] for cid, v in case["expected"].items()},
                      "gold_final": FINAL_KO2EN[final], "age_case": case})
    return items


def complete(sheet: dict) -> str | None:
    """시트를 실험에 써도 되면 None, 아니면 빠지는 이유."""
    if not sheet["detailed_text"]:
        return "상세 설명 없음"
    empty = sum(1 for t in sheet["trials"] for r in t["rows"] if not r["verdict"])
    return f"판정 빈 칸 {empty}개" if empty else None


def detailed_items(paths: list[Path], dry: bool) -> tuple[list[dict], int]:
    """상세 환자: 상세 설명 + 그 설명의 프로필(eval_detailed와 같은 저장 위치) + 짧은 설명 단계의 기준.
    반환: (항목, 프로필을 새로 만들어야 하는 환자 수)."""
    from src.pipeline import understand_patient

    items, new_profiles = [], 0
    for path in paths:
        sheet = parse_sheet(path)
        why = complete(sheet)
        if why:
            print(f"  상세 환자 제외: {path.relative_to(ROOT)} ({why})")
            continue
        pid = sheet["patient_id"]
        key = f"{pid}_detailed_{hashlib.sha1(sheet['detailed_text'].encode('utf-8')).hexdigest()[:8]}"
        cache = ROOT / "data" / "processed" / "eval_cache" / f"profile_{key}.json"
        if dry and not cache.exists():
            new_profiles += 1
            profile = {}
        else:
            profile = understand_patient(sheet["detailed_text"], patient_id=key)
        criteria = {t["nct_id"]: t["criteria"] for t in base_bundle(pid)["trials"]}
        gold = gold_of(sheet)
        for t in sheet["trials"]:
            g_trial = {cid: g["verdict"] for (nct, cid), g in gold.items() if nct == t["nct_id"]}
            # 최종 판단 칸이 비어 있으면 기준별 정답으로 계산 (팀 규칙과 같은 코드 규칙)
            g_final = t["final"] or final_judgment([{"verdict": v} for v in g_trial.values()])
            items.append({"dataset": "detailed", "case": f"{pid}_{t['nct_id']}", "trial": t["nct_id"],
                          "case_text": sheet["detailed_text"], "profile": profile,
                          "criteria": criteria[t["nct_id"]], "gold": g_trial,
                          "gold_final": g_final, "age_case": None})
    return items, new_profiles


def cache_path(cond: str, system: str, item: dict, rep: int) -> Path:
    tag = hashlib.sha1(system.encode("utf-8")).hexdigest()[:8]
    return OUT / "cache" / f"{cond}_{tag}" / f"{item['dataset']}__{item['case']}__r{rep}.json"


def run(conds: dict[str, str], items: list[dict], repeats: int, use_batch: bool) -> None:
    todo = [(c, it, r) for c in conds for it in items for r in range(1, repeats + 1)
            if not cache_path(c, conds[c], it, r).exists()]
    if not todo:
        print("새로 돌릴 판정 없음 (모두 저장돼 있음)")
        return
    print(f"새로 돌릴 판정 {len(todo)}건 ({'배치' if use_batch else '바로 호출'})")
    if use_batch:
        requests, paths = {}, {}
        for c, it, r in todo:
            cid = re.sub(r"[^A-Za-z0-9_-]", "_", f"{c}-{it['dataset'][0]}-{it['case']}-r{r}")[:64]
            requests[cid] = (conds[c], build_user_message(it["profile"], it["criteria"], it["case_text"]))
            paths[cid] = cache_path(c, conds[c], it, r)
        results, cost = batch_ask_json(requests)
        for cid, judgments in results.items():
            if judgments is not None:
                paths[cid].parent.mkdir(parents=True, exist_ok=True)
                paths[cid].write_text(json.dumps(judgments, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"배치 완료: {sum(v is not None for v in results.values())}/{len(requests)}건 저장, 실제 비용 약 ${cost:.2f}")
        return
    for i, (c, it, r) in enumerate(todo, 1):
        print(f"  [{i}/{len(todo)}] {c} {it['case']} #{r}")
        try:
            judgments = ask_json(conds[c], build_user_message(it["profile"], it["criteria"], it["case_text"]))
        except json.JSONDecodeError:
            print("    JSON 파싱 실패 → 건너뜀 (다시 실행하면 재시도)")
            continue
        path = cache_path(c, conds[c], it, r)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(judgments, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"AI 호출 {spent['calls']}번, 비용 약 ${spent['usd']:.2f}")


def estimate(conds: dict[str, str], items: list[dict], repeats: int, use_batch: bool, new_profiles: int) -> None:
    pin, pout = (BATCH_PRICE if use_batch else PRICE).get(MODEL, (0.0, 0.0))
    n = usd = 0
    for c, system in conds.items():
        for it in items:
            left = sum(not cache_path(c, system, it, r).exists() for r in range(1, repeats + 1))
            if not left:
                continue
            chars = len(system) + len(build_user_message(it["profile"], it["criteria"], it["case_text"]))
            n += left
            usd += left * (chars / 3.2 * pin + EST_OUT_TOKENS * pout) / 1e6
    by_ds = Counter(it["dataset"] for it in items)
    print(f"\n조건 {len(conds)}개 × 케이스 {len(items)}개 (평가 세트 {by_ds['goldset']}, 상세 환자 {by_ds['detailed']})"
          f" × {repeats}회 → 새로 돌릴 판정 {n}건")
    if new_profiles:
        print(f"  + 상세 환자 프로필 새로 만들기 {new_profiles}건 (약 $0.01씩, 정가)")
    print(f"예상 비용: 약 ${usd:.2f} ({'배치 50% 할인' if use_batch else '정가'}, {MODEL})"
          f" · 실제는 0.7~1.5배 정도 차이 날 수 있음")


def judged(conds, items, repeats):
    """{(조건, 케이스, 회차): {"raw": 판정 목록, "code": 코드 판정·출력 검사 후}}  (저장된 것만)"""
    out = {}
    for c, system in conds.items():
        for it in items:
            for r in range(1, repeats + 1):
                p = cache_path(c, system, it, r)
                if not p.exists():
                    continue
                raw = validate_shape(json.loads(p.read_text(encoding="utf-8")))
                code, _ = apply_code_checks(raw, code_judgments(it["profile"], it["criteria"]))
                code, _ = validate_judgments(it["criteria"], code)
                out[(c, it["case"], r)] = {"raw": raw, "code": code}
    return out


def final_of(it: dict, judgments: list[dict]) -> str:
    f = final_judgment(judgments)
    if it["age_case"] and f != "ineligible" and age_out_of_range(it["age_case"], it["profile"]):
        f = "ineligible"   # 평가 세트 결정 3: 기준 목록에 없는 나이 조건은 하드 필터
    return f


def score(it: dict, judgments: list[dict]) -> dict:
    by_id = {j.get("criterion_id"): j.get("verdict") for j in judgments}
    s = Counter()
    for cid, g in it["gold"].items():
        ai = by_id.get(cid)
        s["total"] += 1
        s["same"] += ai == g
        s["missing"] += ai is None
        s[f"{g}_total"] += 1
        s[f"{g}_ok"] += ai == g
    s["final_ok"] = final_of(it, judgments) == it["gold_final"]
    return s


def fmt(vals: list[float], total: int) -> str:
    """회차별 맞힌 수 → '평균/전체 (최소~최대)'."""
    if not vals:
        return "-"
    mean = sum(vals) / len(vals)
    rng = f" ({min(vals):g}~{max(vals):g})" if len(vals) > 1 and min(vals) != max(vals) else ""
    return f"{mean:.1f}/{total}{rng}" if mean != int(mean) else f"{mean:.0f}/{total}{rng}"


def report(conds, items, repeats) -> None:
    res = judged(conds, items, repeats)
    datasets = [d for d in ("goldset", "detailed") if any(it["dataset"] == d for it in items)]
    lines = ["# 판정 프롬프트 비교 결과", "",
             f"- 모델: {MODEL} · 회차: {repeats} · 조건: {', '.join(conds)}",
             "- 숫자는 회차 평균 (괄호는 회차별 최소~최대). '통과·탈락'은 정답이 통과나 탈락인 기준만 센 것",
             "- **AI만** = 프롬프트 효과만 본 점수 · **+코드** = 나이·임신 코드 판정과 출력 검사를 더한 점수 (파이프라인과 같은 방식)",
             "- 흔들린 기준 = 회차마다 판정이 달랐던 기준 수", ""]
    rows_csv, majority = [], {}
    for ds in datasets:
        its = [it for it in items if it["dataset"] == ds]
        name = "평가 세트 (규칙을 고칠 때 본 데이터)" if ds == "goldset" else "상세 환자 (규칙을 고칠 때 안 본 데이터)"
        tot = Counter()
        for it in its:
            for g in it["gold"].values():
                tot[g] += 1
            tot["all"] += len(it["gold"])
        lines += [f"## {name}", "",
                  f"기준 {tot['all']}개 (정답 통과 {tot['pass']}, 탈락 {tot['fail']}, 모름 {tot['unknown']},"
                  f" 등록 후 확인 {tot['post_enrollment']}) · 케이스 {len(its)}개", "",
                  "| 조건 | 기준 일치 (AI만) | 기준 일치 (+코드) | 통과·탈락 | 모름 | 등록 후 확인 | 최종 판단 | 누락 | 흔들린 기준 | 완료 회차 |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for c in conds:
            per_rep = defaultdict(lambda: defaultdict(Counter))   # mode -> rep -> 합계
            votes = defaultdict(Counter)
            for it in its:
                for r in range(1, repeats + 1):
                    j = res.get((c, it["case"], r))
                    if not j:
                        continue
                    for mode in ("raw", "code"):
                        per_rep[mode][r].update(score(it, j[mode]))
                    by_id = {x.get("criterion_id"): x for x in j["raw"]}
                    for cid, g in it["gold"].items():
                        x = by_id.get(cid) or {}
                        v = x.get("verdict")
                        votes[(it["case"], cid)][v] += 1
                        rows_csv.append({"condition": c, "dataset": ds, "case": it["case"], "criterion": cid,
                                         "rep": r, "gold": EN2KO.get(g, g), "ai": EN2KO.get(v, "(누락)"),
                                         "ok": v == g, "evidence": (x.get("evidence") or "")[:300]})
            raw, code = per_rep["raw"], per_rep["code"]
            reps = sorted(raw)
            if not reps:
                lines.append(f"| {c} | 결과 없음 | | | | | | | | 0/{repeats} |")
                continue
            col = lambda key, mode="raw": [per_rep[mode][r][key] for r in reps]
            decided = [raw[r]["pass_ok"] + raw[r]["fail_ok"] for r in reps]
            shaky = sum(1 for v in votes.values() if len(v) > 1)
            lines.append(
                f"| {c} | {fmt(col('same'), tot['all'])} | {fmt(col('same', 'code'), tot['all'])}"
                f" | {fmt(decided, tot['pass'] + tot['fail'])} | {fmt(col('unknown_ok'), tot['unknown'])}"
                f" | {fmt(col('post_enrollment_ok'), tot['post_enrollment'])} | {fmt(col('final_ok'), len(its))}"
                f" | {fmt(col('missing'), tot['all'])} | {shaky} | {len(reps)}/{repeats} |")
            for k, v in votes.items():
                majority[(c, ds) + k] = v.most_common(1)[0][0]
        lines.append("")

    # 이웃한 조건끼리 다수결 판정이 바뀐 기준
    order = [c for c in ORDER if c in conds] + [c for c in conds if c not in ORDER]
    changes = []
    gold_of_key = {(it["dataset"], it["case"], cid): g for it in items for cid, g in it["gold"].items()}
    for a, b in zip(order, order[1:]):
        n = Counter()
        for (ds, case, cid), g in gold_of_key.items():
            va, vb = majority.get((a, ds, case, cid)), majority.get((b, ds, case, cid))
            if (a, ds, case, cid) not in majority or (b, ds, case, cid) not in majority or va == vb:
                continue
            kind = "고쳐짐" if vb == g else "망가짐" if va == g else "바뀜(둘 다 틀림)"
            n[(ds, kind)] += 1
            changes.append({"from": a, "to": b, "dataset": ds, "case": case, "criterion": cid,
                            "gold": EN2KO[g], "before": EN2KO.get(va, "(누락)"), "after": EN2KO.get(vb, "(누락)"),
                            "kind": kind})
        if n:
            summary = ", ".join(f"{'평가 세트' if ds == 'goldset' else '상세 환자'} {k} {v}"
                                for (ds, k), v in sorted(n.items()))
            lines.append(f"- **{a} → {b}**: {summary}")
    if changes:
        lines += ["", "바뀐 기준 목록은 changes.csv, 기준별 근거는 criteria.csv에 있어요."]

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name, rows in (("criteria.csv", rows_csv), ("changes.csv", changes)):
        with open(OUT / name, "w", newline="", encoding="utf-8-sig") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
    print("\n".join(lines))
    print(f"\n저장: {(OUT / 'summary.md').relative_to(ROOT)}, criteria.csv, changes.csv")


def main() -> int:
    ap = argparse.ArgumentParser(description="판정 프롬프트 비교 실험")
    ap.add_argument("--conditions", nargs="+", help="돌릴 조건 (기본: prompts/의 모든 조건 + v3, v3_r1112)")
    ap.add_argument("--datasets", nargs="+", choices=["goldset", "detailed"], default=["goldset", "detailed"])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--sheets", nargs="+", type=Path, help="상세 환자 시트 (기본: screening/detailed/*/ 중 다 채워진 것)")
    ap.add_argument("--dry-run", action="store_true", help="무료: 할 일과 예상 비용만 보여 줌")
    ap.add_argument("--report", action="store_true", help="무료: API를 부르지 않고 저장된 결과만 채점")
    ap.add_argument("--no-batch", action="store_true", help="배치 대신 바로 호출 (정가)")
    args = ap.parse_args()

    all_conds = load_conditions()
    names = args.conditions or ([c for c in ORDER if c in all_conds] + [c for c in all_conds if c not in ORDER])
    unknown = [c for c in names if c not in all_conds]
    if unknown:
        sys.exit(f"없는 조건: {unknown} (있는 조건: {list(all_conds)})")
    conds = {c: all_conds[c] for c in names}

    items = goldset_items() if "goldset" in args.datasets else []
    new_profiles = 0
    if "detailed" in args.datasets:
        paths = args.sheets or sorted((ROOT / "screening" / "detailed").glob("*/*_detailed_sheet*.md"))
        # 같은 환자의 시트가 여러 개면 (예: 인선 S004 원본과 _filled) 다 채워진 것 중 마지막 하나만
        by_pid = {}
        for p in paths:
            s = parse_sheet(p)
            if complete(s) is None:
                by_pid[s["patient_id"]] = p
        skipped = [p for p in paths if p not in by_pid.values()]
        for p in skipped:
            why = complete(parse_sheet(p)) or "같은 환자의 다른 시트를 씀"
            print(f"  상세 환자 제외: {p.relative_to(ROOT) if p.is_absolute() else p} ({why})")
        d_items, new_profiles = detailed_items(list(by_pid.values()), dry=args.dry_run)
        items += d_items
        print(f"상세 환자: {sorted(by_pid)}")

    if args.dry_run:
        estimate(conds, items, args.repeats, not args.no_batch, new_profiles)
        return 0
    if not args.report:
        run(conds, items, args.repeats, use_batch=not args.no_batch)
    report(conds, items, args.repeats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
