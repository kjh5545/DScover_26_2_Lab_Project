"""에이전트 파이프라인 (1~4번 담당: 해준, 질문 루프 5~6번 연결: 주희).

[1] 환자 정보 이해 → [2] 후보 검색 + 하드 필터 → [3] 기준 파싱 → [4] 매칭·추론
→ [5] 질문 (next_round) → 환자 답변 → [6] 관련 기준만 재판정 (reassess) → [5] ...
→ 루프를 마치면 전체 재판정 한 번 (final_check)

단일 진입점 run_intake() 가 전 단계를 실행하고, 결과를 표준 전달 형식으로
data/handoff/{patient_id}.json 에 저장한다. 이후 단계(질문 생성·추천) 담당
팀원은 이 파일만 읽으면 된다. 형식 명세: docs/HANDOFF.md

사용 예:
    from src.pipeline import run_intake
    bundle = run_intake("A 34-year-old woman ...", patient_id="S005")
"""

import datetime
import json
from pathlib import Path

from src.agents.criteria_parser import parse_criteria
from src.agents.matcher import final_judgment, match, match_with_rules
from src.agents.patient_profiler import profile_patient
from src.agents.question_generator import generate_questions
from src.agents.trial_searcher import search_candidates
from src.llm import MODEL

ROOT = Path(__file__).resolve().parent.parent
PROMPT_VERSION = "v3"  # 2026-10-12: goldset v1.1 결정 + 환자 원문 입력 (v2: 2026-10-08 회의 결정)


# ── 단계별 함수 (개별 호출도 가능) ──────────────────────────

def understand_patient(case_text: str, patient_id: str | None = None) -> dict:
    """[1] 환자 줄글 → 구조화 프로필 (환자 ID가 있으면 디스크 캐시 사용)."""
    cache = ROOT / "data" / "processed" / "eval_cache" / f"profile_{patient_id}.json" \
        if patient_id else None
    if cache and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    profile = profile_patient(case_text)
    if patient_id:
        profile["id"] = patient_id
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


def find_candidates(profile: dict, max_candidates: int = 3) -> dict:
    """[2] 프로필 → 검색어 결정(LLM) → ClinicalTrials.gov 검색 → 나이·성별 하드 필터."""
    return search_candidates(profile, max_candidates=max_candidates)


def parse_trial(trial: dict) -> list[dict]:
    """[3] 시험의 eligibility criteria 원문 → 원자 조건 목록 (NCT ID별 디스크 캐시)."""
    path = ROOT / "data" / "processed" / f"criteria_{trial['nct_id']}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    criteria = parse_criteria(trial["eligibility_criteria"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(criteria, ensure_ascii=False, indent=2), encoding="utf-8")
    return criteria


def screen(profile: dict, criteria: list[dict], case_text: str | None = None) -> tuple[list[dict], str]:
    """[4] 조건별 4단계 판정 + 근거 → (판정 목록, 최종 판단). case_text: 환자 원문 (v3).
    나이·임신 기준은 코드가 판정해 LLM 결과를 덮어쓴다 (src/tools/rule_checks.py)."""
    judgments, _changed = match_with_rules(profile, criteria, case_text=case_text)
    return judgments, final_judgment(judgments)


# ── 단일 진입점 ─────────────────────────────────────────────

def run_intake(case_text: str, patient_id: str = "CUSTOM",
               max_candidates: int = 3, do_screen: bool = True,
               save: bool = True) -> dict:
    """1→2→3(→4) 전체 실행 후 전달 형식(bundle)을 반환·저장한다.

    do_screen=False 면 매칭([4])을 건너뛰고 파싱까지만 수행
    (질문 생성 담당이 매칭을 직접 돌려보고 싶을 때).
    """
    profile = understand_patient(case_text, patient_id)
    search = find_candidates(profile, max_candidates=max_candidates)

    trials = []
    for t in search["candidates"]:
        entry = {
            "nct_id": t["nct_id"],
            "title": t["title"],
            "eligibility_criteria": t["eligibility_criteria"],
            "minimum_age": t.get("minimum_age"),
            "maximum_age": t.get("maximum_age"),
            "sex": t.get("sex"),
            "criteria": parse_trial(t),
        }
        if do_screen:
            entry["judgments"], entry["final_judgment"] = screen(profile, entry["criteria"], case_text)
        trials.append(entry)

    bundle = {
        "patient_id": patient_id,
        "case_text": case_text,
        "profile": profile,
        "search": {k: v for k, v in search.items() if k != "candidates"},
        "trials": trials,
        "meta": {
            "model": MODEL,
            "prompt_version": PROMPT_VERSION,
            "created": datetime.date.today().isoformat(),
            "stages": "1-4" if do_screen else "1-3",
        },
    }
    if save:
        save_bundle(bundle)
    return bundle


def save_bundle(bundle: dict) -> Path:
    """bundle을 data/handoff/{patient_id}.json 에 저장한다."""
    out = ROOT / "data" / "handoff" / f"{bundle['patient_id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


# ── 질문 루프: [5] 질문 → 환자 답변 → [6] 재평가 ───────────────────
# 형식: docs/결정_HANDOFF_질문루프.md (bundle["rounds"]에 질문·답변·바뀐 판정을 라운드별로 쌓는다)

def asked_criteria(bundle: dict) -> dict[str, set[str]]:
    """이미 질문한 기준 {시험: {기준 ID}} — 같은 기준을 다시 묻지 않기 위해."""
    asked: dict[str, set[str]] = {}
    for r in bundle.get("rounds", []):
        for q in r["questions"]:
            for res in q.get("resolves", []):
                asked.setdefault(res["trial"], set()).update(res["criteria"])
    return asked


def questions_per_trial(bundle: dict, max_questions: int = 5) -> list[dict]:
    """임시 질문 생성: 해준의 build_questions()가 나오기 전까지 쓰는 대체 구현.

    시험마다 기존 5번(generate_questions)을 불러 resolves 형식으로 바꾼 뒤,
    시험별로 번갈아 하나씩 골라 max_questions개를 채운다 (한 시험에 질문이 몰리지 않게).
    여러 시험에 걸친 질문 묶기는 하지 않는다. 부적격 시험과 이미 물어본 기준은 뺀다.
    """
    asked = asked_criteria(bundle)
    per_trial = []
    for t in bundle["trials"]:
        if t.get("final_judgment") == "ineligible":
            continue
        open_j = [j for j in t["judgments"]
                  if j["verdict"] == "unknown" and j["criterion_id"] not in asked.get(t["nct_id"], set())]
        open_ids = {j["criterion_id"] for j in open_j}
        if not open_j:
            continue
        qs = []
        for q in generate_questions(t["criteria"], open_j):
            ids = [cid for cid in q.get("criterion_ids", []) if cid in open_ids]
            if ids:
                qs.append({"text": q["question"], "needed_info": "",
                           "resolves": [{"trial": t["nct_id"], "criteria": ids}]})
        per_trial.append(qs)

    questions = []
    for i in range(max((len(qs) for qs in per_trial), default=0)):   # 시험 A 1번, 시험 B 1번, A 2번, ...
        questions += [qs[i] for qs in per_trial if i < len(qs)]
    return [dict(q, priority=n) for n, q in enumerate(questions[:max_questions], 1)]


def next_round(bundle: dict, build_questions=None, max_questions: int = 5, save: bool = False) -> list[dict]:
    """[5] 이번 라운드 질문을 만들어 bundle["rounds"]에 추가하고, 추가한 질문을 반환한다.

    build_questions: bundle → [{"text", "needed_info", "resolves", "priority"}] 함수 (5번, 해준).
                     없으면 questions_per_trial (임시). ID는 여기서 Q1, Q2, ... 통번호로 붙인다.
    질문이 없으면 라운드를 만들지 않고 [] 반환.
    """
    rounds = bundle.setdefault("rounds", [])
    questions = (build_questions or questions_per_trial)(bundle, max_questions=max_questions)
    n_before = sum(len(r["questions"]) for r in rounds)
    questions = [dict(q, id=f"Q{n_before + i}") for i, q in enumerate(questions, 1)]
    if questions:
        rounds.append({"round": len(rounds) + 1, "questions": questions, "answers": [], "changed": []})
    if save:
        save_bundle(bundle)
    return questions


def all_answers(bundle: dict) -> list[dict]:
    """지금까지 받은 모든 답변 [{"id", "question", "answer"}] — 판정에 그대로 넘긴다."""
    out = []
    for r in bundle.get("rounds", []):
        by_q = {a["question_id"]: a["answer"] for a in r["answers"]}
        out += [{"id": q["id"], "question": q["text"], "answer": by_q[q["id"]]}
                for q in r["questions"] if q["id"] in by_q]
    return out


def reassess(bundle: dict, answers: list[dict], full: bool = False, save: bool = False) -> list[dict]:
    """[6] 환자 답변을 기록하고, 답과 관련된 기준만 다시 판정한다. 이번에 바뀐 판정 목록을 반환.

    answers: [{"question_id": "Q1", "answer": "..."}] — 빈 답은 기록하지 않음 (답 없는 질문으로 남고, 다음 라운드에 다시 묻지 않음)
    full=True: 모든 시험의 모든 기준을 다시 판정 (마지막 확인용 — 환자가 묻지 않은 정보를
               덧붙였을 때 대비). answers=[] 와 같이 쓰면 답변 기록 없이 전체 재판정만 한다.
    판정에는 원문 + 지금까지의 모든 답변이 들어가고, 프로필은 다시 쓰지 않는다.
    """
    rounds = bundle.get("rounds", [])
    q_index = {q["id"]: (r, q) for r in rounds for q in r["questions"]}
    new = [a for a in answers if str(a.get("answer", "")).strip()]
    missing = [a["question_id"] for a in new if a["question_id"] not in q_index]
    if missing:
        raise ValueError(f"bundle에 없는 질문 ID: {missing}")

    # 1. 답변 기록 (같은 질문에 다시 답하면 새 답으로 바꿈)
    for a in new:
        r, _ = q_index[a["question_id"]]
        r["answers"] = [x for x in r["answers"] if x["question_id"] != a["question_id"]]
        r["answers"].append({"question_id": a["question_id"], "answer": str(a["answer"]).strip()})

    # 2. 다시 판정할 기준 {시험: {기준: [근거 질문 ID]}}
    targets: dict[str, dict[str, list[str]]] = {}
    if full:
        for t in bundle["trials"]:
            targets[t["nct_id"]] = {c["id"]: ["full"] for c in t["criteria"]}
    else:
        for a in new:
            for res in q_index[a["question_id"]][1].get("resolves", []):
                for cid in res["criteria"]:
                    targets.setdefault(res["trial"], {}).setdefault(cid, []).append(a["question_id"])

    # 3~4. 시험별로 그 기준만 다시 판정 (코드 판정·출력 검사 포함) → 합치고 최종 판단 다시 계산
    answered = all_answers(bundle)
    trials = {t["nct_id"]: t for t in bundle["trials"]}
    changed = []
    for nct, sources in targets.items():
        t = trials.get(nct)
        subset = [c for c in t["criteria"] if c["id"] in sources] if t else []
        if not subset:
            continue
        new_j, _ = match_with_rules(bundle["profile"], subset, case_text=bundle.get("case_text"),
                                    answers=answered)
        by_id = {j["criterion_id"]: j for j in t["judgments"]}
        for j in new_j:
            before = by_id.get(j["criterion_id"], {}).get("verdict")
            if before != j["verdict"]:
                changed.append({"trial": nct, "criterion_id": j["criterion_id"], "from": before,
                                "to": j["verdict"], "source": sources[j["criterion_id"]]})
            by_id[j["criterion_id"]] = j
        t["judgments"] = [by_id[c["id"]] for c in t["criteria"] if c["id"] in by_id]
        t["final_judgment"] = final_judgment(t["judgments"])

    # 5. 바뀐 판정 기록
    if rounds:
        rounds[-1]["changed"].extend(changed)
    if save:
        save_bundle(bundle)
    return changed


def final_check(bundle: dict, save: bool = False) -> list[dict]:
    """질문 루프를 마친 뒤 반드시 한 번 부른다: 모든 기준을 원문 + 모든 답변으로 다시 판정.

    부분 재판정은 답과 관련된 기준만 보기 때문에 (1) 환자가 묻지 않은 정보를 덧붙인 경우를 놓치고
    (2) 같은 답을 다른 맥락에서 다르게 판정할 수 있다. 10/16 실제 실행(S004)에서 "수술 일정 아직 없음"을
    부분 재판정은 탈락, 전체 재판정은 모름으로 판정했고 정답은 모름이었다. 바뀐 판정은 source ["full"]로 기록.
    """
    return reassess(bundle, [], full=True, save=save)
