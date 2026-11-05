"""질문 생성 ablation 파일럿 실행기.

기존 코드를 그대로 쓴다: 질문은 question_builder.write_questions·arrange, 후속 판정은 pipeline.next_round·
reassess·final_check, 답변은 patient_simulator.answer_questions, 정답 비교는 scoring.py. 공용 파일은 고치지 않고,
실행 중에만 세 모듈의 ask_json을 기록용 함수로 바꿔 끼운다 (토큰·stop_reason·원시 출력 저장, 형식 실패 재시도).
eval_detailed.run_loop는 기존 결과를 덮어쓰므로 쓰지 않는다.

무료:  freeze · check · plan · dry-run · estimate · packet · compare-raters · merge · lock-scores · sim-audit · report
유료:  questions · downstream  (사전 주석 잠금 + --paid <실험 ID> 없이는 시작하지 않음)
       smoke ping|questions|downstream  (연동 테스트, 분석 제외. ping은 실험 데이터 없음)

실행 방법: experiments/question_ablation/README.md
"""

import argparse
import contextlib
import csv
import difflib
import hashlib
import json
import os
import platform
import random
import re
import secrets
import shutil
import statistics
import subprocess
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(HERE / "evaluation"))

import scoring as sc  # noqa: E402

sc._load_project()  # 패키지가 없으면 호출 불가 스텁 (무료 명령·테스트용)

import src.agents.matcher as matcher  # noqa: E402
import src.llm as llm  # noqa: E402
import src.question_builder as qb  # noqa: E402
import src.testing.patient_simulator as simulator  # noqa: E402
from eval_detailed import gold_of  # noqa: E402
from src.pipeline import final_check, next_round, reassess  # noqa: E402
from src.testing.detailed_sheet import parse_sheet  # noqa: E402
from src.testing.goldset_bundle import make_bundle  # noqa: E402

CORE_ARMS = ("C0", "C_full", "A1", "A2")
ARMS = CORE_ARMS + ("A2s",)
PATIENTS = ("S004", "S008")
REPS = 3
MAX_QUESTIONS = 5
MAX_TOKENS = 16000
PLAN_SEED = 20261102                # 실행 순서 시드. 실행 전에 고정
EXPECTED_CANDIDATES = {"S004": 13, "S008": 23}
EXPECTED_CRITERIA = {"S004": 19, "S008": 27}
SHEET_DIR = ROOT / "screening" / "detailed" / "인선"
LOCK = HERE / "pilot_lock.json"
ANNOTATION_RECORD = HERE / "evaluation" / "preannotation" / "annotation_record.json"
REAL_ROOT = ROOT / "data" / "processed" / "question_ablation"
PINNED_FILES = [
    "src/question_builder.py", "src/llm.py", "src/pipeline.py", "src/agents/matcher.py", "src/tools/rule_checks.py",
    "src/testing/patient_simulator.py", "src/testing/goldset_bundle.py", "src/testing/detailed_sheet.py",
    "scripts/eval_detailed.py", "goldset/goldset_v1.json",
    "screening/detailed/인선/S004_detailed_sheet_filled.md", "screening/detailed/인선/S008_detailed_sheet_filled.md",
    "data/processed/eval_cache/profile_S004.json", "data/processed/eval_cache/profile_S008.json",
    "data/processed/goldset_cache_v3_claude-sonnet-5-5/match_S004_NCT04369560.json",
    "data/processed/goldset_cache_v3_claude-sonnet-5-5/match_S004_NCT05646485.json",
    "data/processed/goldset_cache_v3_claude-sonnet-5-5/match_S008_NCT07299695.json",
    "data/processed/goldset_cache_v3_claude-sonnet-5-5/match_S008_NCT07652658.json",
]
MAX_API_ERROR_STREAK = 3
NOT_ASKED_REASONS = {"질문 수 제한으로 보류", "검사·기록 또는 의료진의 추가 확인 필요"}


try:
    import anthropic
    API_ERRORS = (ConnectionError, TimeoutError, anthropic.APIError)
except (ImportError, AttributeError):
    API_ERRORS = (ConnectionError, TimeoutError)


class GateError(RuntimeError):
    """유료 실행 차단 또는 무결성 검사 실패."""


class FormatFailure(ValueError):
    """형식 실패. 이것만 1회 재시도한다."""


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_new(path: Path, obj) -> None:
    """새 파일만 만든다. 있으면 FileExistsError (덮어쓰기 금지)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    with open(path, "x", encoding="utf-8", newline="") as f:
        f.write(text)


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ── 버전 고정 ──────────────────────────────────────────────

def blob(path: str) -> str:
    return subprocess.run(["git", "hash-object", path], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout.strip()


def load_prompts() -> dict[str, str]:
    """manifest의 SHA-256과 다르면 실패."""
    manifest = read_json(HERE / "prompts" / "manifest.json")
    prompts = {}
    for arm in ARMS:
        info = manifest["conditions"][arm]
        raw = (HERE / "prompts" / info["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != info["sha256"]:
            raise GateError(f"프롬프트 해시 불일치: {arm}")
        prompts[arm] = raw.decode("utf-8")
    return prompts


def user_messages() -> dict[str, str]:
    """환자별 질문 생성 입력. 조건과 무관하며 상세 설명·정답을 읽지 않는다."""
    out = {}
    for pid in PATIENTS:
        bundle = make_bundle(pid)
        out[pid] = qb.question_input(bundle, qb.collect_materials(bundle), MAX_QUESTIONS)
    return out


def compute_versions() -> dict:
    params = llm._params("S", "U", MAX_TOKENS)
    return {
        "model_id": params["model"], "max_tokens": params["max_tokens"], "thinking": params["thinking"],
        "extra_params": sorted(set(params) - {"model", "max_tokens", "thinking", "system", "messages"}),
        "max_questions": MAX_QUESTIONS, "plan_seed": PLAN_SEED,
        "prompt_sha256": {a: sha(p) for a, p in load_prompts().items()},
        "judge_prompt_sha256": sha(matcher.SYSTEM_PROMPT), "judge_answers_header_sha256": sha(matcher.ANSWERS_HEADER),
        "simulator_prompt_sha256": sha(simulator.SYSTEM_PROMPT),
        "input_sha256": {p: sha(m) for p, m in user_messages().items()},
        "file_blobs": {f: blob(f) for f in PINNED_FILES},
    }


def runtime_info() -> dict:
    try:
        import anthropic
        sdk = getattr(anthropic, "__version__", "stub")
    except ImportError:
        sdk = "none"
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"python": platform.python_version(), "anthropic_sdk": sdk, "git_head": head}


def tracked_changes() -> list[str]:
    """실험 폴더 밖의 변경 (추적 파일 수정, 새 파일)."""
    out = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8").stdout.splitlines()
    return [l for l in out if "experiments/question_ablation" not in l and "data/processed/question_ablation" not in l]


def verify_versions() -> dict:
    """pilot_lock.json과 현재 상태 비교. 모델·프롬프트·판정기·시뮬레이터·데이터가 바뀌면 실패."""
    if not LOCK.exists():
        raise GateError("pilot_lock.json 없음. 먼저 freeze")
    pinned, now = read_json(LOCK)["versions"], compute_versions()
    diff = [k for k in pinned if pinned[k] != now.get(k)]
    if diff:
        details = [f for f, v in pinned["file_blobs"].items() if now["file_blobs"].get(f) != v]
        raise GateError(f"고정 값 변경 감지: {diff} {details}")
    return now


# ── 사전 주석 잠금 (유료 실행 조건) ─────────────────────────

def annotation_gate(record_path: Path | None = None) -> dict:
    """사전 주석 조건을 검사한다. 미충족이면 GateError (무료 dry-run에는 적용하지 않음)."""
    record_path = record_path or ANNOTATION_RECORD
    if not record_path.exists():
        raise GateError("사전 주석 기록 없음")
    rec = read_json(record_path)
    problems = []
    if not rec.get("m4a_definition_review", {}).get("approved"):
        problems.append("M4a 고영향 정의 검토 미완료")
    if not rec.get("judge_freeze_confirmed_by"):
        problems.append("판정기 변경 예정 확인 미완료")
    people = rec.get("people", [])
    if not people or any(p.get("gold_exposed") not in ("none", "partial", "full") for p in people):
        problems.append("담당자·정답 노출 기록 미완료")
    base = record_path.parent
    for rel, digest in rec.get("files", {}).items():
        f = base / rel
        if not f.exists() or sc.sha_file(f) != digest:
            problems.append(f"잠긴 파일 변경 또는 없음: {rel}")
    for name in annotation_files():
        if name not in rec.get("files", {}):
            problems.append(f"잠금 목록에 없음: {name}")
    if not problems:
        problems += evidence_problems(base / "safety_evidence.csv")
        ids = evidence_ids(base / "safety_evidence.csv")
        for pid in PATIENTS:
            problems += check_annotation_population(pid, sc.read_csv(base / f"{pid}_final.csv"), ids)
        problems += ai_source_problems(rec, base)
    if problems:
        raise GateError("; ".join(problems))
    return rec


def lock_annotation(draft: Path, record_path: Path | None = None) -> dict:
    """담당자·검토 기록(draft)에 주석 파일 해시를 더해 잠근다. 조건을 못 채우면 잠기지 않는다."""
    record_path = record_path or ANNOTATION_RECORD
    rec = read_json(draft)
    names = annotation_files()
    missing = [n for n in names if not (record_path.parent / n).exists()]
    if missing:
        raise GateError(f"주석 파일 없음: {missing}")
    rec["files"] = {n: sc.sha_file(record_path.parent / n) for n in names}
    rec["locked_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if record_path.exists():
        raise FileExistsError(record_path)
    trial = record_path.with_suffix(".trial.json")
    trial.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    try:
        annotation_gate(trial)
    finally:
        trial.unlink()
    write_new(record_path, rec)
    return rec


AI_MODE = "ai_unverified"
AI_LABEL = "AI 주석 버전 고정"
AI_PATIENTS = ("S004", "S008")      # 확인 실험 설정(use_cohort)이 바꾸지 않는 상수
AI_PROVENANCE = ("drafting_tool", "drafting_model", "drafting_inputs", "drafted_at")


def ai_source_problems(rec: dict, base: Path) -> list[str]:
    """파일럿 전용 미검증 AI 사전 주석 (annotation_workflow.md 6절). 사람 주석 기록이면 검사하지 않는다.

    AI 주석 경로를 허용하되 조용히 통과시키지 않는다: 파일럿 환자만, 사람 검토 없음 명시, 작성 이력(모르면 "미확인"),
    AI 원본 해시, 확정표가 AI 원본에서 조정 없이 옮겨졌는지 (h_any = h_strict, 표시 문구).
    """
    src = rec.get("annotation_source", {})
    if src.get("mode") != AI_MODE:
        return []
    if set(PATIENTS) - set(AI_PATIENTS):
        return [f"AI 주석 경로는 파일럿 환자 {AI_PATIENTS}에만 쓸 수 있음"]
    out = []
    if src.get("status") != AI_LABEL:
        out.append(f"AI 주석 상태는 '{AI_LABEL}'로 기록")
    if src.get("human_item_review") is not False:
        out.append("사람 항목별 검토 여부(human_item_review)를 false로 명시")
    out += [f"AI 작성 이력 {k} 없음 (모르면 '미확인')" for k in AI_PROVENANCE if not str(src.get(k, "")).strip()]
    files = src.get("source_files", {})
    if sorted(files) != sorted(f"ai_draft/source/{p}_preannotation_AI_draft.csv" for p in PATIENTS):
        out.append("AI 원본 파일 목록이 환자와 다름")
    for rel, digest in files.items():
        if not (base / rel).exists() or sc.sha_file(base / rel) != digest:
            out.append(f"AI 원본 변경 또는 없음: {rel}")
    norm = lambda s: " ".join(str(s).split())  # noqa: E731
    pairs = [("askable", "final_askable"), ("centrality", "final_centrality"),
             ("centrality_evidence", "final_centrality_evidence"), ("core_part", "final_core_part"),
             ("core_info", "final_core_info")]
    for pid in PATIENTS:
        rows = sc.read_csv(base / f"{pid}_final.csv")
        source = base / "ai_draft" / "source" / f"{pid}_preannotation_AI_draft.csv"
        ai = {(r["trial_id"], r["criterion_id"]): r for r in (sc.read_csv(source) if source.exists() else [])
              if r["is_candidate"] == "1"}
        if any(r["h_any"] != r["h_strict"] or not r["adjudication_note"].startswith(AI_LABEL) for r in rows):
            out.append(f"{pid}: 확정표가 AI 주석에서 조정 없이 옮겨진 형태가 아님")
        changed = [f"{r['trial_id']} {r['criterion_id']}" for r in rows
                   if (r["trial_id"], r["criterion_id"]) not in ai
                   or any(norm(ai[(r["trial_id"], r["criterion_id"])][a]) != norm(r[b]) for a, b in pairs)]
        if changed:
            out.append(f"{pid}: 확정표 값이 AI 원본과 다름 {changed[:3]} (수정은 수정 이력과 함께 별도 버전으로)")
    return out


def annotation_files() -> list[str]:
    """잠금 대상. 안전 조건 근거 목록은 비어 있어도(머리글만) 함께 잠근다."""
    return [f"{p}_{kind}.csv" for p in PATIENTS for kind in ("final", "clusters")] + ["safety_evidence.csv"]


def evidence_ids(path: Path) -> set | None:
    """인용할 수 있는 근거 ID: 모든 열이 채워지고 review_status가 "고정"인 행."""
    if not path.exists():
        return None
    rows = sc.read_csv(path)
    return {r["evidence_id"] for r in rows if all(r.get(c, "").strip() for c in sc.SCHEMA["safety_evidence_columns"])
            and r["review_status"] == "고정" and re.fullmatch(r"EV[\w-]+", r["evidence_id"])}


def evidence_problems(path: Path) -> list[str]:
    """잠금 시 근거 목록에 검토 대기 행이 남아 있으면 안 된다 (고정 또는 제외만)."""
    rows = sc.read_csv(path) if path.exists() else []
    if rows and list(rows[0]) != sc.SCHEMA["safety_evidence_columns"]:
        return ["safety_evidence.csv 열이 양식과 다름"]
    pending = [r["evidence_id"] for r in rows if r.get("review_status") not in ("고정", "제외")]
    return [f"근거 목록 검토 대기 {len(pending)}건"] if pending else []


def check_annotation_population(pid: str, rows: list[dict], evidence: set | None = None) -> list[str]:
    """확정 주석의 모집단이 질문 후보(U)와 정확히 같은지, 계산 열이 확정 점수와 맞는지.

    evidence: 고정된 근거 목록 ID. None이면 근거 ID 대조를 건너뛴다.
    H가 0개여도 거부하지 않는다 (M5-B: M4a는 값 없음으로 두고 n_H를 보고).
    """
    bundle = make_bundle(pid)
    cand = {(m["trial"], m["criterion_id"]) for m in qb.collect_materials(bundle)}
    got = {(r["trial_id"], r["criterion_id"]) for r in rows}
    out = []
    if got != cand:
        out.append(f"{pid}: 주석 모집단이 후보와 다름 (빠짐 {len(cand - got)}, 초과 {len(got - cand)})")
    missing = [c for c in sc.SCHEMA["preannotation_final_columns"] if rows and c not in rows[0]]
    if missing:
        out.append(f"{pid}: 확정표 열 없음 {missing}")
        return out
    if any(r.get("final_askable") not in sc.SCHEMA["values"]["askable"][:3] for r in rows):
        out.append(f"{pid}: final_askable 미확정")
    if any((str(r["h_strict"]).lower() == "true") != sc.is_core(r["final_centrality"]) for r in rows):
        out.append(f"{pid}: h_strict가 확정 핵심성과 맞지 않음")
    for r in rows:
        key = f"{pid} {r['trial_id']} {r['criterion_id']}"
        core, info = r["final_core_part"].strip(), r["final_core_info"].strip()
        if r["final_centrality"] == "2":
            if not r["final_centrality_evidence"].strip():
                out.append(f"{key}: 핵심성 2점의 근거 없음")
            if not core or not info:
                out.append(f"{key}: 핵심성 2점 기준은 핵심 부분(또는 '{sc.WHOLE}')과 필요한 정보가 필요")
        elif core or info:
            out.append(f"{key}: 핵심 부분은 핵심성 2점 기준에만 적는다")
        cited = set(re.findall(r"\bEV[\w-]+", r["final_centrality_evidence"]))
        if evidence is not None and cited - evidence:
            out.append(f"{key}: 근거 목록에 없거나 고정되지 않은 근거 {sorted(cited - evidence)}")
    return out


def denominators() -> dict:
    """36개 후보와 46개 전체 기준의 관계. 정답은 집계 수치에만 쓴다."""
    out = {}
    for pid in PATIENTS:
        bundle = make_bundle(pid)
        mats = qb.collect_materials(bundle)
        cand = {(m["trial"], m["criterion_id"]) for m in mats}
        all_c = {(t["nct_id"], c["id"]) for t in bundle["trials"] for c in t["criteria"]}
        gold = {k: v["verdict"] for k, v in gold_of(load_sheet(pid)).items()}
        non = all_c - cand
        out[pid] = {"criteria": len(all_c), "candidates_U": len(cand), "non_candidates": len(non),
                    "subset": cand <= all_c, "gold_keys_match": set(gold) == all_c,
                    "M8a_denominator": sum(gold[k] in ("pass", "fail") for k in cand),
                    "M8b_denominator": sum(gold[k] == "unknown" for k in cand),
                    "M8d_denominator": len(non)}
        if len(cand) != EXPECTED_CANDIDATES[pid] or len(all_c) != EXPECTED_CRITERIA[pid] or not cand <= all_c:
            raise GateError(f"{pid}: 평가 모집단이 설계와 다름 {out[pid]}")
    return out


def load_sheet(pid: str) -> dict:
    """상세 설명과 정답이 들어 있는 시트. 후속 판정·정답 대조에서만 호출한다."""
    return parse_sheet(SHEET_DIR / f"{pid}_detailed_sheet_filled.md")


# ── 실행 계획 ──────────────────────────────────────────────

def run_key(arm: str, pid: str, rep: int) -> str:
    return f"{arm}__{pid}__r{rep}"


def make_plan(seed: int = PLAN_SEED) -> list[dict]:
    """회차 블록 안에서 무작위화. 같은 시드면 같은 순서."""
    rng = random.Random(seed)
    plan = []
    for rep in range(1, REPS + 1):
        block = [(a, p) for a in ARMS for p in PATIENTS]
        rng.shuffle(block)
        for arm, pid in block:
            plan.append({"run_key": run_key(arm, pid, rep), "arm": arm, "patient_id": pid, "rep": rep,
                         "downstream": arm in CORE_ARMS})
    return plan


def plan_hash(plan: list[dict]) -> str:
    return sha(json.dumps(plan, ensure_ascii=False, sort_keys=True))


class Workspace:
    """실험 1건의 저장 경로. mock과 실제 결과를 섞지 않는다."""

    def __init__(self, root: Path, mock: bool):
        self.root, self.mock = Path(root), mock
        self.questions, self.attempts = self.root / "questions", self.root / "attempts"
        self.answers, self.downstream = self.root / "answers", self.root / "downstream"
        self.packet, self.sealed = self.root / "rater_packet", self.root / "sealed"
        self.scores = self.root / "scores"
        self.errors = self.root / "errors.jsonl"
        self.bundle, self.seal_record = self.root / "sealed_bundle.zip", self.root / "seal_record.json"

    @classmethod
    def existing(cls, root: Path) -> "Workspace":
        return cls(root, mock=read_json(Path(root) / "experiment.json")["mock"])

    def prepare(self, plan: list[dict], versions: dict) -> None:
        info = self.root / "experiment.json"
        if info.exists():
            old = read_json(info)
            if old["mock"] != self.mock:
                raise GateError("mock 결과와 실제 결과를 같은 폴더에 섞을 수 없음")
            if old["plan_sha256"] != plan_hash(plan):
                raise GateError("저장된 실행 계획과 다름")
            if old["versions"] != versions:
                raise GateError("저장된 버전 기록과 다름")
            return
        write_new(self.root / ".gitignore", "# 조건 매핑은 채점 잠금 전에 공유하지 않는다\nsealed/\n")
        write_new(self.root / "run_manifest.json", {"seed": PLAN_SEED, "sha256": plan_hash(plan), "runs": plan})
        write_new(info, {"mock": self.mock, "plan_sha256": plan_hash(plan), "versions": versions,
                         "runtime": runtime_info(), "created": time.strftime("%Y-%m-%dT%H:%M:%S")})

    def log_error(self, run: str, stage: str, kind: str, detail: str) -> None:
        self.errors.parent.mkdir(parents=True, exist_ok=True)
        with open(self.errors, "a", encoding="utf-8") as f:
            f.write(json.dumps({"run_key": run, "stage": stage, "kind": kind, "detail": detail[:500],
                                "time": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False) + "\n")


# ── LLM 호출 ───────────────────────────────────────────────

class RealTransport:
    """실제 API. src.llm._params로 파이프라인과 같은 요청을 만든다.

    fallbacks는 넣지 않는다: 거부 시 다른 모델로 넘어가면 모델 고정이 깨진다. refusal은 그대로 기록한다.
    SDK 자동 재시도는 끈다 (max_retries=0, 2026-11-05 결정). 재시도는 실행기가 예산 검사(BudgetTransport) 안에서 한다:
    API 오류 실행은 결과를 남기지 않으므로 같은 명령을 다시 실행하면 그 실행만 다시 시도한다.
    """

    def __init__(self, client=None):
        self.client = (client or llm.get_client()).with_options(max_retries=0)

    def __call__(self, system: str, user: str) -> dict:
        start = time.monotonic()
        response = self.client.messages.create(**llm._params(system, user, MAX_TOKENS))
        usage = response.usage
        return {"text": next((b.text for b in response.content if b.type == "text"), ""),
                "stop_reason": response.stop_reason, "model": response.model,
                "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                "request_id": getattr(response, "_request_id", None), "elapsed": time.monotonic() - start}


class MockTransport:
    """API를 부르지 않는 가짜 응답. faults: {호출 번호: 'bad_json'|'truncate'|'schema'|'api_error'|'refusal'|'short'|'swap'}."""

    def __init__(self, faults: dict | None = None):
        self.faults, self.calls = dict(faults or {}), []

    def __call__(self, system: str, user: str) -> dict:
        n = len(self.calls) + 1
        self.calls.append({"system": system, "user": user})
        fault = self.faults.get(n)
        if fault == "api_error":
            raise ConnectionError("mock API 오류")
        stop = {"truncate": "max_tokens", "refusal": "refusal"}.get(fault, "end_turn")
        if fault in ("bad_json", "truncate"):
            text = '{"questions": ['
        elif fault == "schema":
            text = '{"questions": "없음"}'
        elif "role-playing a PATIENT" in system:
            text = self._answers(user, fault)
        elif "eligibility matching" in system:
            text = self._judge(user)
        else:
            text = self._questions(user)
        return {"text": text, "stop_reason": stop, "model": "mock", "input_tokens": len(system + user) // 3,
                "output_tokens": len(text) // 3, "request_id": f"mock-{n}", "elapsed": 0.0}

    @staticmethod
    def _questions(user: str) -> str:
        """후보마다 질문 1개 + 무효 기준·중복 질문을 섞어 arrange 경로를 지나게 한다."""
        links, trial = [], None
        for line in user.splitlines():
            m = re.match(r"\[시험 \d+: (NCT\d+)", line)
            if m:
                trial = m.group(1)
            m = re.match(r"([IE]\d+)\. ", line)
            if m and trial:
                links.append((trial, m.group(1)))
        qs = [{"question": f"(MOCK) {t} {c} 기준에 대해 알려 주세요.", "needed_info": "mock",
               "resolves": [{"trial": t, "criteria": [c]}]} for t, c in links[:7]]
        if qs:
            qs.insert(1, dict(qs[0], question="(MOCK) 중복 질문입니다."))
            qs.insert(2, {"question": "(MOCK) 없는 기준입니다.", "needed_info": "mock",
                          "resolves": [{"trial": "NCT00000000", "criteria": ["I1"]}]})
        not_asked = [{"trial": t, "criterion_id": c, "reason": "질문 수 제한으로 보류"} for t, c in links[7:]]
        return json.dumps({"questions": qs, "not_asked": not_asked}, ensure_ascii=False)

    @staticmethod
    def _answers(user: str, fault: str | None) -> str:
        qs = json.loads(user[user.index("QUESTIONS:\n") + len("QUESTIONS:\n"):])
        ans = [{"question": q, "answer": "(MOCK) 잘 모르겠어요."} for q in qs]
        if fault == "short":
            ans = ans[:-1]
        if fault == "swap" and len(ans) > 1:
            ans[0], ans[1] = ans[1], ans[0]
        return json.dumps(ans, ensure_ascii=False)

    @staticmethod
    def _judge(user: str) -> str:
        crit = json.loads(user[user.index("ELIGIBILITY CRITERIA:\n") + len("ELIGIBILITY CRITERIA:\n"):])
        return json.dumps([{"criterion_id": c["id"], "verdict": "unknown", "evidence": "mock", "sub_condition_notes": []}
                           for c in crit], ensure_ascii=False)


def validate_question_output(obj) -> None:
    if not isinstance(obj, dict) or not isinstance(obj.get("questions"), list) or not isinstance(obj.get("not_asked"), list):
        raise FormatFailure("questions·not_asked 배열이 없음")
    for q in obj["questions"]:
        if not isinstance(q, dict) or not isinstance(q.get("question"), str) or "needed_info" not in q \
                or not isinstance(q.get("resolves"), list):
            raise FormatFailure("질문 항목 형식 오류")


def validate_judgments(obj) -> None:
    if not isinstance(matcher.validate_shape(obj), list) or not matcher.validate_shape(obj):
        raise FormatFailure("판정 배열이 없음")


def check_answers(questions: list[str], answers) -> None:
    """시뮬레이터 답변의 개수·순서 검사. run_loop의 zip은 길이가 달라도 조용히 잘린다."""
    if not isinstance(answers, list) or len(answers) != len(questions):
        raise FormatFailure(f"답변 개수 불일치: 질문 {len(questions)}, 답변 {len(answers) if isinstance(answers, list) else '형식 오류'}")
    norm = lambda s: " ".join(str(s).split())  # noqa: E731
    for i, a in enumerate(answers):
        if not isinstance(a, dict) or not str(a.get("answer", "")).strip():
            raise FormatFailure(f"{i + 1}번 답변 없음")
        scores = [difflib.SequenceMatcher(None, norm(a.get("question", "")), norm(q)).ratio() for q in questions]
        if max(range(len(scores)), key=scores.__getitem__) != i:
            raise FormatFailure(f"{i + 1}번 답변의 질문 순서 불일치")


class Recorder:
    """ask_json 대체 함수. 원시 응답을 모두 저장하고, 형식 실패만 1회 재시도한다."""

    def __init__(self, ws: Workspace, transport, run: str):
        self.ws, self.transport, self.run = ws, transport, run
        self.stage, self.validator, self.calls = "", None, []

    def _save(self, record: dict) -> None:
        n = 1
        while True:
            path = self.ws.attempts / f"{self.run}__{self.stage}__{n:03d}.json"
            try:
                write_new(path, record)
                return
            except FileExistsError:
                n += 1

    def _prior_failures(self) -> int:
        if self.stage not in ("question", "simulator"):
            return 0
        files = self.ws.attempts.glob(f"{self.run}__{self.stage}__*.json")
        return sum(read_json(f)["format_error"] is not None for f in files)

    def __call__(self, system: str, user: str, max_tokens: int = MAX_TOKENS):
        if max_tokens != MAX_TOKENS:
            raise GateError("max_tokens 변경 감지")
        attempt = self._prior_failures()  # 중단 후 재개해도 재시도 한도를 넘지 않게
        while True:
            if attempt >= 2:
                raise FormatExhausted("형식 실패 2회")
            attempt += 1
            reply = self.transport(system, user)
            price = llm.PRICE.get(reply["model"], (0.0, 0.0))
            cost = (reply["input_tokens"] * price[0] + reply["output_tokens"] * price[1]) / 1e6
            rec = {**reply, "run_key": self.run, "stage": self.stage, "attempt": attempt, "cost_usd": cost,
                   "system_sha256": sha(system), "user_sha256": sha(user), "format_error": None}
            self.calls.append({k: rec[k] for k in ("stage", "attempt", "stop_reason", "input_tokens", "output_tokens",
                                                   "cost_usd", "elapsed", "model")})
            try:
                if reply["stop_reason"] == "refusal":
                    self._save(rec)
                    raise RefusalStop("모델이 거부함")
                if reply["stop_reason"] == "max_tokens":
                    raise FormatFailure("max_tokens에서 잘림")
                try:
                    obj = llm.parse_json(reply["text"])
                except json.JSONDecodeError as e:
                    raise FormatFailure(f"JSON 파싱 실패: {e}")
                if self.validator:
                    self.validator(obj)
                self._save(rec)
                return obj
            except FormatFailure as e:
                rec["format_error"] = str(e)
                self._save(rec)
                self.ws.log_error(self.run, self.stage, "format", str(e))


class RefusalStop(RuntimeError):
    pass


class FormatExhausted(RuntimeError):
    pass


@contextlib.contextmanager
def recording(recorder: Recorder):
    """이 프로세스 안에서만 세 모듈의 ask_json을 바꾼다. 파일은 수정하지 않는다."""
    saved = qb.ask_json, simulator.ask_json, matcher.ask_json
    qb.ask_json = simulator.ask_json = matcher.ask_json = recorder
    try:
        yield recorder
    finally:
        qb.ask_json, simulator.ask_json, matcher.ask_json = saved


# ── 질문 생성 ──────────────────────────────────────────────

def arrange_report(raw: list[dict], materials: list[dict], final: list[dict]) -> list[dict]:
    """arrange가 무엇을 왜 뺐는지 재구성한다. 결과가 실제 arrange와 다르면 실패."""
    valid = {(m["trial"], m["criterion_id"]) for m in materials}
    report, covered, kept = [], set(), 0
    for i, q in enumerate(raw, 1):
        links = {(r.get("trial"), c) for r in q.get("resolves") or [] if isinstance(r, dict) for c in r.get("criteria") or []}
        good = links & valid
        row = {"raw_no": i, "text": q.get("text", ""), "invalid_links": sorted(map(list, links - valid))}
        if not str(q.get("text", "")).strip():
            row["status"] = "removed_empty_text"
        elif not good:
            row["status"] = "removed_no_valid_criterion"
        elif good <= covered:
            row["status"] = "removed_duplicate_criteria"
        elif kept >= MAX_QUESTIONS:
            row["status"] = "removed_over_budget"
        else:
            row["status"] = "kept"
            kept += 1
            covered |= good
        report.append(row)
    if [r["text"].strip() for r in report if r["status"] == "kept"] != [q["text"] for q in final]:
        raise GateError("arrange 결과 재구성 불일치")
    return report


def not_asked_report(not_asked, materials: list[dict], final: list[dict]) -> dict:
    """D6 진단. 성과로 비교하지 않는다."""
    cand = {(m["trial"], m["criterion_id"]) for m in materials}
    linked = {(r["trial"], c) for q in final for r in q["resolves"] for c in r["criteria"]}
    items = [x for x in not_asked if isinstance(x, dict)] if isinstance(not_asked, list) else []
    listed = {(x.get("trial"), x.get("criterion_id")) for x in items}
    return {"missing": len(cand - linked - listed), "contradiction": len(linked & listed),
            "unknown_criterion": len(listed - cand),
            "invalid_reason": sum(x.get("reason") not in NOT_ASKED_REASONS for x in items)}


def run_question(entry: dict, prompts: dict, ws: Workspace, transport) -> str:
    """질문 생성 1건. 이 함수는 상세 설명·정답을 읽지 않는다."""
    run = entry["run_key"]
    out = ws.questions / f"{run}.json"
    if out.exists():
        return "skipped"
    bundle = make_bundle(entry["patient_id"])
    materials = qb.collect_materials(bundle)
    rec = Recorder(ws, transport, run)
    rec.stage, rec.validator = "question", validate_question_output
    base = {**entry, "mock": ws.mock, "prompt_sha256": sha(prompts[entry["arm"]]),
            "input_sha256": sha(qb.question_input(bundle, materials, MAX_QUESTIONS))}
    try:
        with recording(rec):
            raw, not_asked, _ = qb.write_questions(bundle, materials, MAX_QUESTIONS, prompts[entry["arm"]])
    except (FormatExhausted, RefusalStop) as e:
        status = "failed_format" if isinstance(e, FormatExhausted) else "refused"
        ws.log_error(run, "question", status, str(e))
        write_new(out, {**base, "status": status, "error": str(e), "calls": rec.calls})
        return status
    final = qb.arrange(raw, materials, MAX_QUESTIONS)
    criteria = {f"{t['nct_id']}|{c['id']}": {"text": c["text"], "type": c.get("type", "")}
                for t in bundle["trials"] for c in t["criteria"]}
    write_new(out, {**base, "status": "ok", "raw_questions": raw, "final_questions": final,
                    "arrange_report": arrange_report(raw, materials, final), "not_asked": not_asked,
                    "not_asked_report": not_asked_report(not_asked, materials, final), "criteria": criteria,
                    "d9_hangul_ratio": [round(sc.hangul_ratio(q["text"]), 4) for q in final],
                    "d9_below_heuristic": sum(sc.hangul_ratio(q["text"]) < sc.HANGUL_MIN for q in final),
                    "calls": rec.calls})
    return "ok"


def snapshot(bundle: dict) -> dict:
    return {f"{t['nct_id']}|{j['criterion_id']}": j["verdict"] for t in bundle["trials"] for j in t["judgments"]}


def run_downstream(entry: dict, ws: Workspace, transport) -> str:
    """핵심 조건의 시뮬레이터 → reassess → final_check. 저장된 질문을 다시 만들지 않는다."""
    run = entry["run_key"]
    if entry["arm"] not in CORE_ARMS:
        raise GateError("A2s는 후속 판정을 실행하지 않음")
    out = ws.downstream / f"{run}.json"
    if out.exists():
        return "skipped"
    q_file = ws.questions / f"{run}.json"
    if not q_file.exists() or read_json(q_file)["status"] != "ok":
        ws.log_error(run, "downstream", "no_questions", "질문 결과 없음")
        return "no_questions"
    final = read_json(q_file)["final_questions"]
    bundle = make_bundle(entry["patient_id"])
    bundle.pop("rounds", None)
    before = snapshot(bundle)
    rec = Recorder(ws, transport, run)
    fact = load_sheet(entry["patient_id"])["detailed_text"]   # 시뮬레이터 전용 경로. 저장 파일에는 넣지 않는다
    try:
        with recording(rec):
            questions = next_round(bundle, build_questions=lambda b, max_questions: final, max_questions=MAX_QUESTIONS)
            texts = [q["text"] for q in questions]
            ans_file = ws.answers / f"{run}.json"
            if ans_file.exists():
                answers = read_json(ans_file)["answers"]
            else:
                rec.stage, rec.validator = "simulator", lambda a: check_answers(texts, a)
                answers = simulator.answer_questions(fact, [{"question": t} for t in texts])
                write_new(ans_file, {"run_key": run, "questions": texts, "answers": answers, "mock": ws.mock})
            payload = [{"question_id": q["id"], "answer": a["answer"]} for q, a in zip(questions, answers)]
            rec.stage, rec.validator = "reassess", validate_judgments
            changed = reassess(bundle, payload)
            after_reassess = snapshot(bundle)
            rec.stage = "final_check"
            fixes = final_check(bundle)
            after_final = snapshot(bundle)
    except (FormatExhausted, RefusalStop) as e:
        status = "failed_format" if isinstance(e, FormatExhausted) else "refused"
        ws.log_error(run, rec.stage, status, str(e))
        write_new(out, {**entry, "status": status, "failed_stage": rec.stage, "error": str(e), "calls": rec.calls})
        return status
    write_new(out, {**entry, "status": "ok", "mock": ws.mock, "before": before, "after_reassess": after_reassess,
                    "after_final": after_final, "changed": changed, "final_changes": fixes,
                    "finals": {t["nct_id"]: t["final_judgment"] for t in bundle["trials"]}, "calls": rec.calls})
    return "ok"


def execute(stage: str, plan: list[dict], ws: Workspace, transport, stop_after: int | None = None) -> Counter:
    prompts = load_prompts()
    done, streak = Counter(), 0
    for entry in plan:
        if stage == "downstream" and not entry["downstream"]:
            continue
        try:
            result = run_question(entry, prompts, ws, transport) if stage == "questions" else \
                run_downstream(entry, ws, transport)
        except FileExistsError as e:
            ws.log_error(entry["run_key"], stage, "overwrite_blocked", str(e))
            result = "overwrite_blocked"
        except API_ERRORS as e:  # 결과를 남기지 않아 재개 때 다시 시도한다
            ws.log_error(entry["run_key"], stage, "api_error", f"{type(e).__name__}: {e}")
            result = "api_error"
            streak += 1
            if streak >= MAX_API_ERROR_STREAK:
                raise GateError(f"API 오류 {streak}회 연속: 중단. 원인 확인 후 다시 실행하면 이어서 진행")
        else:
            streak = 0
        done[result] += 1
        if stop_after and sum(v for k, v in done.items() if k != "skipped") >= stop_after:
            break
    return done


def paid_gate(args) -> tuple[Workspace, list[dict], dict]:
    """유료 실행 조건 전부 검사."""
    if args.paid != args.experiment:
        raise GateError("--paid에 실험 ID를 그대로 적어야 유료 실행이 시작됨")
    if args.experiment.startswith(SMOKE_PREFIX):
        raise GateError(f"'{SMOKE_PREFIX}'로 시작하는 실험 ID는 연동 테스트 전용")
    annotation_gate()
    versions = verify_versions()
    denominators()
    if tracked_changes():
        raise GateError(f"실험 폴더 밖 변경 있음: {tracked_changes()[:5]}")
    if not (os.environ.get("ANTHROPIC_API_KEY") or (ROOT / ".env").exists() or (ROOT / "eval" / ".env").exists()):
        raise GateError("API 키 없음")
    ws = Workspace(REAL_ROOT / args.experiment, mock=False)
    if ws.seal_record.exists():
        raise GateError("봉인된 실험 폴더: 채점표 생성 후에는 질문 생성·후속 실행을 하지 않음")
    plan = make_plan()
    ws.prepare(plan, versions)
    return ws, plan, versions


# ── 소규모 연동 테스트 (Phase 6A, 유료) ─────────────────────
# 결과는 분석에서 제외한다. 파일럿과 실행 계획이 달라 같은 폴더에 섞이지 않는다 (Workspace.prepare).

SMOKE_PREFIX = "smoke"
SMOKE_PLAN = [  # 6A-1: S004의 C0·C_full 질문 2회. 6A-2: C_full 1세트만 후속 판정
    {"run_key": run_key("C0", "S004", 1), "arm": "C0", "patient_id": "S004", "rep": 1, "downstream": False},
    {"run_key": run_key("C_full", "S004", 1), "arm": "C_full", "patient_id": "S004", "rep": 1, "downstream": True},
]
SMOKE_CALL_CAP_USD = 0.20   # 호출 1회 안전 상한: 출력 16,000토큰($0.16) + 입력 2만 토큰($0.04)
SMOKE_BUDGET_USD = 1.00     # 같은 smoke 폴더의 누계 상한. 넘으면 다음 호출 전에 멈춘다
SMOKE_STOP_STATUS = (401, 403, 404)
PING = ("Reply with exactly one word: OK", "ping")   # 6A-0. 실험 데이터를 보내지 않는다


def stop_on_status(e: Exception) -> None:
    code = getattr(e, "status_code", None)
    if code in SMOKE_STOP_STATUS:
        raise GateError(f"API {code} 오류: 키·권한·모델 확인 전까지 중단") from e


class SmokeTransport:
    """연동 테스트 중단 조건. 응답은 검사 전에 smoke_calls.jsonl에 먼저 남긴다."""

    def __init__(self, inner, ws: Workspace, model_id: str):
        self.inner, self.model_id = inner, model_id
        self.log = ws.root / "smoke_calls.jsonl"
        old = [json.loads(l) for l in self.log.read_text(encoding="utf-8").splitlines()] if self.log.exists() else []
        self.spent = sum(r["cost_usd"] or 0.0 for r in old)

    def __call__(self, system: str, user: str) -> dict:
        if self.spent >= SMOKE_BUDGET_USD:
            raise GateError(f"smoke 누계 비용 ${self.spent:.2f}가 상한 ${SMOKE_BUDGET_USD:.2f}에 도달")
        try:
            reply = self.inner(system, user)
        except Exception as e:  # noqa: BLE001  상태 코드만 보고 나머지는 그대로 올린다
            stop_on_status(e)
            raise
        price = llm.PRICE.get(reply["model"])
        cost = (reply["input_tokens"] * price[0] + reply["output_tokens"] * price[1]) / 1e6 if price else None
        self.spent += cost or 0.0
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps({**{k: reply[k] for k in ("model", "stop_reason", "input_tokens", "output_tokens",
                                                          "request_id", "elapsed")},
                                "cost_usd": cost, "text_head": reply["text"][:300],
                                "time": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False) + "\n")
        if reply["model"] != self.model_id:
            raise GateError(f"응답 모델 불일치: {reply['model']} (고정 {self.model_id})")
        if not cost:
            raise GateError("호출 비용을 계산할 수 없음 (단가 없음 또는 토큰 0)")
        if cost > SMOKE_CALL_CAP_USD:
            raise GateError(f"호출 1회 비용 ${cost:.3f}가 상한 ${SMOKE_CALL_CAP_USD:.2f} 초과")
        return reply


TOTAL_BUDGET_USD = 10.00    # 연구 담당자 결정 (2026-11-05, $6에서 상향): smoke + 파일럿 모든 유료 단계 합계
LEDGER_NAME = "spend_ledger.jsonl"   # REAL_ROOT 아래 공용 장부. 실험 폴더·단계·재시작과 무관하게 합산


class BudgetExhausted(GateError):
    """예산 부족. 완료된 결과는 그대로 두고 추가 호출을 하지 않는다."""


class BudgetTransport:
    """공용 예산 검사. 호출 전에 '장부 누계 + 이번 호출의 최악 비용'이 예산을 넘으면 호출하지 않고 멈춘다.

    최악 비용 = 입력 UTF-8 바이트 수(토큰 수의 상한)×입력 단가 + MAX_TOKENS×출력 단가.
    응답 없이 실패한 호출(연결 오류·시간 초과 등)도 청구됐을 수 있으므로 최악 비용으로 장부에 적는다 (보수적 집계).
    SDK 내부 재시도는 RealTransport에서 끈다. 형식 실패 재시도와 재실행은 모두 이 검사를 다시 거친다.
    보장하지 못하는 것: 단가표(llm.PRICE)가 실제 청구 단가와 다를 때.
    장부에는 실험 ID와 단계만 적는다 (실행 키에는 조건 이름이 들어 있으므로 적지 않는다).
    """

    def __init__(self, inner, label: str, ledger: Path | None = None, budget_usd: float = TOTAL_BUDGET_USD):
        self.inner, self.label, self.budget = inner, label, budget_usd
        self.ledger = ledger or REAL_ROOT / LEDGER_NAME
        self.price = llm.PRICE.get(llm.MODEL)
        if not self.price:
            raise GateError(f"고정 모델 단가 없음: {llm.MODEL}")

    def spent(self) -> float:
        if not self.ledger.exists():
            return 0.0
        return sum(json.loads(l)["cost_usd"] for l in self.ledger.read_text(encoding="utf-8").splitlines() if l.strip())

    def _write(self, cost: float, kind: str, **extra) -> None:
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ledger, "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "label": self.label, "kind": kind,
                                "cost_usd": cost, **extra}, ensure_ascii=False) + "\n")

    def __call__(self, system: str, user: str) -> dict:
        worst = (len((system + user).encode("utf-8")) * self.price[0] + MAX_TOKENS * self.price[1]) / 1e6
        spent = self.spent()
        if spent + worst > self.budget:
            raise BudgetExhausted(f"예산 부족으로 중단: 누계 ${spent:.2f} + 다음 호출 최악 ${worst:.2f} > 예산 ${self.budget:.2f}. "
                                  "완료된 결과는 보존됨")
        try:
            reply = self.inner(system, user)
        except Exception as e:  # noqa: BLE001  청구 여부를 알 수 없으므로 최악 비용으로 적고 그대로 올린다
            self._write(worst, "error_charged_as_worst", error=type(e).__name__)
            raise
        price = llm.PRICE.get(reply["model"])
        if not price:
            self._write(worst, "unknown_price_charged_as_worst", model=reply["model"])
            raise GateError(f"응답 모델 단가 없음: {reply['model']} (비용 집계 불가)")
        cost = (reply["input_tokens"] * price[0] + reply["output_tokens"] * price[1]) / 1e6
        self._write(cost, "ok", model=reply["model"], input_tokens=reply["input_tokens"],
                    output_tokens=reply["output_tokens"])
        return reply


def smoke_gate(args, step: str) -> tuple[Workspace, dict]:
    """6A-0(ping)은 실험 데이터를 쓰지 않아 사전 주석 잠금 없이 열린다. 6A-1·2는 파일럿과 같은 조건."""
    if args.paid != args.experiment:
        raise GateError("--paid에 실험 ID를 그대로 적어야 유료 실행이 시작됨")
    if not args.experiment.startswith(SMOKE_PREFIX):
        raise GateError(f"연동 테스트 실험 ID는 '{SMOKE_PREFIX}'로 시작해야 함")
    if step != "ping":
        annotation_gate()
        denominators()
    versions = verify_versions()
    if tracked_changes():
        raise GateError(f"실험 폴더 밖 변경 있음: {tracked_changes()[:5]}")
    ws = Workspace(REAL_ROOT / args.experiment, mock=False)
    ws.prepare(SMOKE_PLAN, versions)
    return ws, versions


def smoke_client():
    """키 값은 출력하지 않는다. 빈 .env도 여기서 걸린다."""
    try:
        client = llm.get_client()
    except Exception as e:  # noqa: BLE001
        raise GateError(f"API 클라이언트 생성 실패 ({type(e).__name__})") from None
    if not getattr(client, "api_key", None):
        raise GateError("API 키 없음")
    return client


def smoke_ping(client, transport: SmokeTransport, model_id: str) -> dict:
    try:
        found = getattr(client.models.retrieve(model_id), "id", None)
    except Exception as e:  # noqa: BLE001
        stop_on_status(e)
        raise
    reply = transport(*PING)
    return {"model_lookup": found, "model_lookup_match": found == model_id,
            "reply_ok": reply["text"].strip().strip(".").upper() == "OK",
            "call": {k: reply[k] for k in ("model", "stop_reason", "input_tokens", "output_tokens")}}


def run_smoke(step: str, ws: Workspace, versions: dict, client) -> dict:
    """질문 텍스트는 출력하지 않는다. 결과 파일은 관리자만 본다."""
    budget = BudgetTransport(RealTransport(client), f"{ws.root.name}:smoke_{step}")
    transport = SmokeTransport(budget, ws, versions["model_id"])
    if step == "ping":
        result = smoke_ping(client, transport, versions["model_id"])
    else:
        done = execute(step, SMOKE_PLAN, ws, transport)
        folder = ws.questions if step == "questions" else ws.downstream
        result = {"done": dict(done), "runs": {}}
        for e in SMOKE_PLAN:
            f = folder / f"{e['run_key']}.json"
            if f.exists():
                r = read_json(f)
                result["runs"][e["run_key"]] = {
                    "status": r["status"], "failed_stage": r.get("failed_stage"),
                    "n_final_questions": len(r.get("final_questions", [])),
                    "d9_below_heuristic": r.get("d9_below_heuristic"), "not_asked_report": r.get("not_asked_report"),
                    "calls": r["calls"]}
    result.update(step=step, analysis="제외 (연동 테스트)", spent_usd=round(transport.spent, 4),
                  budget_usd=SMOKE_BUDGET_USD, total_spent_usd=round(budget.spent(), 4),
                  total_budget_usd=TOTAL_BUDGET_USD)
    n = 1
    while (ws.root / f"smoke_{step}_{n:03d}.json").exists():
        n += 1
    write_new(ws.root / f"smoke_{step}_{n:03d}.json", result)
    return result


# ── 채점 연결 (STEP 4 scoring.py 재사용) ───────────────────

def core_parts(pid: str, base: Path | None = None) -> dict:
    """확정 주석의 H 기준별 (핵심 부분 또는 "전체", 필요한 정보). 확정표가 없으면(잠금 전 dry-run) 비어 있다.

    핵심 부분의 범위는 사전 주석 단계에서 정해 잠근 값이다. 채점 단계에서는 바꾸지 않는다.
    """
    f = (base or ANNOTATION_RECORD.parent) / f"{pid}_final.csv"
    if not f.exists():
        return {}
    return {f"{r['trial_id']}|{r['criterion_id']}": (r["final_core_part"].strip(), r["final_core_info"].strip())
            for r in sc.read_csv(f) if r["h_strict"].lower() == "true"}


def build_rater_packet(ws: Workspace, seed: int, ann_base: Path | None = None) -> dict:
    runs = [r for r in map(read_json, sorted(ws.questions.glob("*.json"))) if r["status"] == "ok"]
    parts = {pid: core_parts(pid, ann_base) for pid in PATIENTS}
    for r in runs:
        mine = parts.get(r["patient_id"], {})
        r["criteria"] = {k: {**v, "core_part": mine.get(k, ("", ""))[0], "core_info": mine.get(k, ("", ""))[1]}
                         for k, v in r["criteria"].items()}
    mapping = sc.build_packet(runs, ws.packet, ws.sealed, seed)
    (ws.sealed / "double_score_sets.json").write_text(
        json.dumps(sc.double_score_sample(mapping, seed), indent=2) + "\n", encoding="utf-8")
    return mapping


Q_FIELDS = ["assumption", "redundancy", "single_topic", "overgroup"]
L_FIELDS = ["preservation", "coverage", "core_coverage", "group_validity"]
Q_KEYS = ("blind_id", "question_no")
L_KEYS = ("blind_id", "question_no", "trial_id", "criterion_id")


def compare_raters(rater1: Path, rater2: Path, out: Path) -> dict:
    rows_q, stats_q = sc.disagreements("question", sc.read_csv(rater1 / "question_sheet.csv"),
                                       sc.read_csv(rater2 / "question_sheet.csv"), Q_FIELDS, Q_KEYS)
    rows_l, stats_l = sc.disagreements("link", sc.read_csv(rater1 / "link_sheet.csv"),
                                       sc.read_csv(rater2 / "link_sheet.csv"), L_FIELDS, L_KEYS)
    sc.write_csv(out / "adjudication.csv", sc.SCHEMA["adjudication_columns"], rows_q + rows_l)
    result = {"question": stats_q, "link": stats_l, "disagreements": len(rows_q) + len(rows_l)}
    write_new(out / "agreement.json", result)
    return result


def merge_scores(primary: Path, adjudication: Path, out: Path) -> None:
    """1차 채점표에 조정 결과를 반영해 확정표를 만든다. 원본은 고치지 않는다."""
    adj = sc.read_csv(adjudication) if adjudication.exists() else []
    if any(not a["final_value"] for a in adj):
        raise GateError("조정되지 않은 불일치가 있음")
    q, l = sc.read_csv(primary / "question_sheet.csv"), sc.read_csv(primary / "link_sheet.csv")
    for sheet, rows, keys in (("question", q, Q_KEYS), ("link", l, L_KEYS)):
        index = {"|".join(str(r[k]) for k in keys): r for r in rows}
        for a in adj:
            if a["sheet"] == sheet:
                index[a["item_key"]][a["field"]] = a["final_value"]
    errs = sc.validate(q, l)
    if errs:
        raise GateError(f"확정표 형식 오류 {len(errs)}건: {errs[:3]}")
    sc.write_csv(out / "question_final.csv", sc.QC, q)
    sc.write_csv(out / "link_final.csv", sc.LC, l)


# ── 조건 매핑 자동 봉인 (방식 B, 2026-11-05 결정) ───────────
# 자기 관리 봉인이다: 같은 계정에서 묶음을 열 수 있으며 실제 접근 차단 장치가 없다.
# 해시는 봉인 후 변경을 드러낼 뿐 열람 여부를 증명하지 않는다. 결과 보고에 이 한계를 적는다.

SEALED_PARTS = ("questions", "attempts", "answers", "downstream", "errors.jsonl", "sealed")
SEAL_LIMITATION = ("자기 관리 봉인 (방식 B: 자동 봉인·로그 가림). 같은 계정에서 열 수 있으며 실제 접근 차단 장치가 없다. "
                   "해시는 봉인 후 변경만 드러내고 열람 여부를 증명하지 않는다.")


def seal(ws: Workspace) -> dict:
    """채점표 생성 직후 조건이 드러나는 실행 기록과 sealed/를 묶음 하나로 옮긴다. 화면에는 건수만 낸다."""
    if ws.seal_record.exists():
        raise GateError("이미 봉인됨")
    if not (ws.sealed / "blind_map.json").exists() or not (ws.packet / "question_sheet.csv").exists():
        raise GateError("채점표 생성 후에 봉인한다")
    parts = [ws.root / p for p in SEALED_PARTS if (ws.root / p).exists()]
    files = [f for p in parts for f in ([p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file()))]
    with zipfile.ZipFile(ws.bundle, "x", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.relative_to(ws.root).as_posix())
    with zipfile.ZipFile(ws.bundle) as z:
        if z.testzip() is not None or len(z.namelist()) != len(files):
            ws.bundle.unlink()
            raise GateError("봉인 묶음 검증 실패 (원본은 그대로 둠)")
    digest = sc.sha_file(ws.bundle)
    for p in parts:
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    write_new(ws.seal_record, {"sealed_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "bundle_sha256": digest,
                               "files": len(files), "limitation": SEAL_LIMITATION})
    return {"sealed_files": len(files)}


def unseal(ws: Workspace) -> dict:
    """채점 잠금(sealed/lock.json)이 있고 채점 확정표가 그대로일 때만 묶음을 푼다."""
    if not ws.seal_record.exists():
        raise GateError("봉인 기록 없음")
    finals = [ws.scores / "question_final.csv", ws.scores / "link_final.csv"]
    lock = ws.sealed / "lock.json"
    if not lock.exists():
        raise GateError("채점 잠금 전에는 봉인을 풀 수 없음")
    if read_json(lock)["files"] != {f.name: sc.sha_file(f) for f in finals if f.exists()}:
        raise GateError("잠금 후 채점 파일이 바뀜")
    if sc.sha_file(ws.bundle) != read_json(ws.seal_record)["bundle_sha256"]:
        raise GateError("봉인 묶음이 봉인 후 바뀜")
    with zipfile.ZipFile(ws.bundle) as z:
        names = z.namelist()
        clash = [n for n in names if (ws.root / n).exists()]
        if clash:
            raise GateError(f"풀 위치에 같은 파일이 있음 ({len(clash)}건)")
        z.extractall(ws.root)
    write_new(ws.root / "unseal_record.json", {"unsealed_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "files": len(names)})
    return {"unsealed_files": len(names)}


def rater_id_problems(rows: list[dict], record: Path | None = None) -> list[str]:
    """채점표의 rater_id가 잠금 기록에 등록된 채점자 ID(role이 rater로 시작)인지."""
    record = record or ANNOTATION_RECORD
    if not record.exists():
        return ["사전 주석 잠금 기록 없음"]
    ids = {p.get("id") for p in read_json(record).get("people", []) if str(p.get("role", "")).startswith("rater")}
    bad = sorted({r.get("rater_id", "") for r in rows} - ids)
    return [f"등록되지 않은 rater_id {bad} (등록: {sorted(ids)})"] if bad else []


def load_final_annotation(pid: str, base: Path) -> tuple[dict, dict]:
    ann = {}
    for r in sc.read_csv(base / f"{pid}_final.csv"):
        ann[(r["trial_id"], r["criterion_id"])] = {
            "askable": r["final_askable"], "candidate": True,
            "centrality": r["final_centrality"], "h_strict": r["h_strict"].lower() == "true",
            "h_any": r["h_any"].lower() == "true"}
    clusters = defaultdict(set)
    for r in sc.read_csv(base / f"{pid}_clusters.csv"):
        clusters[r["cluster_id"]].add((r["trial_id"], r["criterion_id"]))
    return ann, dict(clusters)


def blind_status(registry: Path | None) -> dict:
    """정답 노출자가 있으면 독립적인 정답 블라인드 평가로 표시하지 않는다."""
    rows = sc.read_csv(registry) if registry and registry.exists() else []
    exposed = [r for r in rows if r["gold_exposed"] != "none"]
    label = ("정답 노출 연구자의 탐색적 채점: 독립 평가로 보고하지 않음" if exposed
             else "정답 비노출 평가자" if rows else "평가자 기록 없음")
    return {"registered": len(rows), "gold_exposed": exposed, "label": label,
            "independent_gold_blind": bool(rows) and not exposed, "condition_blind": True}


def summarize(values: list) -> dict:
    nums = [v for v in values if v is not None]
    return {"mean": statistics.mean(nums) if nums else None, "min": min(nums) if nums else None,
            "max": max(nums) if nums else None, "n": len(nums), "undefined": len(values) - len(nums)}


def downstream_metrics(ws: Workspace, mapping: dict, audit: Path | None) -> dict:
    """M8. unblind 통과 후에만 호출된다."""
    exclude = defaultdict(set)
    if audit and audit.exists():
        for r in sc.read_csv(audit):
            if r["simulator_code"] in ("S1", "S2", "S3"):
                exclude[r["audit_id"].split("#")[0]].add(int(r["audit_id"].split("#")[1]))
    by_bid = {m["run_key"]: b for b, m in mapping.items()}
    cells, flips = defaultdict(list), defaultdict(list)
    for f in sorted(ws.downstream.glob("*.json")):
        d = read_json(f)
        if d["status"] != "ok":
            continue
        gold = {f"{k[0]}|{k[1]}": v["verdict"] for k, v in gold_of(load_sheet(d["patient_id"])).items()}
        tup = lambda m: {tuple(k.split("|")): v for k, v in m.items()}  # noqa: E731
        q = read_json(ws.questions / f.name)["final_questions"]
        drop = {f"{r['trial']}|{c}" for i, x in enumerate(q, 1) if i in exclude.get(by_bid.get(d["run_key"]), ())
                for r in x["resolves"] for c in r["criteria"]}
        row = {}
        for tag, snap in (("reassess", d["after_reassess"]), ("final", d["after_final"])):
            m = sc.m8_metrics(tup(d["before"]), tup(snap), tup(gold))
            m["M8c"] = m["M8a_n"] / len(q) if q else None
            row[tag] = m
        if drop:
            keep = lambda m: {k: v for k, v in m.items() if k not in drop}  # noqa: E731
            row["final_excl_sim"] = sc.m8_metrics(tup(keep(d["before"])), tup(keep(d["after_final"])), tup(keep(gold)))
        cells[(d["patient_id"], d["arm"])].append(row)
        flips[(d["patient_id"], d["arm"])].append(tup(d["after_final"]))
    out = {}
    for key, rows in cells.items():
        res = {f"{tag}.{name}": summarize([r[tag][name] for r in rows])
               for tag in ("reassess", "final") for name in ("M8a", "M8b", "M8c", "M8d")}
        res["M7b"] = sc.verdict_flip_rate(flips[key])
        out["|".join(key)] = res
    return out


def report(ws: Workspace, ann_base: Path, registry: Path | None, audit: Path | None) -> dict:
    """잠금 후 조건 공개 → 환자×조건 집계 → 정답 대조. 잠금이 없으면 정답을 읽기 전에 실패한다."""
    final = [ws.scores / "question_final.csv", ws.scores / "link_final.csv"]
    mapping = sc.unblind(ws.sealed, final)
    q_rows, l_rows = sc.read_csv(final[0]), sc.read_csv(final[1])
    rows = defaultdict(list)
    for bid, m in mapping.items():
        ann, clusters = load_final_annotation(m["patient_id"], ann_base)
        got = sc.set_metrics([r for r in q_rows if r["blind_id"] == bid], [r for r in l_rows if r["blind_id"] == bid],
                             ann, clusters)
        rows[(m["patient_id"], m["arm"])].append(got)
    table = {}
    for key, sets in rows.items():
        names = [k for k, v in sets[0].items() if isinstance(v, (int, float)) or v is None]
        cell = {n: summarize([s[n] for s in sets]) for n in names}
        cell["M7a"] = sc.stability([s["covered_set"] for s in sets])
        table["|".join(key)] = cell
    record = ann_base / "annotation_record.json"
    src = read_json(record).get("annotation_source", {}) if record.exists() else {}
    raters = sorted({r["rater_id"] for r in q_rows + l_rows})
    result = {"mock": ws.mock, "scope": "개발 데이터 탐색 결과. 환자를 합산하지 않음",
              "preannotation": ("미검증 AI 주석 (AI 주석 버전 고정, 사람 항목별 검토 없음). "
                                "M4a는 AI가 핵심으로 분류한 기준의 커버리지" if src.get("mode") == AI_MODE
                                else "사람 주석 (지침 2절 절차)"),
              "scoring_raters": {"n": len(raters),
                                 "note": "단일 평가자: 평가자 간 일치도·κ 없음" if len(raters) == 1 else ""},
              "condition_mapping": (read_json(ws.seal_record)["limitation"] if ws.seal_record.exists()
                                    else "봉인 기록 없음 (방식 A 또는 mock)"),
              "blinding": blind_status(registry), "question_metrics": table,
              "downstream_metrics": downstream_metrics(ws, mapping, audit)}
    write_new(ws.scores / "report.json", result)
    return result


def sim_audit_sheet(ws: Workspace) -> Path:
    """시뮬레이터 감사표. 사실 자료가 들어가므로 채점 잠금 후에만 만든다."""
    final = [ws.scores / "question_final.csv", ws.scores / "link_final.csv"]
    mapping = sc.unblind(ws.sealed, final)
    by_run = {m["run_key"]: (b, m) for b, m in mapping.items()}
    rows = []
    for f in sorted(ws.answers.glob("*.json")):
        d = read_json(f)
        bid, m = by_run[d["run_key"]]
        fact = load_sheet(m["patient_id"])["detailed_text"]
        rows += [{"audit_id": f"{bid}#{i}", "patient_id": m["patient_id"], "question_text": q, "answer_text": a["answer"],
                  "fact_text": fact, "simulator_code": "", "rationale": "", "rater_id": "", "needs_review": ""}
                 for i, (q, a) in enumerate(zip(d["questions"], d["answers"]), 1)]
    path = ws.scores / "simulator_audit.csv"
    sc.write_csv(path, sc.SCHEMA["simulator_audit_columns"], rows)
    return path


# ── 비용 추정 ──────────────────────────────────────────────

# 호출 1회 비용 범위 (달러, 정가). 근거: cost_estimate.md
UNIT_COST = {"question": (0.04, 0.09), "simulator": (0.003, 0.01), "reassess": (0.01, 0.025), "final_check": (0.015, 0.03)}
RETRY_RATE = 0.10


def call_counts() -> dict:
    plan = make_plan()
    core = sum(p["downstream"] for p in plan)
    trials = {p: len(make_bundle(p)["trials"]) for p in PATIENTS}
    per_run = [trials[p["patient_id"]] for p in plan if p["downstream"]]
    return {"question": (len(plan), len(plan)), "simulator": (core, core), "reassess": (core, sum(per_run)),
            "final_check": (sum(per_run), sum(per_run))}


def estimate() -> dict:
    counts = call_counts()
    lines = {k: {"calls": list(counts[k]), "usd": [round(counts[k][0] * UNIT_COST[k][0], 2), round(counts[k][1] * UNIT_COST[k][1], 2)]}
             for k in counts}
    low, high = sum(v["usd"][0] for v in lines.values()), sum(v["usd"][1] for v in lines.values())
    return {"price_per_mtok": llm.PRICE.get(llm.MODEL), "lines": lines,
            "total_calls": [sum(v["calls"][0] for v in lines.values()), sum(v["calls"][1] for v in lines.values())],
            "base_usd": [round(low, 2), round(high, 2)],
            "retry_usd_at_10pct": [round(low * RETRY_RATE, 2), round(high * RETRY_RATE, 2)],
            "total_usd": [round(low * (1 + RETRY_RATE), 2), round(high * (1 + RETRY_RATE), 2)]}


# ── 명령 ───────────────────────────────────────────────────

def cmd_dry_run(out: Path) -> dict:
    """mock으로 전체 흐름 실행. API·키·사전 주석이 없어도 된다."""
    plan = make_plan()
    versions = compute_versions()
    ws = Workspace(out, mock=True)
    ws.prepare(plan, versions)
    transport = MockTransport()
    q = execute("questions", plan, ws, transport)
    d = execute("downstream", plan, ws, transport)
    mapping = build_rater_packet(ws, seed=PLAN_SEED)
    calls = Counter(a.name.split("__")[3] for a in ws.attempts.glob("*.json"))
    result = {"mock": True, "planned_runs": len(plan), "questions": dict(q), "downstream": dict(d),
              "mock_calls_by_stage": dict(calls), "blind_sets": len(mapping), "denominators": denominators(),
              "paid_gate": gate_status(), "plan_sha256": plan_hash(plan)}
    write_new(out / "dryrun_report.json", result)
    return result


def gate_status() -> dict:
    status = {}
    for name, fn in (("annotation", annotation_gate), ("versions", verify_versions)):
        try:
            fn()
            status[name] = "통과"
        except GateError as e:
            status[name] = f"차단: {e}"
    status["outside_changes"] = tracked_changes()
    status["api_key_present"] = bool(os.environ.get("ANTHROPIC_API_KEY") or (ROOT / ".env").exists() or (ROOT / "eval" / ".env").exists())
    return status


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("freeze", help="고정 값을 pilot_lock.json에 기록 (1회)")
    sub.add_parser("check", help="버전·모집단·유료 실행 조건 점검")
    sub.add_parser("plan", help="실행 순서 출력")
    p = sub.add_parser("lock-annotation", help="사전 주석 잠금")
    p.add_argument("draft", type=Path)
    sub.add_parser("estimate", help="호출 수·비용 추정")
    p = sub.add_parser("dry-run")
    p.add_argument("--out", type=Path, default=HERE / "dryrun" / "pilot_dryrun")
    for name in ("questions", "downstream"):
        p = sub.add_parser(name, help="유료")
        p.add_argument("--experiment", required=True)
        p.add_argument("--paid", required=True, help="실험 ID를 다시 적는다")
    p = sub.add_parser("smoke", help="유료 연동 테스트 (분석 제외)")
    p.add_argument("step", choices=["ping", "questions", "downstream"])
    p.add_argument("--experiment", required=True, help=f"'{SMOKE_PREFIX}'로 시작")
    p.add_argument("--paid", required=True, help="실험 ID를 다시 적는다")
    for name, extra in (("packet", ["--seed"]), ("lock-scores", []), ("sim-audit", []), ("unseal", [])):
        p = sub.add_parser(name)
        p.add_argument("--workspace", type=Path, required=True)
        if extra:
            p.add_argument("--seed", type=int, help="생략 권장: 비밀 난수를 쓰고 sealed/에만 저장한다. "
                                                    "시드를 알면 실행 목록만으로 조건 매핑을 다시 계산할 수 있다")
    p = sub.add_parser("compare-raters")
    p.add_argument("rater1", type=Path)
    p.add_argument("rater2", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("merge")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--primary", type=Path, required=True)
    p.add_argument("--adjudication", type=Path, required=True)
    p = sub.add_parser("report")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--registry", type=Path)
    p.add_argument("--sim-audit", type=Path)
    args = ap.parse_args()

    if args.cmd == "freeze":
        write_new(LOCK, {"versions": compute_versions(), "runtime": runtime_info(), "denominators": denominators()})
        print(f"저장: {LOCK}")
    elif args.cmd == "check":
        print(json.dumps({"denominators": denominators(), "gates": gate_status()}, ensure_ascii=False, indent=2))
    elif args.cmd == "lock-annotation":
        print(json.dumps(lock_annotation(args.draft), ensure_ascii=False, indent=2))
    elif args.cmd == "plan":
        for i, e in enumerate(make_plan(), 1):
            print(i, e["run_key"], "후속 판정" if e["downstream"] else "질문만")
    elif args.cmd == "estimate":
        print(json.dumps(estimate(), ensure_ascii=False, indent=2))
    elif args.cmd == "dry-run":
        print(json.dumps(cmd_dry_run(args.out), ensure_ascii=False, indent=2))
    elif args.cmd in ("questions", "downstream"):
        ws, plan, _ = paid_gate(args)
        transport = BudgetTransport(RealTransport(), f"{args.experiment}:{args.cmd}")
        try:
            print(dict(execute(args.cmd, plan, ws, transport)))
        except Exception as e:  # noqa: BLE001  상세(실행 키 = 조건 이름 포함)는 화면에 내지 않고 errors.jsonl에만 남긴다
            ws.log_error("-", args.cmd, "stopped", f"{type(e).__name__}: {e}")
            note = "예산 부족: 완료된 결과는 보존, 추가 호출 없음" if isinstance(e, BudgetExhausted) else \
                "상세는 실행 폴더 errors.jsonl (채점자는 열지 않음)"
            print(f"[중단] {type(e).__name__}. {note}", file=sys.stderr)
            print(f"누계 비용 ${transport.spent():.2f} / 예산 ${TOTAL_BUDGET_USD:.2f}", file=sys.stderr)
            return 2
        print(f"누계 비용 ${transport.spent():.2f} / 예산 ${TOTAL_BUDGET_USD:.2f}")
    elif args.cmd == "smoke":
        client = smoke_client()   # 키가 없으면 결과 폴더를 만들기 전에 멈춘다
        ws, versions = smoke_gate(args, args.step)
        print(json.dumps(run_smoke(args.step, ws, versions, client), ensure_ascii=False, indent=2))
    elif args.cmd == "packet":
        ws = Workspace.existing(args.workspace)
        seed = args.seed if args.seed is not None else secrets.randbits(48)   # 출력하지 않는다
        n = len(build_rater_packet(ws, seed))
        print(json.dumps({"blind_sets": n, **seal(ws), "note": SEAL_LIMITATION}, ensure_ascii=False))
    elif args.cmd == "unseal":
        print(json.dumps(unseal(Workspace.existing(args.workspace)), ensure_ascii=False))
    elif args.cmd == "compare-raters":
        print(json.dumps(compare_raters(args.rater1, args.rater2, args.out), ensure_ascii=False, indent=2))
    elif args.cmd == "merge":
        ws = Workspace.existing(args.workspace)
        problems = rater_id_problems(sc.read_csv(args.primary / "question_sheet.csv") +
                                     sc.read_csv(args.primary / "link_sheet.csv"))
        if problems:
            raise GateError("; ".join(problems))
        merge_scores(args.primary, args.adjudication, ws.scores)
    elif args.cmd == "lock-scores":
        ws = Workspace.existing(args.workspace)
        finals = [ws.scores / "question_final.csv", ws.scores / "link_final.csv"]
        problems = rater_id_problems(sc.read_csv(finals[0]) + sc.read_csv(finals[1]))
        if problems:
            raise GateError("; ".join(problems))
        sc.lock(ws.sealed, finals)
    elif args.cmd == "sim-audit":
        print(sim_audit_sheet(Workspace.existing(args.workspace)))
    elif args.cmd == "report":
        ws = Workspace.existing(args.workspace)
        print(json.dumps(report(ws, ANNOTATION_RECORD.parent, args.registry, args.sim_audit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GateError as e:
        print(f"[차단] {e}", file=sys.stderr)
        sys.exit(2)
