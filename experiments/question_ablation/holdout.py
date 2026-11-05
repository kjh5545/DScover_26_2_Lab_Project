"""확인 실험 후보(S002·S010·N001·N002)의 입력 준비 (API 호출 없음, 무료).

- 상세 시트는 작업 트리가 아니라 manifest에 적은 커밋·blob에서 읽는다. 전체 브랜치 병합 없이 필요한 파일·버전만 쓰고,
  blob이 다르면 실패한다. 작업 트리의 추적 파일을 바꾸지 않으므로 파일럿의 "실험 폴더 밖 변경" 검사에도 걸리지 않는다.
- 질문 생성 입력 묶음은 기존 scripts/eval_detailed.base_bundle을 그대로 쓴다 (S: 평가 세트 + v3 판정 캐시, N: handoff).
- **이 모듈의 출력에는 환자 설명, 판정값, 근거, 질문, 최종 판단 값을 넣지 않는다.** 개수와 일치 여부만 돌려준다.
- 확인 실험 데이터로 실제 질문을 생성하지 않는다. mock 점검만 한다.

  python experiments/question_ablation/holdout.py check            # 시트 버전·입력 묶음·ID 대조
  python experiments/question_ablation/holdout.py inputs           # 입력 형식 일관성·초기 판정 출처·누출 대조 (6명)
  python experiments/question_ablation/holdout.py mock-dry-run     # mock으로 질문·후속 판정 경로 점검 (임시 폴더)
"""

import argparse
import contextlib
import copy
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))

import run_pilot as rp  # noqa: E402
from eval_detailed import base_bundle  # noqa: E402
from src.agents.matcher import final_judgment  # noqa: E402

MANIFEST = HERE / "holdout_manifest.json"
GOLDSET_KEYS = ("id", "type", "text")
PILOT = ("S004", "S008")
CONFIRM = ("S002", "S010", "N001", "N002")
V3_CACHE = "data/processed/goldset_cache_v3_claude-sonnet-5-5"


class HoldoutError(RuntimeError):
    pass


def manifest(path: Path = MANIFEST) -> dict:
    return rp.read_json(path)


def sheet_text(pid: str, man: dict | None = None) -> str:
    """manifest의 커밋에서 시트를 읽고 blob을 대조한다. 작업 트리 파일은 쓰지 않는다."""
    man = man or manifest()
    entry = man["sheets"][pid]
    spec = f"{man['commit']}:{entry['path']}"
    blob = subprocess.run(["git", "rev-parse", spec], cwd=rp.ROOT, capture_output=True, text=True)
    if blob.returncode:
        raise HoldoutError(f"{pid}: {spec} 없음 (git fetch origin 필요)")
    if blob.stdout.strip() != entry["blob"]:
        raise HoldoutError(f"{pid}: blob 불일치 (manifest {entry['blob'][:12]}, 실제 {blob.stdout.strip()[:12]})")
    out = subprocess.run(["git", "cat-file", "blob", entry["blob"]], cwd=rp.ROOT, capture_output=True, check=True)
    return out.stdout.decode("utf-8")


def read_sheet(pid: str, man: dict | None = None) -> dict:
    """parse_sheet 결과 (상세 설명·정답 포함). 시뮬레이터와 잠금 후 정답 대조에서만 호출한다."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / f"{pid}_detailed_sheet.md"
        f.write_text(sheet_text(pid, man), encoding="utf-8")
        return rp.parse_sheet(f)


def load_bundle(pid: str, shape: str = "goldset") -> dict:
    """질문 생성 입력 묶음. 상세 설명·정답을 읽지 않는다.

    shape="goldset": 파일럿(S004·S008)의 make_bundle과 같은 입력 형식. 기준은 (id, type, text)만, 시험 제목은
      NCT 번호(입력에 제목이 붙지 않음), 시험별 최종 판단은 판정 목록에서 make_bundle과 같은 함수로 다시 계산한다.
    shape="service": handoff 그대로. N 환자는 needed_info가 질문 입력에 들어가고 시험 제목이 붙는다 (서비스 형식).
    어느 형식을 쓸지는 확인 실험 계획에서 정한다.
    """
    if shape not in ("goldset", "service"):
        raise ValueError(shape)
    bundle = copy.deepcopy(base_bundle(pid))
    bundle.pop("rounds", None)
    if shape == "goldset":
        bundle = {k: bundle[k] for k in ("patient_id", "case_text", "profile", "trials")}
        bundle["trials"] = [{"nct_id": t["nct_id"], "title": t["nct_id"],
                             "criteria": [{k: c[k] for k in GOLDSET_KEYS} for c in t["criteria"]],
                             "judgments": t["judgments"], "final_judgment": final_judgment(t["judgments"])}
                            for t in bundle["trials"]]
    return bundle


# ── 입력 형식·초기 판정 출처·누출 대조 (개수와 여부만) ──────────────

def input_format(pid: str, shape: str = "goldset") -> dict:
    """질문 생성 입력의 형식 요소. 조건과 무관한 입력이므로 환자 간 형식이 같아야 한다."""
    b = load_bundle(pid, shape)
    text = rp.qb.question_input(b, rp.qb.collect_materials(b), rp.MAX_QUESTIONS)
    heads = sorted({re.sub(r"\d+|NCT\d+.*", "#", l) for l in text.splitlines() if l.startswith("[")})
    return {"patient": pid, "shape": shape, "headers": heads,
            "trial_title_in_input": any(" · " in l for l in text.splitlines() if l.startswith("[시험")),
            "needed_info_in_input": "(필요한 정보:" in text,
            "criteria_keys": sorted({k for t in b["trials"] for c in t["criteria"] for k in c}),
            "final_judgment_recomputed_same": all(t["final_judgment"] == final_judgment(t["judgments"])
                                                  for t in base_bundle(pid)["trials"])}


def first_commit(path: str) -> str:
    out = subprocess.run(["git", "log", "--diff-filter=A", "--format=%h %ad", "--date=short", "--", path],
                         cwd=rp.ROOT, capture_output=True, text=True).stdout.split("\n")
    return [l for l in out if l][-1] if any(out) else "기록 없음"


def provenance(pid: str) -> dict:
    """초기 판정의 출처·버전·입력 범위. 판정값은 돌려주지 않는다."""
    b = base_bundle(pid)
    js = [j for t in b["trials"] for j in t["judgments"]]
    if pid.startswith("N"):
        src, meta = f"data/handoff/{pid}.json", b.get("meta", {})
        out = {"source": "handoff (src.pipeline.run_intake: 짧은 설명 → 프로필 → 판정 + 코드 규칙)",
               "file": src, "created": first_commit(src), "model": meta.get("model"),
               "judge_prompt": meta.get("prompt_version"), "stages": meta.get("stages")}
    else:
        files = sorted(str(p.relative_to(rp.ROOT)).replace("\\", "/") for p in (rp.ROOT / V3_CACHE).glob(f"match_{pid}_*.json"))
        out = {"source": "평가 세트 v3 판정 캐시 (scripts/eval_vs_goldset.py: 짧은 설명 + 프로필 → 판정, 코드 규칙은 채점 때만)",
               "file": files, "created": sorted({first_commit(f) for f in files}), "model": "claude-sonnet-5-5 (캐시 폴더명)",
               "judge_prompt": "v3", "stages": "4"}
    prof = f"data/processed/eval_cache/profile_{pid}.json"
    out.update(patient=pid, profile_file=prof, profile_created=first_commit(prof),
               judgments=len(js), code_checked=sum(j.get("checked_by") == "code" for j in js),
               code_changed_verdict=sum(j.get("checked_by") == "code" and j.get("llm_verdict") != j["verdict"] for j in js),
               validator_fixed=sum(j.get("checked_by") == "validator" for j in js))
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def leak_check(pid: str) -> dict:
    """프로필·초기 판정·질문 생성 입력에 상세 설명 조각이나 정답 근거 문장이 들어 있는지 센다 (내용은 돌려주지 않음)."""
    sheet = read_sheet(pid) if pid in CONFIRM else rp.load_sheet(pid)
    short = _norm(sheet["short_text"])
    det = [_norm(p) for p in re.split(r"(?<=[.?!다요])\s+|[;\n]", sheet["detailed_text"]) if len(_norm(p)) >= 14]
    det = [p for p in det if p not in short]
    ev = [_norm(r["evidence"]) for t in sheet["trials"] for r in t["rows"] if len(_norm(r["evidence"])) >= 14]
    ev = [e for e in ev if e not in short]
    found = {}
    for shape in ("goldset", "service"):
        b = load_bundle(pid, shape)
        text = _norm(json.dumps({"p": b["profile"], "j": [t["judgments"] for t in b["trials"]]}, ensure_ascii=False)
                     + rp.qb.question_input(b, rp.qb.collect_materials(b), rp.MAX_QUESTIONS))
        found[shape] = {"detailed_fragments": sum(p in text for p in det), "gold_evidence": sum(e in text for e in ev)}
    return {"patient": pid, "case_text_equals_sheet_short": _norm(base_bundle(pid)["case_text"]) == short,
            "detailed_fragments_checked": len(det), "gold_evidence_checked": len(ev), "found": found}


# ── 실험별 환자 설정 ────────────────────────────────────────────

CONFIRM_PINNED = [f for f in rp.PINNED_FILES if not f.startswith(("screening/", "data/processed/"))] + [
    "experiments/question_ablation/holdout_manifest.json", "data/handoff/N001.json", "data/handoff/N002.json",
    *[f"data/processed/eval_cache/profile_{p}.json" for p in CONFIRM],
    f"{V3_CACHE}/match_S002_NCT06068179.json", f"{V3_CACHE}/match_S002_NCT07018323.json",
    f"{V3_CACHE}/match_S010_NCT03714503.json", f"{V3_CACHE}/match_S010_NCT07081945.json"]


@contextlib.contextmanager
def use_cohort(name: str, shape: str = "goldset"):
    """실행기의 환자 설정을 이 프로세스 안에서만 확인 실험용으로 바꾼다. 파일럿 설정·잠금은 건드리지 않는다.

    확인 실험은 유료 실행 경로가 없다: paid_gate는 항상 차단한다 (계획 고정·manifest 고정 전).
    상세 시트는 manifest의 blob으로 읽고, 고정 대상에는 시트 대신 manifest를 넣는다.
    """
    if name == "pilot":
        yield
        return
    if name != "confirm":
        raise ValueError(name)
    man = manifest()
    loader = lambda p: load_bundle(p, shape)  # noqa: E731

    def blocked(*_a, **_k):
        raise rp.GateError(f"확인 실험 유료 실행 차단: 계획·manifest 고정 전 (manifest {man['status'][:5]})")

    expected_criteria = {p: sum(len(t["criteria"]) for t in loader(p)["trials"]) for p in CONFIRM}
    expected_cand = {p: len(rp.qb.collect_materials(loader(p))) for p in CONFIRM}
    with mock.patch.multiple(rp, PATIENTS=CONFIRM, EXPECTED_CRITERIA=expected_criteria,
                             EXPECTED_CANDIDATES=expected_cand, make_bundle=loader,
                             load_sheet=lambda p: read_sheet(p, man), PINNED_FILES=CONFIRM_PINNED,
                             LOCK=HERE / "confirm_lock.json",
                             ANNOTATION_RECORD=HERE / "evaluation" / "preannotation_confirm" / "annotation_record.json",
                             paid_gate=blocked):
        yield


def input_check(pid: str, man: dict | None = None) -> dict:
    """시트와 입력 묶음의 시험·기준 ID가 같은지, 초기 판정이 모든 기준에 있는지. 개수와 여부만 돌려준다."""
    sheet = read_sheet(pid, man)
    bundle = load_bundle(pid)
    s_ids = {(t["nct_id"], r["id"]) for t in sheet["trials"] for r in t["rows"]}
    b_ids = {(t["nct_id"], c["id"]) for t in bundle["trials"] for c in t["criteria"]}
    judged = {(t["nct_id"], j["criterion_id"]) for t in bundle["trials"] for j in t["judgments"]}
    return {"patient": pid, "sheet_blob_ok": True, "sheet_parse_problems": len(sheet["problems"]),
            "bundle_trials": len(bundle["trials"]), "bundle_criteria": len(b_ids),
            "ids_match_sheet": s_ids == b_ids, "initial_judgment_all": b_ids <= judged,
            "case_text": bool(bundle["case_text"]), "profile": bool(bundle["profile"]),
            "service_shape_extra_fields": sorted({k for t in base_bundle(pid)["trials"] for c in t["criteria"] for k in c}
                                                 - set(GOLDSET_KEYS))}


def mock_dry_run(out: Path, man: dict | None = None, shape: str = "goldset") -> dict:
    """mock 응답으로 질문 생성(5조건)과 후속 판정(핵심 조건) 경로를 점검한다. API를 부르지 않는다.

    실행기의 make_bundle·load_sheet를 이 프로세스 안에서만 바꿔 끼운다. 결과는 out(임시 폴더)에만 쓴다.
    """
    man = man or manifest()
    ws = rp.Workspace(out, mock=True)
    prompts = rp.load_prompts()
    result = {}
    with mock.patch.object(rp, "make_bundle", lambda p: load_bundle(p, shape)), \
            mock.patch.object(rp, "load_sheet", lambda p: read_sheet(p, man)):
        for pid in man["sheets"]:
            t = rp.MockTransport()
            q = Counter(rp.run_question({"run_key": rp.run_key(a, pid, 1), "arm": a, "patient_id": pid, "rep": 1,
                                         "downstream": a in rp.CORE_ARMS}, prompts, ws, t) for a in rp.ARMS)
            inputs_same = len({c["user"] for c in t.calls}) == 1
            d = Counter(rp.run_downstream({"run_key": rp.run_key(a, pid, 1), "arm": a, "patient_id": pid, "rep": 1,
                                           "downstream": True}, ws, rp.MockTransport()) for a in rp.CORE_ARMS)
            result[pid] = {"questions": dict(q), "question_inputs_identical_across_arms": inputs_same,
                           "downstream": dict(d)}
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("inputs")
    p = sub.add_parser("mock-dry-run")
    p.add_argument("--shape", choices=["goldset", "service"], default="goldset")
    args = ap.parse_args()
    man = manifest()
    try:
        if args.cmd == "check":
            print(json.dumps({"manifest_status": man["status"], "commit": man["commit"][:12],
                              "patients": [input_check(p, man) for p in man["sheets"]]}, ensure_ascii=False, indent=2))
        elif args.cmd == "inputs":
            pts = PILOT + CONFIRM
            print(json.dumps({"format": [input_format(p, s) for s in ("goldset", "service") for p in pts],
                              "provenance": [provenance(p) for p in pts],
                              "leak": [leak_check(p) for p in pts]}, ensure_ascii=False, indent=1))
        else:
            with tempfile.TemporaryDirectory() as tmp:
                print(json.dumps({"mock": True, "shape": args.shape, "saved": "임시 폴더 (종료 시 삭제)",
                                  "result": mock_dry_run(Path(tmp) / "holdout_mock", man, args.shape)},
                                 ensure_ascii=False, indent=2))
    except HoldoutError as e:
        print(f"[중단] {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
