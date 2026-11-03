"""질문 생성 평가: 블라인드 채점표 생성·검사·잠금·지표 계산 (API 호출 없음, 무료).

정의: ../04_question_rubric.md · 코드값과 열 이름: scoring_schema.json

  python experiments/question_ablation/evaluation/scoring.py templates
  python experiments/question_ablation/evaluation/scoring.py preannotation S004 S008
  python experiments/question_ablation/evaluation/scoring.py packet <runs.json> <채점표 폴더> <봉인 폴더> --seed <정수>
  python experiments/question_ablation/evaluation/scoring.py validate <question.csv> <link.csv>
  python experiments/question_ablation/evaluation/scoring.py lock <봉인 폴더> <question.csv> <link.csv>
"""

import argparse
import csv
import hashlib
import json
import random
import re
import sys
import types
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
SCHEMA = json.loads((HERE / "scoring_schema.json").read_text(encoding="utf-8"))
QC = SCHEMA["question_columns"]["given"] + SCHEMA["question_columns"]["rated"]
LC = SCHEMA["link_columns"]["given"] + SCHEMA["link_columns"]["rated"]
PC = SCHEMA["preannotation_columns"]["given"] + SCHEMA["preannotation_columns"]["rated"]
TIERS = {"H": 3, "M": 2}
HANGUL_MIN = 0.5    # 저장된 v2.3.3 질문 47개의 최솟값 0.556. 이보다 낮으면 출력 언어 이탈로 표시


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def sha_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_templates(out: Path = HERE / "templates") -> None:
    empty = lambda cols: {c: "" for c in cols}  # noqa: E731
    sheets = {"question_sheet_template": QC, "link_sheet_template": LC, "preannotation_template": PC,
              "shared_cluster_template": SCHEMA["cluster_columns"],
              "preannotation_final_template": SCHEMA["preannotation_final_columns"],
              "adjudication_template": SCHEMA["adjudication_columns"],
              "simulator_audit_template": SCHEMA["simulator_audit_columns"],
              "rater_registry_template": SCHEMA["rater_registry_columns"]}
    for name, cols in sheets.items():
        write_csv(out / f"{name}.csv", cols, [])
    (out / "question_sheet_template.json").write_text(
        json.dumps({"records": [empty(QC)]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "link_sheet_template.json").write_text(
        json.dumps({"records": [empty(LC)]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "annotation_record_template.json").write_text(json.dumps(
        {"m4a_definition_review": {"approved": False, "reviewed_by": [], "date": "", "note": ""},
         "judge_freeze_confirmed_by": [],
         "people": [{"id": "", "role": "annotator | rater | adjudicator | manager",
                     "gold_exposed": "none | partial | full", "exposure_scope": ""}]},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "blind_map_template.json").write_text(json.dumps(
        {"warning": "채점자에게 주지 않는다. 채점 결과 잠금 전에는 열지 않는다.", "seed": None,
         "sets": {"<blind_id>": {"run_key": "", "arm": "", "patient_id": "", "rep": None}}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_project():
    """저장소 코드를 불러온다. 없는 패키지는 호출 불가 스텁으로 대체."""
    class Blocked:
        def __init__(self, *a, **k):
            raise RuntimeError("API 호출 차단")
    for name in ("anthropic", "requests", "certifi"):
        try:
            __import__(name)
        except ImportError:
            mod = types.ModuleType(name)
            mod.Anthropic = Blocked
            sys.modules[name] = mod
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT))
    from src.question_builder import collect_materials
    from src.testing.goldset_bundle import make_bundle
    return make_bundle, collect_materials


def preannotation_rows(pid: str) -> list[dict]:
    """사전 주석 입력: 짧은 설명 + 기준 원문 + 초기 판정. 정답·상세 설명·생성 질문은 넣지 않는다."""
    make_bundle, collect_materials = _load_project()
    bundle = make_bundle(pid)
    cand = {(m["trial"], m["criterion_id"]) for m in collect_materials(bundle)}
    rows = []
    for t in bundle["trials"]:
        verdict = {j["criterion_id"]: j["verdict"] for j in t["judgments"]}
        for c in t["criteria"]:
            is_cand = (t["nct_id"], c["id"]) in cand
            rows.append({"annotation_id": f"{pid}-{t['nct_id']}-{c['id']}", "patient_id": pid,
                         "patient_text": bundle["case_text"], "trial_id": t["nct_id"],
                         "trial_status": t["final_judgment"], "criterion_id": c["id"], "criterion_type": c["type"],
                         "criterion_text": c["text"], "initial_verdict": verdict.get(c["id"], ""),
                         "is_candidate": int(is_cand), **{k: "" for k in SCHEMA["preannotation_columns"]["rated"]}})
    return rows


def impact_tier(decisiveness: str, centrality: str) -> str:
    """판정 직접성 + 시험 대상 핵심성 → H(3 이상) / M(2) / L(1 이하). 판단 불가면 빈 값."""
    if not (str(decisiveness).isdigit() and str(centrality).isdigit()):
        return ""
    total = int(decisiveness) + int(centrality)
    return "H" if total >= TIERS["H"] else "M" if total == TIERS["M"] else "L"


def build_packet(runs: list[dict], out: Path, sealed: Path, seed: int) -> dict:
    """실행 기록 → 채점표. 실행마다 무작위 blind_id를 주고 ID 순으로 정렬해 조건·회차 순서를 지운다.

    runs: [{"run_key", "arm", "patient_id", "rep", "criteria": {"시험|기준": {"text", "type"}},
            "final_questions": [{"text", "needed_info", "resolves": [{"trial", "criteria"}]}]}]
    질문 순서(question_no)는 M4b에 필요하므로 세트 안에서 유지한다.
    """
    rng = random.Random(seed)
    ids = rng.sample(range(16 ** 6), len(runs))
    order = list(range(len(runs)))
    rng.shuffle(order)
    qrows, lrows, mapping = [], [], {}
    for idx, run in zip(ids, (runs[i] for i in order)):
        bid = f"B{idx:06X}"
        mapping[bid] = {k: run[k] for k in ("run_key", "arm", "patient_id", "rep")}
        for no, q in enumerate(run["final_questions"], 1):
            links = [(r["trial"], c) for r in q["resolves"] for c in r["criteria"]]
            base = {"blind_id": bid, "patient_id": run["patient_id"], "question_no": no,
                    "question_text": q["text"], "needed_info": q.get("needed_info", "")}
            qrows.append({**{c: "" for c in QC}, **base, "n_links": len(links),
                          "n_trials": len({t for t, _ in links})})
            for trial, cid in links:
                c = run["criteria"][f"{trial}|{cid}"]
                lrows.append({**{k: "" for k in LC}, **base, "trial_id": trial, "criterion_id": cid,
                              "criterion_type": c.get("type", ""), "criterion_text": c["text"],
                              "is_multi_link": int(len(links) > 1)})
    qrows.sort(key=lambda r: (r["patient_id"], r["blind_id"], r["question_no"]))
    lrows.sort(key=lambda r: (r["patient_id"], r["blind_id"], r["question_no"], r["trial_id"], r["criterion_id"]))
    write_csv(out / "question_sheet.csv", QC, qrows)
    write_csv(out / "link_sheet.csv", LC, lrows)
    (out / "question_sheet.json").write_text(json.dumps({"records": qrows}, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
    (out / "link_sheet.json").write_text(json.dumps({"records": lrows}, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    sealed.mkdir(parents=True, exist_ok=True)
    (sealed / "blind_map.json").write_text(json.dumps({"seed": seed, "sets": mapping}, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")
    return mapping


def double_score_sample(mapping: dict, seed: int) -> list[str]:
    """이중 채점 세트: 환자×조건마다 1세트 이상. 조정자가 고르고 채점자에게는 blind_id만 준다."""
    rng = random.Random(seed)
    cells = defaultdict(list)
    for bid, m in sorted(mapping.items()):
        cells[(m["patient_id"], m["arm"])].append(bid)
    return sorted(rng.choice(v) for _, v in sorted(cells.items()))


def _codes(s: str) -> list[str]:
    return [c for c in re.split(r"[;,\s]+", s or "") if c]


def validate(qrows: list[dict], lrows: list[dict]) -> list[str]:
    """채점표 규칙 검사. 빈 목록이면 통과."""
    errs = []
    v, known = SCHEMA["values"], SCHEMA["error_codes"]

    def need(row, where, field):
        if row.get(field, "") not in v[field]:
            errs.append(f"{where}: {field} 값 오류 {row.get(field)!r}")

    for r in qrows:
        w = f"Q {r['blind_id']}#{r['question_no']}"
        for f in ("assumption", "redundancy", "single_topic", "overgroup"):
            need(r, w, f)
            code = r.get(f"{f}_error", "")
            if r.get(f) == "FAIL" and not code:
                errs.append(f"{w}: {f}=FAIL인데 오류 코드 없음")
            if r.get(f) in ("PASS", "NA") and code:
                errs.append(f"{w}: {f}={r.get(f)}인데 오류 코드 있음")
            if code and code not in known:
                errs.append(f"{w}: 모르는 코드 {code}")
        if int(r["n_links"] or 0) < 2 and r.get("overgroup") != "NA":
            errs.append(f"{w}: 기준 1개 연결 질문의 overgroup은 NA")
        if int(r["n_links"] or 0) >= 2 and r.get("overgroup") == "NA":
            errs.append(f"{w}: 다기준 질문의 overgroup은 NA일 수 없음")
        if "R1" == r.get("redundancy_error") and not r.get("duplicate_of"):
            errs.append(f"{w}: R1은 duplicate_of 필요")
        if "UNSURE" in (r.get("assumption"), r.get("redundancy"), r.get("single_topic"), r.get("overgroup")) \
                and not r.get("unsure_reason"):
            errs.append(f"{w}: UNSURE에는 판단 불가 사유 필요")
        if "FAIL" in (r.get("assumption"), r.get("redundancy"), r.get("single_topic"), r.get("overgroup")) \
                and not r.get("rationale"):
            errs.append(f"{w}: FAIL에는 판단 근거 필요")
        if not r.get("rater_id"):
            errs.append(f"{w}: rater_id 없음")
    for r in lrows:
        w = f"L {r['blind_id']}#{r['question_no']} {r['trial_id']} {r['criterion_id']}"
        for f in ("preservation", "coverage", "group_validity"):
            need(r, w, f)
        codes = _codes(r.get("error_codes", ""))
        for c in codes:
            if c not in known:
                errs.append(f"{w}: 모르는 코드 {c}")
        if r.get("coverage") == "NONE":
            if r.get("preservation") != "NA":
                errs.append(f"{w}: coverage=NONE이면 preservation=NA")
            if "C1" not in codes:
                errs.append(f"{w}: coverage=NONE이면 C1 필요")
        elif r.get("preservation") == "NA":
            errs.append(f"{w}: 질문이 기준을 다루면 preservation은 NA일 수 없음")
        if r.get("preservation") == "FAIL" and not any(c.startswith("F") for c in codes):
            errs.append(f"{w}: 왜곡에는 F 코드 필요")
        if r.get("coverage") == "PARTIAL" and not {"C2", "C3", "G5"} & set(codes):
            errs.append(f"{w}: 부분 커버에는 C2·C3·G5 중 하나 필요")
        if r.get("preservation") != "FAIL" and any(c.startswith("F") for c in codes):
            errs.append(f"{w}: F 코드는 preservation=FAIL에만")
        multi = str(r.get("is_multi_link")) == "1"
        if multi and r.get("group_validity") == "NA":
            errs.append(f"{w}: 다기준 연결은 group_validity 필요")
        if not multi and r.get("group_validity") != "NA":
            errs.append(f"{w}: 단일 연결의 group_validity는 NA")
        if r.get("coverage") == "NONE" and multi and r.get("group_validity") != "INVALID":
            errs.append(f"{w}: 허위 연결은 group_validity=INVALID")
        if "UNSURE" in (r.get("preservation"), r.get("coverage"), r.get("group_validity")) and not r.get("unsure_reason"):
            errs.append(f"{w}: UNSURE에는 판단 불가 사유 필요")
        if (r.get("preservation") == "FAIL" or r.get("coverage") in ("NONE", "PARTIAL")
                or r.get("group_validity") == "INVALID") and not r.get("rationale"):
            errs.append(f"{w}: 판단 근거 필요")
        if not r.get("rater_id"):
            errs.append(f"{w}: rater_id 없음")
    return errs


def agreement(a: list[str], b: list[str]) -> dict:
    """두 평가자의 일치율과 Cohen's kappa. 기대 일치가 1이면 kappa는 정의 불가(None)."""
    n = len(a)
    if n == 0 or n != len(b):
        raise ValueError("평가 수가 다르거나 0")
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in ca) / (n * n)
    return {"n": n, "percent": po, "kappa": None if pe == 1 else (po - pe) / (1 - pe)}


def _key(row: dict, fields: tuple) -> str:
    return "|".join(str(row[f]) for f in fields)


def disagreements(sheet: str, r1: list[dict], r2: list[dict], fields: list[str], keys: tuple) -> tuple[list[dict], dict]:
    """같은 항목을 채점한 두 평가자 비교 → (조정 양식 행, 항목별 일치도)."""
    m1, m2 = {_key(r, keys): r for r in r1}, {_key(r, keys): r for r in r2}
    common = sorted(set(m1) & set(m2))
    rows, stats = [], {}
    for f in fields:
        stats[f] = agreement([m1[k][f] for k in common], [m2[k][f] for k in common])
        for k in common:
            if m1[k][f] != m2[k][f]:
                rows.append({"sheet": sheet, "item_key": k, "field": f, "rater1_id": m1[k].get("rater_id", ""),
                             "rater1_value": m1[k][f], "rater2_id": m2[k].get("rater_id", ""),
                             "rater2_value": m2[k][f], "final_value": "", "reason": "", "adjudicator_id": ""})
    return rows, stats


def lock(sealed: Path, files: list[Path]) -> dict:
    """채점 잠금: 파일 해시 기록. 이 기록이 없거나 파일이 바뀌면 unblind가 거부한다."""
    rec = {"files": {str(Path(f).name): sha_file(f) for f in files}}
    Path(sealed).mkdir(parents=True, exist_ok=True)
    (Path(sealed) / "lock.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rec


def unblind(sealed: Path, files: list[Path]) -> dict:
    """잠금 확인 후에만 조건 매핑을 돌려준다."""
    lock_file = Path(sealed) / "lock.json"
    if not lock_file.exists():
        raise PermissionError("잠금 전에는 조건을 공개할 수 없음")
    rec = json.loads(lock_file.read_text(encoding="utf-8"))["files"]
    now = {str(Path(f).name): sha_file(f) for f in files}
    if now != rec:
        raise PermissionError("잠금 후 채점 파일이 바뀜")
    return json.loads((Path(sealed) / "blind_map.json").read_text(encoding="utf-8"))["sets"]


def _ratio(num: int, den: int):
    return None if den == 0 else num / den


def set_metrics(qrows: list[dict], lrows: list[dict], final_ann: dict, clusters: dict) -> dict:
    """세트 1개의 M1~M6.

    final_ann: {(시험, 기준): {"askable", "tier", "h_strict", "h_any", "candidate"}}
    clusters: {cluster_id: {(시험, 기준), ...}}  공유정보 군집
    분모가 0이면 None (0으로 채우지 않음).
    """
    uv = {k for k, a in final_ann.items() if a["candidate"] and a["askable"] != "NOT_OBTAINABLE"}
    h = {k for k in uv if final_ann[k]["h_strict"]}
    h_any = {k for k in uv if final_ann[k]["h_any"]}
    pair = lambda r: (r["trial_id"], r["criterion_id"])  # noqa: E731
    linked = {pair(r) for r in lrows} & uv
    sub = {pair(r) for r in lrows if r["coverage"] in ("FULL", "PARTIAL")} & uv
    full = {pair(r) for r in lrows if r["coverage"] == "FULL"} & uv
    # 같은 기준이 여러 질문에 연결되면 FULL이 하나라도 있을 때만 완전 커버로 본다 (합쳐서 완전해지는 경우는 판정하지 않음)

    ev = [r for r in lrows if r["preservation"] in ("PASS", "FAIL")]
    fails = [r for r in ev if r["preservation"] == "FAIL"]
    ev_q = {(r["blind_id"], r["question_no"]) for r in ev}
    fail_q = {(r["blind_id"], r["question_no"]) for r in fails}
    unsure = sum(r["preservation"] == "UNSURE" for r in lrows)
    q_ev = [r for r in qrows if r["assumption"] in ("PASS", "FAIL")]
    multi = [r for r in lrows if str(r["is_multi_link"]) == "1"]
    multi_ev = [r for r in multi if r["group_validity"] in ("VALID", "INVALID")]
    kept = [r for r in multi if r["preservation"] != "UNSURE" and r["coverage"] != "UNSURE"]  # 허위 연결(NA·NONE)도 분모에 포함
    mq = [r for r in qrows if r["overgroup"] in ("PASS", "FAIL")]
    red = [r for r in qrows if r["redundancy"] in ("PASS", "FAIL")]
    topic = [r for r in qrows if r["single_topic"] in ("PASS", "FAIL")]

    in_top2 = {pair(r) for r in lrows if r["coverage"] in ("FULL", "PARTIAL") and int(r["question_no"]) <= 2} & h
    cl_cov = cl_one = 0
    for members in clusters.values():
        got = [r for r in lrows if pair(r) in members and r["coverage"] in ("FULL", "PARTIAL")]
        if len({pair(r) for r in got}) >= 2:
            cl_cov += 1
            cl_one += len({(r["question_no"]) for r in got}) == 1
    by_trial = Counter(k[0] for k in sub)
    return {
        "M1a": None if not ev else 1 - len(fails) / len(ev),
        "M1b": None if not ev_q else 1 - len(fail_q) / len(ev_q),
        "M1c": _ratio(sum(r["coverage"] == "PARTIAL" for r in ev), len(ev)),
        "M1_unsure_rate": _ratio(unsure, len(lrows)),
        "M2": _ratio(sum(r["assumption"] == "FAIL" for r in q_ev), len(q_ev)),
        "M3a": _ratio(len(linked), len(uv)), "M3b": _ratio(len(sub), len(uv)), "M3c": _ratio(len(full), len(uv)),
        "M3d": _ratio(len(sub), len(qrows)),
        "M4a": _ratio(len(sub & h), len(h)), "M4a_any": _ratio(len(sub & h_any), len(h_any)),
        "M4b": _ratio(len(in_top2), len(sub & h)), "M4c": dict(by_trial),
        "M5a": _ratio(sum(r["group_validity"] == "VALID" for r in multi_ev), len(multi_ev)),
        "M5b": _ratio(cl_one, cl_cov),
        "M5c": _ratio(sum(r["preservation"] == "PASS" and r["coverage"] == "FULL" for r in kept), len(kept)),
        "M6a": _ratio(sum(r["overgroup"] == "FAIL" for r in mq), len(mq)),
        "M6b": _ratio(sum(r["redundancy"] == "FAIL" for r in red), len(red)),
        "M6c": _ratio(sum(r["single_topic"] == "FAIL" for r in topic), len(topic)),
        "n_questions": len(qrows), "n_links": len(lrows), "covered_set": sorted(map(list, sub)),
    }


def stability(sets: list[list]) -> float | None:
    """M7a: 반복 간 실질 커버 기준 집합의 평균 쌍별 Jaccard. 양쪽 공집합인 쌍은 제외."""
    vals = []
    for a, b in combinations([{tuple(x) for x in s} for s in sets], 2):
        if a | b:
            vals.append(len(a & b) / len(a | b))
    return sum(vals) / len(vals) if vals else None


def verdict_flip_rate(reps: list[dict]) -> float | None:
    """M7b: 반복 간 최종 판정이 달라진 기준의 비율. reps: [{(시험, 기준): 판정}]."""
    keys = set().union(*reps) if reps else set()
    return _ratio(sum(len({r.get(k) for r in reps}) > 1 for k in keys), len(keys))


def m8_metrics(before: dict, after: dict, gold: dict) -> dict:
    """후속 판정 지표. 키는 (시험, 기준). 정답이 필요하므로 채점 잠금 후에만 호출한다.

    M8a는 질문 수로 나눈 M8c의 입력이다. unknown→post_enrollment는 해소로 세지 않고 따로 센다.
    """
    cand = {k for k, v in before.items() if v == "unknown"}
    ug = {k for k in cand if gold.get(k) in ("pass", "fail")}
    gu = {k for k in cand if gold.get(k) == "unknown"}
    non = {k for k in before if k not in cand and gold.get(k) == before[k]}
    right = {k for k in ug if after.get(k) == gold[k]}
    over = {k for k in gu if after.get(k) in ("pass", "fail")}
    reg = {k for k in non if after.get(k) != gold[k]}
    return {"M8a_n": len(right), "M8a": _ratio(len(right), len(ug)), "M8b_n": len(over), "M8b": _ratio(len(over), len(gu)),
            "M8d_n": len(reg), "M8d": _ratio(len(reg), len(non)),
            "to_post_enrollment": sum(after.get(k) == "post_enrollment" for k in cand),
            "fail_to_pass": sorted(k for k in before if gold.get(k) == "fail" and after.get(k) == "pass")}


def hangul_ratio(text: str) -> float:
    """D9: 한글 / (한글 + 라틴 문자)."""
    h = len(re.findall(r"[가-힣]", text))
    n = len(re.findall(r"[A-Za-z]", text))
    return 0.0 if h + n == 0 else h / (h + n)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("templates")
    p = sub.add_parser("preannotation")
    p.add_argument("patients", nargs="+")
    p = sub.add_parser("packet")
    p.add_argument("runs", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("sealed", type=Path)
    p.add_argument("--seed", type=int, required=True)
    p = sub.add_parser("validate")
    p.add_argument("question", type=Path)
    p.add_argument("link", type=Path)
    p = sub.add_parser("lock")
    p.add_argument("sealed", type=Path)
    p.add_argument("files", nargs="+", type=Path)
    args = ap.parse_args()
    if args.cmd == "templates":
        write_templates()
    elif args.cmd == "preannotation":
        for pid in args.patients:
            write_csv(HERE / "preannotation" / f"{pid}_preannotation.csv", PC, preannotation_rows(pid))
    elif args.cmd == "packet":
        build_packet(json.loads(args.runs.read_text(encoding="utf-8")), args.out, args.sealed, args.seed)
    elif args.cmd == "validate":
        errs = validate(read_csv(args.question), read_csv(args.link))
        print("\n".join(errs) or "통과")
        return 1 if errs else 0
    elif args.cmd == "lock":
        print(json.dumps(lock(args.sealed, args.files), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
