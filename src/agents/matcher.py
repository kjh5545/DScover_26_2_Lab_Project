"""[4] 매칭·추론 에이전트.

환자 프로필 + 파싱된 기준 목록을 받아, 기준 하나하나에 대해
4단계 판정(pass/fail/unknown/post_enrollment)과 근거를 생성한다.

킥오프 문서의 판정 규칙(사전 실험 v3에서 검증된 규칙 포함)을 프롬프트에 넣는다:
- 실험 5에서 v3 규칙 3개로 Opus 기준 일치 100% 달성
- 프롬프트 v3 (2026-10-12): goldset v1.1 불일치 분석 반영 — 환자 원문 입력, 추정 진단 사용 금지(규칙 9),
  검사 수치 미기재 = unknown(규칙 10), 연구자 판단·순응도·수술 적합성·기대 여명 = post_enrollment(규칙 4)
"""

import json

from src.llm import ask_json

SYSTEM_PROMPT = """You are a clinical trial eligibility matching agent.

You receive the patient's ORIGINAL DESCRIPTION, a structured patient profile
derived from it (which may also contain newer facts from the patient's answers
to screening questions), and a list of parsed eligibility criteria. For EVERY
criterion (and every sub-condition), judge whether the patient passes it, and
give evidence.

Verdicts (exactly one per criterion):
- "pass": it is confirmed the patient is NOT excluded by this criterion
- "fail": it is confirmed the patient IS excluded by this criterion
- "unknown": the information could be obtained by asking the patient or
  checking existing records now, but is not given
- "post_enrollment": the information only comes into existence after the
  patient applies, or only the study team can determine it

Judgment rules (follow strictly):
1. Evidence must QUOTE the original description, or a profile entry that came
   from the patient's answers. Never invent facts. If there is no relevant
   information, the verdict is "unknown" (not "pass").
2. Distinguish criteria about a DIAGNOSIS on record from criteria about
   HISTORY/SYMPTOMS. Symptoms strongly suggesting a diagnosis do not prove a
   formal diagnosis exists; a criterion requiring a formal diagnosis with no
   diagnosis on record is "unknown". A criterion about history/symptoms can
   be judged from the described symptoms directly.
3. Distinguish the time of DIAGNOSIS from the time of SYMPTOM ONSET.
4. "post_enrollment" always includes:
   - ability/willingness to understand and sign informed consent
   - willingness to participate, attend visits, or comply with follow-up
   - open-ended criteria whose content is not disclosed ("Other",
     "additional criteria are defined in the protocol", etc.)
   - anything decided by the investigator's or treating physician's judgment
     or opinion (e.g. "unacceptable risk in the investigator's judgment")
   - adherence/compliance with medications, supplements, or post-treatment care
   - fitness for surgery or anesthesia ("surgical candidate", "tolerate
     general anesthesia"), which the clinical team evaluates
   - life expectancy estimates (e.g. "life expectancy less than 2 years"):
     the patient cannot know this; it is a clinician's estimate
   - measurements taken at screening or on the study day
5. For a criterion with sub-conditions, check EVERY sub-condition one by one
   and judge the criterion from the sub-condition results. Do not skip any.
6. After judging all criteria, re-check your own verdicts for contradictions
   or over-inference (claiming more than the evidence supports), and fix them
   before answering.
7. An absence of mention for an EXCLUSION criterion is "unknown", not "pass"
   — unless the description logically rules it out (e.g. sex, age).
8. BE CONSERVATIVE about inference: judge "pass" or "fail" only from facts
   explicitly stated, or from direct demographic facts (age, sex). Indirect
   reasoning — timeline arithmetic (e.g. "3-week history, so cannot have had
   6 months of treatment"), developmental assumptions (e.g. "an infant cannot
   fill in a survey"), or clinical-knowledge deductions about unmentioned
   facts — is NOT enough to confirm; such criteria stay "unknown".
9. The profile's "suspected_diagnosis" is an INFERENCE, not a fact. Never use
   it as evidence to confirm or rule out any condition. Do not conclude that a
   disease is absent (e.g. "no malignancy") or of a certain type (e.g. "not
   exudative") because the suspected diagnosis is something else; such
   criteria stay "unknown" unless the description states it.
10. Test values, scores, and measurements (e.g. creatinine, FVC, DLCO, pain
   scores) that are not given are "unknown" — a prior result may exist in the
   patient's records. Use "post_enrollment" only when the criterion itself
   requires a measurement at screening or on the study day.

Respond with ONLY a JSON array, one entry per criterion, no other text:
[
  {
    "criterion_id": "<id>",
    "verdict": "pass" | "fail" | "unknown" | "post_enrollment",
    "evidence": "<quote, or why it is unknown/post_enrollment>",
    "sub_condition_notes": ["<judgment per sub-condition, if any>", ...]
  },
  ...
]"""

# v2 프롬프트 (2026-10-08 회의 결정 반영, Opus 5로 goldset v1 기준 90.2%). 비교용으로 남겨 둠
SYSTEM_PROMPT_V2 = """You are a clinical trial eligibility matching agent.

You receive a structured patient profile and a list of parsed eligibility
criteria. For EVERY criterion (and every sub-condition), judge whether the
patient passes it, and give evidence.

Verdicts (exactly one per criterion):
- "pass": it is confirmed the patient is NOT excluded by this criterion
- "fail": it is confirmed the patient IS excluded by this criterion
- "unknown": the information could be obtained by asking the patient now,
  but is not in the profile
- "post_enrollment": the information only comes into existence after the
  patient applies (screening diaries, on-site tests, investigator's judgment)

Judgment rules (follow strictly):
1. Evidence must QUOTE the patient profile. Never invent facts that are not
   in the profile. If there is no relevant information, the verdict is
   "unknown" (not "pass").
2. Distinguish criteria about a DIAGNOSIS on record from criteria about
   HISTORY/SYMPTOMS. Symptoms strongly suggesting a diagnosis do not prove a
   formal diagnosis exists; a criterion requiring a formal diagnosis with no
   diagnosis on record is "unknown". A criterion about history/symptoms can
   be judged from the described symptoms directly.
3. Distinguish the time of DIAGNOSIS from the time of SYMPTOM ONSET.
4. "post_enrollment" includes investigator's judgment, on-site measurements,
   and screening-period requirements. It ALSO includes, always:
   - ability/willingness to understand and sign informed consent
   - willingness to participate, attend visits, or comply with follow-up
   - open-ended criteria whose content is not disclosed ("Other",
     "additional criteria are defined in the protocol", etc.)
5. For a criterion with sub-conditions, check EVERY sub-condition one by one
   and judge the criterion from the sub-condition results. Do not skip any.
6. After judging all criteria, re-check your own verdicts for contradictions
   or over-inference (claiming more than the profile supports), and fix them
   before answering.
7. An absence of mention for an EXCLUSION criterion is "unknown", not "pass"
   — unless the profile logically rules it out (e.g. sex, age).
8. BE CONSERVATIVE about inference: judge "pass" or "fail" only from facts
   explicitly stated in the profile, or from direct demographic facts (age,
   sex). Indirect reasoning — timeline arithmetic (e.g. "3-week history, so
   cannot have had 6 months of treatment"), developmental assumptions, or
   clinical-knowledge deductions about unmentioned facts — is NOT enough to
   confirm; such criteria stay "unknown".

Respond with ONLY a JSON array, one entry per criterion, no other text:
[
  {
    "criterion_id": "<id>",
    "verdict": "pass" | "fail" | "unknown" | "post_enrollment",
    "evidence": "<quote from the patient profile, or why it is unknown/post_enrollment>",
    "sub_condition_notes": ["<judgment per sub-condition, if any>", ...]
  },
  ...
]"""


def match(profile: dict, criteria: list[dict], case_text: str | None = None,
          system_prompt: str | None = None, answers: list[dict] | None = None) -> list[dict]:
    """기준별 판정 리스트를 반환한다.

    case_text: 환자 원문. 넣으면 판정 근거를 원문에서 인용하고, 프로필의 추정 진단을
               사실처럼 쓰는 실수를 줄인다 (v3). 넣지 않아도 동작한다 (이전 호출 호환).
    system_prompt: 비교 실험용. 기본은 v3 (SYSTEM_PROMPT).
    answers: 질문 루프의 환자 답변 [{"id": "Q1", "question": ..., "answer": ...}].
             넣으면 판정 근거에 'Q1 answer: "..."'처럼 답변을 인용한다 (6번 재평가, 2026-10-15).
    """
    return ask_json(system_prompt or SYSTEM_PROMPT, build_user_message(profile, criteria, case_text, answers))


# 답변 안내는 시스템 프롬프트가 아니라 사용자 메시지에 넣는다
# → 답변이 없을 때는 v3 평가(172/173)와 똑같은 요청이 나간다
ANSWERS_HEADER = """PATIENT ANSWERS TO SCREENING QUESTIONS (authoritative; newer than the description):
- Treat each answer as a fact stated by the patient. Quote it as evidence, e.g. 'Q1 answer: "..."'.
- If the patient says they are unsure or have not checked, keep that criterion "unknown".
- Judge only from what the answer states; do not infer beyond it."""


def build_user_message(profile: dict, criteria: list[dict], case_text: str | None = None,
                       answers: list[dict] | None = None) -> str:
    """판정 요청의 사용자 메시지 (match()와 배치 평가가 같이 쓴다)."""
    parts = []
    if case_text:
        parts.append("ORIGINAL PATIENT DESCRIPTION (authoritative):\n" + case_text)
    if answers:
        parts.append(ANSWERS_HEADER + "\n" + json.dumps(answers, ensure_ascii=False, indent=2))
    parts.append("PATIENT PROFILE (derived; may include facts from the patient's answers):\n"
                 + json.dumps(profile, ensure_ascii=False, indent=2))
    parts.append("ELIGIBILITY CRITERIA:\n" + json.dumps(criteria, ensure_ascii=False, indent=2))
    return "\n\n".join(parts)


def final_judgment(judgments: list[dict]) -> str:
    """기준별 판정을 모아 최종 판단 4단계를 계산한다 (LLM 아닌 코드 규칙).

    - fail 하나라도 있으면 → ineligible (부적격)
    - unknown 남아 있으면 → insufficient_info (정보 부족 → 질문 생성 대상)
    - post_enrollment만 남으면 → probably_eligible (적격 가능, 등록 후 확인 필요)
    - 전부 pass면 → eligible (적격)
    """
    verdicts = {j["verdict"] for j in judgments}
    if "fail" in verdicts:
        return "ineligible"
    if "unknown" in verdicts:
        return "insufficient_info"
    if "post_enrollment" in verdicts:
        return "probably_eligible"
    return "eligible"


def match_with_rules(profile: dict, criteria: list[dict], case_text: str | None = None,
                     answers: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """LLM 판정 후, 코드로 확실히 판정되는 기준(나이, 임신·수유)을 코드 결과로 덮어쓰고,
    출력 검사(validate_judgments)로 빠진 기준·이상한 값을 모름으로 채운다.

    반환: (기준 순서대로 정리한 판정 목록, 코드 판정·출력 검사가 바꾼 내역).
    코드 판정에는 "checked_by": "code", 출력 검사로 고친 판정에는 "checked_by": "validator"가 붙는다.
    """
    from src.tools.rule_checks import apply_code_checks, code_judgments

    llm = match(profile, criteria, case_text=case_text, answers=answers)
    judgments, changed = apply_code_checks(validate_shape(llm), code_judgments(profile, criteria))
    judgments, fixes = validate_judgments(criteria, judgments)
    return judgments, changed + fixes


VALID_VERDICTS = {"pass", "fail", "unknown", "post_enrollment"}


def validate_shape(judgments) -> list[dict]:
    """AI가 배열 대신 {"judgments": [...]} 같은 객체로 답해도 판정 목록만 꺼낸다."""
    if isinstance(judgments, dict):
        judgments = next((v for v in judgments.values() if isinstance(v, list)), [])
    return [j for j in judgments if isinstance(j, dict)] if isinstance(judgments, list) else []


def validate_judgments(criteria: list[dict], judgments: list[dict]) -> tuple[list[dict], list[dict]]:
    """AI 판정 출력을 코드로 검사한다 (API 호출 없음, 무료).

    - 빠진 기준 → unknown (빠진 탈락 기준 때문에 부적격 환자가 '적격'으로 나오는 안전 오류 방지)
    - 이상한 판정값 → unknown
    - 같은 기준이 두 번 → 앞의 것만 / 기준 목록에 없는 ID → 버림
    고친 판정에는 "checked_by": "validator"가 붙는다.
    반환: (기준 순서대로 정리한 판정 목록, 고친 내역 [{"criterion_id", "llm", "fixed", "reason"}])
    """
    ids = [c["id"] for c in criteria]
    by_upper = {cid.upper(): cid for cid in ids}
    kept: dict[str, dict] = {}
    fixes = []
    for j in validate_shape(judgments):
        raw = str(j.get("criterion_id", "")).strip()
        cid = by_upper.get(raw.upper())
        verdict = j.get("verdict")
        if cid is None:
            fixes.append({"criterion_id": raw, "llm": verdict, "fixed": None, "reason": "기준 목록에 없는 ID → 버림"})
            continue
        if cid in kept:
            fixes.append({"criterion_id": cid, "llm": verdict, "fixed": None, "reason": "같은 기준 중복 → 앞의 것만"})
            continue
        j = dict(j, criterion_id=cid)
        if verdict not in VALID_VERDICTS:
            fixes.append({"criterion_id": cid, "llm": verdict, "fixed": "unknown", "reason": "이상한 판정값 → 모름"})
            j.update(verdict="unknown", checked_by="validator",
                     evidence=f"(판정값 '{verdict}'이 올바르지 않아 모름 처리) {j.get('evidence', '')}".strip())
        kept[cid] = j
    for cid in ids:
        if cid not in kept:
            kept[cid] = {"criterion_id": cid, "verdict": "unknown", "checked_by": "validator",
                         "evidence": "AI 출력에 이 기준이 없음 → 안전하게 모름 처리", "sub_condition_notes": []}
            fixes.append({"criterion_id": cid, "llm": None, "fixed": "unknown", "reason": "AI 출력 누락 → 모름"})
    return [kept[cid] for cid in ids], fixes
