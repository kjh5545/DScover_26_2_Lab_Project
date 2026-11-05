"""사전 주석 보조: 형식 검사 · 두 주석자 일치도 · 조정 양식 · 확정표 계산 (API 호출 없음, 무료).

정의: ../04_annotation_guideline.md 3절 · 절차: ../annotation_workflow.md 4절 · 확정 선택: ../M4a_approval_packet.md 6절
값을 대신 정하지 않는다. 사람이 적은 값과 조정 결과로 h_strict·h_any(핵심성 2점)만 계산한다.
결과 파일은 덮어쓰지 않는다.

  python experiments/question_ablation/evaluation/annotation_tools.py evidence <근거 목록.csv>
  python experiments/question_ablation/evaluation/annotation_tools.py check S004 <주석.csv> [--clusters <군집.csv>]

근거 ID(EV…)는 evaluation/preannotation/safety_evidence.csv에서 review_status가 "고정"인 행과 대조한다.
이 파일은 사전 주석 전에 고정하고 함께 잠근다.
  python experiments/question_ablation/evaluation/annotation_tools.py compare S004 <주석자1.csv> <주석자2.csv> --out <폴더>
         [--clusters <군집1.csv> <군집2.csv>]
  python experiments/question_ablation/evaluation/annotation_tools.py finalize S004 <주석자1.csv> <주석자2.csv>
         --adjudication <조정.csv> --out <폴더>

파일럿 전용 (S004·S008): 사람 항목별 검토 없이 AI 주석 1부를 그대로 확정표로 옮긴다. 값은 바꾸지 않는다.
절차와 한계: ../annotation_workflow.md 6절. 확인 실험 환자에는 쓰지 않는다.
  python experiments/question_ablation/evaluation/annotation_tools.py finalize-ai S004 <AI 주석.csv> --out <폴더>
"""

import argparse
import json
import re
import sys
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))

import scoring as sc  # noqa: E402

FIELDS = ("askable", "centrality")
TEXT_FIELDS = ("centrality_evidence", "core_part", "core_info")   # 핵심성 2점 기준에서만 조정한다
WHOLE = sc.WHOLE
GIVEN = sc.SCHEMA["preannotation_columns"]["given"]
SHEET = "preannotation"
EVIDENCE = HERE / "preannotation" / "safety_evidence.csv"
AI_LABEL = "AI 주석 버전 고정"
AI_PATIENTS = ("S004", "S008")


def norm(text: str) -> str:
    return " ".join(str(text).split())


def source_rows(pid: str) -> dict:
    """배포한 원본 주석표. 주석자가 바꾸면 안 되는 열의 기준."""
    return {r["annotation_id"]: r for r in sc.read_csv(HERE / "preannotation" / f"{pid}_preannotation.csv")}


def evidence_ids(path: Path = EVIDENCE) -> set | None:
    """인용할 수 있는 근거 ID: 모든 열이 채워지고 review_status가 "고정"인 행. 파일이 없으면 None (대조 생략)."""
    if not path.exists():
        return None
    cols = sc.SCHEMA["safety_evidence_columns"]
    return {r["evidence_id"] for r in sc.read_csv(path)
            if all(r.get(c, "").strip() for c in cols) and r["review_status"] == "고정"
            and re.fullmatch(r"EV[\w-]+", r["evidence_id"])}


def check_evidence_list(path: Path) -> list[str]:
    """근거 목록 형식 검사. 검토 대기 행은 검토자·고정일이 비어 있어도 되지만, 고정 행은 모든 열이 필요하다."""
    cols, errs, seen = sc.SCHEMA["safety_evidence_columns"], [], set()
    rows = sc.read_csv(path)
    if rows and list(rows[0]) != cols:
        return [f"열이 양식과 다름: {list(rows[0])}"]
    review_cols = ("reviewed_by", "fixed_date")
    for i, r in enumerate(rows, 2):
        status = r.get("review_status", "")
        if status not in sc.SCHEMA["safety_evidence_status"]:
            errs.append(f"{i}행: review_status 값 오류 {status!r}")
        need = cols if status == "고정" else [c for c in cols if c not in review_cols + ("reason_for_2",)]
        empty = [c for c in need if not r.get(c, "").strip()]
        if empty:
            errs.append(f"{i}행: 빈 열 {empty}")
        if not re.fullmatch(r"EV[\w-]+", r.get("evidence_id", "")):
            errs.append(f"{i}행: evidence_id는 EV로 시작")
        if r.get("evidence_id") in seen:
            errs.append(f"{i}행: evidence_id 중복")
        seen.add(r.get("evidence_id"))
    return errs


def check(pid: str, rows: list[dict], evidence: set | None = None) -> list[str]:
    """주석자 1명의 파일 검사. 빈 목록이면 통과. evidence: 근거 목록 ID (None이면 대조 생략)."""
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
            if any(r.get(f, "") for f in FIELDS + TEXT_FIELDS):
                errs.append(f"{aid}: 후보가 아닌 기준은 작성하지 않음")
            continue
        for f in FIELDS:
            if r.get(f, "") not in v[f]:
                errs.append(f"{aid}: {f} 값 오류 {r.get(f)!r}")
        core, info = r.get("core_part", "").strip(), r.get("core_info", "").strip()
        if r.get("centrality") == "2":
            if not r.get("centrality_evidence", "").strip():
                errs.append(f"{aid}: 핵심성 2점에는 근거(centrality_evidence) 필요")
            if not core or not info:
                errs.append(f"{aid}: 핵심성 2점에는 core_part(일부면 원문 표현, 기준 전체면 '{WHOLE}')와 core_info 필요")
        elif core or info:
            errs.append(f"{aid}: core_part·core_info는 핵심성 2점 기준에만 적는다")
        cited = set(re.findall(r"\bEV[\w-]+", r.get("centrality_evidence", "")))
        if evidence is not None and cited - evidence:
            errs.append(f"{aid}: 근거 목록에 없거나 미완성인 근거 {sorted(cited - evidence)}")
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


def cluster_pairs(rows: list[dict]) -> set:
    groups = {}
    for r in rows:
        groups.setdefault(r["cluster_id"], set()).add(f"{r['trial_id']}|{r['criterion_id']}")
    return {tuple(sorted(p)) for g in groups.values() for p in combinations(g, 2)}


def adjudication_rows(a: dict, b: dict) -> list[dict]:
    """값이 다르거나 양쪽 모두 UNSURE인 항목. askable은 UNSURE로 확정할 수 없으므로 조정이 필요하다.

    근거·핵심 부분·필요 정보는 한 주석자라도 핵심성 2점을 주었고 문구가 다를 때 조정한다.
    """
    rows = []
    for k in sorted(a):
        core = "2" in (a[k]["centrality"], b[k]["centrality"])
        for f in FIELDS + (TEXT_FIELDS if core else ()):
            x, y = a[k][f], b[k][f]
            if (norm(x) != norm(y)) if f in TEXT_FIELDS else (x != y or x == "UNSURE"):
                rows.append({"sheet": SHEET, "item_key": k, "field": f, "rater1_id": a[k]["rater_id"],
                             "rater1_value": x, "rater2_id": b[k]["rater_id"], "rater2_value": y,
                             "final_value": "", "reason": "", "adjudicator_id": ""})
    return rows


def load_pair(pid: str, file_a: Path, file_b: Path, evidence: Path = EVIDENCE) -> tuple[dict, dict]:
    ra, rb = sc.read_csv(file_a), sc.read_csv(file_b)
    ids = evidence_ids(evidence)
    errs = [f"주석자1 {e}" for e in check(pid, ra, ids)] + [f"주석자2 {e}" for e in check(pid, rb, ids)]
    if errs:
        raise ValueError(f"형식 오류 {len(errs)}건: " + "; ".join(errs[:5]))
    a, b = candidates(ra), candidates(rb)
    ids_a, ids_b = {r["rater_id"] for r in a.values()}, {r["rater_id"] for r in b.values()}
    if ids_a & ids_b:
        raise ValueError(f"두 파일의 rater_id가 겹침: {sorted(ids_a & ids_b)}")
    return a, b


def compare(pid: str, file_a: Path, file_b: Path, out: Path, clusters: tuple[Path, Path] | None = None) -> dict:
    a, b = load_pair(pid, file_a, file_b)
    keys = sorted(a)
    stats = {f: sc.agreement([a[k][f] for k in keys], [b[k][f] for k in keys]) for f in FIELDS}
    core = lambda r: sc.is_core(r["centrality"])  # noqa: E731
    stats["is_H"] = sc.agreement([str(core(a[k])) for k in keys], [str(core(b[k])) for k in keys])
    h_a, h_b = {k for k in keys if core(a[k])}, {k for k in keys if core(b[k])}
    both = sorted(h_a & h_b)
    whole = lambda r: norm(r["core_part"]) == WHOLE  # noqa: E731
    adj = adjudication_rows(a, b)
    result = {"patient_id": pid, "candidates": len(keys), "agreement": stats,
              "H": {"rater1": len(h_a), "rater2": len(h_b), "both": len(h_a & h_b), "either_h_any": len(h_a | h_b)},
              "core_part": {"whole_rater1": sum(whole(a[k]) for k in h_a), "whole_rater2": sum(whole(b[k]) for k in h_b),
                            "same_text_when_both_H": sum(norm(a[k]["core_part"]) == norm(b[k]["core_part"]) for k in both),
                            "both_H": len(both)},
              "to_adjudicate": len(adj),
              "note": "H는 핵심성 2점. 핵심 부분 문구 차이는 한 명이라도 2점이면 조정 대상이다."}
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


def finalize(pid: str, file_a: Path, file_b: Path, adjudication: Path, out: Path) -> dict:
    """조정 결과를 반영해 {pid}_final.csv를 만든다. 조정이 비었거나 낡았으면 만들지 않는다."""
    a, b = load_pair(pid, file_a, file_b)
    need = {(r["item_key"], r["field"]) for r in adjudication_rows(a, b)}
    adj = [r for r in sc.read_csv(adjudication) if r["sheet"] == SHEET]
    have = {(r["item_key"], r["field"]): r for r in adj}
    v, errs = sc.SCHEMA["values"], []
    if set(have) != need:
        errs.append(f"조정표가 현재 불일치와 다름 (빠짐 {len(need - set(have))}, 초과 {len(set(have) - need)})")
    for (k, f), r in sorted(have.items()):
        if f in FIELDS and r["final_value"] not in v[f]:
            errs.append(f"{k} {f}: final_value 값 오류 {r['final_value']!r}")
        elif f == "askable" and r["final_value"] == "UNSURE":
            errs.append(f"{k}: final_askable은 UNSURE일 수 없음")
        if not r["reason"].strip() or not r["adjudicator_id"].strip():
            errs.append(f"{k} {f}: 조정 사유·adjudicator_id 필요")
    rows = []
    for k in sorted(a):
        final = {f: have[(k, f)]["final_value"] if (k, f) in have else a[k][f] for f in FIELDS + TEXT_FIELDS}
        if final["centrality"] != "2":       # 핵심 부분은 핵심성 2점 기준에만 둔다
            final.update(core_part="", core_info="")
        elif not final["centrality_evidence"].strip():
            errs.append(f"{k}: 확정 핵심성 2점의 근거 없음")
        elif not final["core_part"].strip() or not final["core_info"].strip():
            errs.append(f"{k}: 확정 핵심성 2점에 핵심 부분(또는 '{WHOLE}')과 필요한 정보 필요")
        notes = [f"{f}: {have[(k, f)]['reason']}" for f in FIELDS + TEXT_FIELDS if (k, f) in have]
        rows.append({"patient_id": pid, "trial_id": a[k]["trial_id"], "criterion_id": a[k]["criterion_id"],
                     "final_askable": final["askable"], "final_centrality": final["centrality"],
                     "final_centrality_evidence": norm(final["centrality_evidence"]),
                     "final_core_part": norm(final["core_part"]), "final_core_info": norm(final["core_info"]),
                     "h_strict": str(sc.is_core(final["centrality"])).lower(),
                     "h_any": str(sc.is_core(a[k]["centrality"]) or sc.is_core(b[k]["centrality"])).lower(),
                     "adjudication_note": " / ".join(notes)})
    if errs:
        raise ValueError(f"조정 오류 {len(errs)}건: " + "; ".join(errs[:5]))
    path = out / f"{pid}_final.csv"
    if path.exists():
        raise FileExistsError(path)
    sc.write_csv(path, sc.SCHEMA["preannotation_final_columns"], rows)
    summary = {"patient_id": pid, "rows": len(rows), "h_strict": sum(r["h_strict"] == "true" for r in rows),
               "h_any": sum(r["h_any"] == "true" for r in rows),
               "centrality_unsure": sum(r["final_centrality"] == "UNSURE" for r in rows),
               "core_part_whole": sum(r["final_core_part"] == WHOLE for r in rows),
               "core_part_specific": sum(bool(r["final_core_part"]) and r["final_core_part"] != WHOLE for r in rows),
               "askable": {x: sum(r["final_askable"] == x for r in rows) for x in v["askable"][:3]}, "file": str(path)}
    if summary["h_strict"] == 0:
        summary["note"] = "H가 0개이다. M4a와 관련 보조값은 값 없음으로 보고되고 n_H=0이 함께 기록된다. 잠금은 가능하다."
    return summary


def finalize_ai(pid: str, file: Path, out: Path, clusters: Path | None = None) -> dict:
    """파일럿 전용. AI 주석 1부를 조정 없이 {pid}_final.csv로 옮긴다 (AI 주석 버전 고정).

    값을 고치거나 채우지 않는다. 주석자가 1명이므로 h_any는 h_strict와 같다 (주석자 간 차이 정보 없음).
    askable UNSURE는 확정할 수 없으므로 거부한다. 군집 파일이 없으면 머리글만 쓰고 "군집 미주석"으로 표시한다.
    """
    if pid not in AI_PATIENTS:
        raise ValueError(f"AI 주석 경로는 파일럿 환자 {AI_PATIENTS}에만 쓸 수 있음: {pid}")
    rows = sc.read_csv(file)
    errs = check(pid, rows, evidence_ids())
    a = candidates(rows)
    errs += [f"{k}: askable UNSURE는 확정할 수 없음 (값을 대신 정하지 않음)" for k, r in a.items() if r["askable"] == "UNSURE"]
    raters = sorted({r["rater_id"] for r in a.values()})
    if len(raters) != 1:
        errs.append(f"rater_id가 하나가 아님: {raters}")
    cl_rows = sc.read_csv(clusters) if clusters else []
    if clusters:
        errs += check_clusters(pid, cl_rows)
    if errs:
        raise ValueError(f"형식 오류 {len(errs)}건: " + "; ".join(errs[:5]))
    paths = [out / f"{pid}_final.csv", out / f"{pid}_clusters.csv"]
    for p in paths:
        if p.exists():
            raise FileExistsError(p)
    final = []
    for k in sorted(a):
        r, core = a[k], sc.is_core(a[k]["centrality"])
        final.append({"patient_id": pid, "trial_id": r["trial_id"], "criterion_id": r["criterion_id"],
                      "final_askable": r["askable"], "final_centrality": r["centrality"],
                      "final_centrality_evidence": norm(r["centrality_evidence"]),
                      "final_core_part": norm(r["core_part"]), "final_core_info": norm(r["core_info"]),
                      "h_strict": str(core).lower(), "h_any": str(core).lower(),
                      "adjudication_note": f"{AI_LABEL}: 사람 항목별 검토 없음, 조정 없음 "
                                           f"(rater_id={r['rater_id']}, needs_review={r.get('needs_review', '')})"})
    sc.write_csv(paths[0], sc.SCHEMA["preannotation_final_columns"], final)
    sc.write_csv(paths[1], sc.SCHEMA["cluster_columns"], cl_rows)
    count = lambda f, x: sum(r[f] == x for r in final)  # noqa: E731
    return {"patient_id": pid, "status": AI_LABEL, "rater_id": raters[0], "rows": len(final),
            "centrality": {x: count("final_centrality", x) for x in sc.SCHEMA["values"]["centrality"]},
            "askable": {x: count("final_askable", x) for x in sc.SCHEMA["values"]["askable"][:3]},
            "h_strict": count("h_strict", "true"), "centrality_unsure_not_H": count("final_centrality", "UNSURE"),
            "core_part_whole": count("final_core_part", WHOLE),
            "core_part_specific": sum(bool(r["final_core_part"]) and r["final_core_part"] != WHOLE for r in final),
            "clusters": len(cl_rows) if clusters else "군집 미주석 (M5b 값 없음)",
            "files": [str(p) for p in paths]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("evidence", help="안전 조건 근거 목록 형식 검사")
    p.add_argument("file", type=Path)
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
    p = sub.add_parser("finalize-ai", help="파일럿 전용: AI 주석 1부를 조정 없이 확정표로 (AI 주석 버전 고정)")
    p.add_argument("patient")
    p.add_argument("file", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--clusters", type=Path)
    args = ap.parse_args()
    try:
        if args.cmd == "evidence":
            errs = check_evidence_list(args.file)
            print("\n".join(errs) or "통과")
            return 1 if errs else 0
        if args.cmd == "check":
            errs = check(args.patient, sc.read_csv(args.file), evidence_ids())
            if args.clusters:
                errs += check_clusters(args.patient, sc.read_csv(args.clusters))
            print("\n".join(errs) or "통과")
            return 1 if errs else 0
        if args.cmd == "finalize-ai":
            result = finalize_ai(args.patient, args.file, args.out, args.clusters)
        elif args.cmd == "compare":
            result = compare(args.patient, args.file_a, args.file_b, args.out, args.clusters)
        else:
            result = finalize(args.patient, args.file_a, args.file_b, args.adjudication, args.out)
    except (ValueError, FileExistsError) as e:
        print(f"[중단] {e}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
