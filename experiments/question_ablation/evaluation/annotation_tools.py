"""사전 주석 보조: 형식 검사 · 두 주석자 일치도 · 조정 양식 · 확정표 계산 (API 호출 없음, 무료).

정의: ../04_annotation_guideline.md 3절 · 절차: ../annotation_workflow.md 4절
값을 대신 정하지 않는다. 사람이 적은 값과 조정 결과로 등급·h_strict·h_any만 계산한다.
결과 파일은 덮어쓰지 않는다.

  python experiments/question_ablation/evaluation/annotation_tools.py check S004 <주석.csv> [--clusters <군집.csv>]
  python experiments/question_ablation/evaluation/annotation_tools.py compare S004 <주석자1.csv> <주석자2.csv> --out <폴더>
         [--clusters <군집1.csv> <군집2.csv>]
  python experiments/question_ablation/evaluation/annotation_tools.py finalize S004 <주석자1.csv> <주석자2.csv>
         --adjudication <조정.csv> --out <폴더> [--score-columns]
"""

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))

import scoring as sc  # noqa: E402

FIELDS = ("askable", "decisiveness", "centrality")
GIVEN = sc.SCHEMA["preannotation_columns"]["given"]
SHEET = "preannotation"


def source_rows(pid: str) -> dict:
    """배포한 원본 주석표. 주석자가 바꾸면 안 되는 열의 기준."""
    return {r["annotation_id"]: r for r in sc.read_csv(HERE / "preannotation" / f"{pid}_preannotation.csv")}


def check(pid: str, rows: list[dict]) -> list[str]:
    """주석자 1명의 파일 검사. 빈 목록이면 통과."""
    src, errs = source_rows(pid), []
    got = {r["annotation_id"]: r for r in rows}
    if set(got) != set(src):
        errs.append(f"{pid}: 행이 원본과 다름 (빠짐 {len(set(src) - set(got))}, 초과 {len(set(got) - set(src))})")
    v = sc.SCHEMA["values"]
    for aid, r in sorted(got.items()):
        if aid not in src:
            continue
        changed = [c for c in GIVEN if r.get(c, "") != src[aid][c]]
        if changed:
            errs.append(f"{aid}: 주어진 열이 바뀜 {changed}")
        if src[aid]["is_candidate"] != "1":
            if any(r.get(f, "") for f in FIELDS):
                errs.append(f"{aid}: 후보가 아닌 기준은 작성하지 않음")
            continue
        for f in FIELDS:
            if r.get(f, "") not in v[f]:
                errs.append(f"{aid}: {f} 값 오류 {r.get(f)!r}")
        if "UNSURE" in (r.get(f) for f in FIELDS) and not r.get("unsure_reason", "").strip():
            errs.append(f"{aid}: UNSURE에는 판단 불가 사유 필요")
        if not r.get("rationale", "").strip():
            errs.append(f"{aid}: rationale 없음")
        if not r.get("rater_id", "").strip():
            errs.append(f"{aid}: rater_id 없음")
    return errs


def check_clusters(pid: str, rows: list[dict]) -> list[str]:
    cand = {(r["trial_id"], r["criterion_id"]) for r in source_rows(pid).values() if r["is_candidate"] == "1"}
    errs, seen = [], {}
    for i, r in enumerate(rows, 2):
        key = (r.get("trial_id", ""), r.get("criterion_id", ""))
        if r.get("patient_id") != pid:
            errs.append(f"{i}행: patient_id가 {pid}가 아님")
        if key not in cand:
            errs.append(f"{i}행: 후보 기준이 아님 {key}")
        if not r.get("cluster_id", "").strip() or not r.get("shared_fact", "").strip():
            errs.append(f"{i}행: cluster_id·shared_fact 필요")
        if key in seen and seen[key] != r.get("cluster_id"):
            errs.append(f"{i}행: {key}가 두 군집에 들어 있음")
        seen[key] = r.get("cluster_id")
    sizes = {}
    for r in rows:
        sizes[r.get("cluster_id")] = sizes.get(r.get("cluster_id"), 0) + 1
    errs += [f"군집 {c}: 기준이 1개뿐" for c, n in sizes.items() if n < 2]
    return errs


def candidates(rows: list[dict]) -> dict:
    return {r["annotation_id"]: r for r in rows if r["is_candidate"] == "1"}


def with_tier(rows: dict) -> dict:
    return {k: {**r, "tier": sc.impact_tier(r["decisiveness"], r["centrality"])} for k, r in rows.items()}


def cluster_pairs(rows: list[dict]) -> set:
    groups = {}
    for r in rows:
        groups.setdefault(r["cluster_id"], set()).add(f"{r['trial_id']}|{r['criterion_id']}")
    return {tuple(sorted(p)) for g in groups.values() for p in combinations(g, 2)}


def adjudication_rows(a: dict, b: dict) -> list[dict]:
    """값이 다르거나 양쪽 모두 UNSURE인 항목. askable은 UNSURE로 확정할 수 없으므로 조정이 필요하다."""
    rows = []
    for k in sorted(a):
        for f in FIELDS:
            x, y = a[k][f], b[k][f]
            if x != y or x == "UNSURE":
                rows.append({"sheet": SHEET, "item_key": k, "field": f, "rater1_id": a[k]["rater_id"],
                             "rater1_value": x, "rater2_id": b[k]["rater_id"], "rater2_value": y,
                             "final_value": "", "reason": "", "adjudicator_id": ""})
    return rows


def load_pair(pid: str, file_a: Path, file_b: Path) -> tuple[dict, dict]:
    ra, rb = sc.read_csv(file_a), sc.read_csv(file_b)
    errs = [f"주석자1 {e}" for e in check(pid, ra)] + [f"주석자2 {e}" for e in check(pid, rb)]
    if errs:
        raise ValueError(f"형식 오류 {len(errs)}건: " + "; ".join(errs[:5]))
    a, b = with_tier(candidates(ra)), with_tier(candidates(rb))
    ids_a, ids_b = {r["rater_id"] for r in a.values()}, {r["rater_id"] for r in b.values()}
    if ids_a & ids_b:
        raise ValueError(f"두 파일의 rater_id가 겹침: {sorted(ids_a & ids_b)}")
    return a, b


def compare(pid: str, file_a: Path, file_b: Path, out: Path, clusters: tuple[Path, Path] | None = None) -> dict:
    a, b = load_pair(pid, file_a, file_b)
    keys = sorted(a)
    stats = {f: sc.agreement([a[k][f] for k in keys], [b[k][f] for k in keys]) for f in FIELDS + ("tier",)}
    stats["is_H"] = sc.agreement([str(a[k]["tier"] == "H") for k in keys], [str(b[k]["tier"] == "H") for k in keys])
    h_a, h_b = {k for k in keys if a[k]["tier"] == "H"}, {k for k in keys if b[k]["tier"] == "H"}
    adj = adjudication_rows(a, b)
    result = {"patient_id": pid, "candidates": len(keys), "agreement": stats,
              "H": {"rater1": len(h_a), "rater2": len(h_b), "both": len(h_a & h_b), "either_h_any": len(h_a | h_b)},
              "tier_blank": {"rater1": sum(not a[k]["tier"] for k in keys), "rater2": sum(not b[k]["tier"] for k in keys)},
              "to_adjudicate": len(adj),
              "note": "등급은 직접성과 핵심성에서 계산된다. 등급 불일치는 두 점수의 조정으로 해소한다."}
    if clusters:
        ca, cb = sc.read_csv(clusters[0]), sc.read_csv(clusters[1])
        errs = [f"군집1 {e}" for e in check_clusters(pid, ca)] + [f"군집2 {e}" for e in check_clusters(pid, cb)]
        if errs:
            raise ValueError(f"군집 형식 오류 {len(errs)}건: " + "; ".join(errs[:5]))
        pa, pb = cluster_pairs(ca), cluster_pairs(cb)
        result["clusters"] = {"pairs_rater1": len(pa), "pairs_rater2": len(pb), "pairs_both": len(pa & pb),
                              "pair_jaccard": len(pa & pb) / len(pa | pb) if pa | pb else None,
                              "only_rater1": sorted(map(list, pa - pb)), "only_rater2": sorted(map(list, pb - pa))}
    for name in (f"{pid}_annotation_agreement.json", f"{pid}_adjudication.csv"):
        if (out / name).exists():
            raise FileExistsError(out / name)
    sc.write_csv(out / f"{pid}_adjudication.csv", sc.SCHEMA["adjudication_columns"], adj)
    (out / f"{pid}_annotation_agreement.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                                          encoding="utf-8")
    return result


def finalize(pid: str, file_a: Path, file_b: Path, adjudication: Path, out: Path, score_columns: bool = False) -> dict:
    """조정 결과를 반영해 {pid}_final.csv를 만든다. 조정이 비었거나 낡았으면 만들지 않는다."""
    a, b = load_pair(pid, file_a, file_b)
    need = {(r["item_key"], r["field"]) for r in adjudication_rows(a, b)}
    adj = [r for r in sc.read_csv(adjudication) if r["sheet"] == SHEET]
    have = {(r["item_key"], r["field"]): r for r in adj}
    v, errs = sc.SCHEMA["values"], []
    if set(have) != need:
        errs.append(f"조정표가 현재 불일치와 다름 (빠짐 {len(need - set(have))}, 초과 {len(set(have) - need)})")
    for (k, f), r in sorted(have.items()):
        if r["final_value"] not in v[f]:
            errs.append(f"{k} {f}: final_value 값 오류 {r['final_value']!r}")
        elif f == "askable" and r["final_value"] == "UNSURE":
            errs.append(f"{k}: final_askable은 UNSURE일 수 없음")
        if not r["reason"].strip() or not r["adjudicator_id"].strip():
            errs.append(f"{k} {f}: 조정 사유·adjudicator_id 필요")
    if errs:
        raise ValueError(f"조정 오류 {len(errs)}건: " + "; ".join(errs[:5]))
    cols = sc.SCHEMA["preannotation_final_columns"] + (["final_decisiveness", "final_centrality"] if score_columns else [])
    rows = []
    for k in sorted(a):
        final = {f: have[(k, f)]["final_value"] if (k, f) in have else a[k][f] for f in FIELDS}
        tier = sc.impact_tier(final["decisiveness"], final["centrality"])
        notes = [f"{f}: {have[(k, f)]['reason']}" for f in FIELDS if (k, f) in have]
        row = {"patient_id": pid, "trial_id": a[k]["trial_id"], "criterion_id": a[k]["criterion_id"],
               "final_askable": final["askable"], "final_tier": tier, "h_strict": str(tier == "H").lower(),
               "h_any": str("H" in (a[k]["tier"], b[k]["tier"])).lower(), "adjudication_note": " / ".join(notes)}
        if score_columns:
            row.update(final_decisiveness=final["decisiveness"], final_centrality=final["centrality"])
        rows.append(row)
    path = out / f"{pid}_final.csv"
    if path.exists():
        raise FileExistsError(path)
    sc.write_csv(path, cols, rows)
    summary = {"patient_id": pid, "rows": len(rows), "h_strict": sum(r["h_strict"] == "true" for r in rows),
               "h_any": sum(r["h_any"] == "true" for r in rows), "tier_blank": sum(not r["final_tier"] for r in rows),
               "askable": {x: sum(r["final_askable"] == x for r in rows) for x in v["askable"][:3]}, "file": str(path)}
    if summary["h_strict"] == 0:
        summary["warning"] = "h_strict가 0개라 잠금이 거부된다. 임의로 H를 늘리지 말고 관리자에게 알린다."
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="주석자 1명의 파일 형식 검사")
    p.add_argument("patient")
    p.add_argument("file", type=Path)
    p.add_argument("--clusters", type=Path)
    p = sub.add_parser("compare", help="두 주석자 일치도와 조정 양식")
    p.add_argument("patient")
    p.add_argument("file_a", type=Path)
    p.add_argument("file_b", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--clusters", type=Path, nargs=2)
    p = sub.add_parser("finalize", help="조정 반영 확정표 생성")
    p.add_argument("patient")
    p.add_argument("file_a", type=Path)
    p.add_argument("file_b", type=Path)
    p.add_argument("--adjudication", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--score-columns", action="store_true", help="팀이 M4a 결정 5를 승인한 경우에만")
    args = ap.parse_args()
    try:
        if args.cmd == "check":
            errs = check(args.patient, sc.read_csv(args.file))
            if args.clusters:
                errs += check_clusters(args.patient, sc.read_csv(args.clusters))
            print("\n".join(errs) or "통과")
            return 1 if errs else 0
        if args.cmd == "compare":
            result = compare(args.patient, args.file_a, args.file_b, args.out, args.clusters)
        else:
            result = finalize(args.patient, args.file_a, args.file_b, args.adjudication, args.out, args.score_columns)
    except (ValueError, FileExistsError) as e:
        print(f"[중단] {e}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
