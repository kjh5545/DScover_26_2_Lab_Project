"""[5b] 프로필 갱신 에이전트 (질문 루프의 후반부).

질문 생성 에이전트의 질문에 환자가 답하면, 그 답변을 구조화된
프로필에 반영한다. 갱신된 프로필로 매칭 에이전트를 다시 돌리면
"모름"이었던 기준들이 통과/탈락으로 바뀐다 (재평가).

규칙: 답변에 있는 내용만 추가한다. 기존 정보는 지우지 않는다.
"모르겠다"는 답은 프로필에 "환자도 모름"으로 기록한다
(다시 물어보지 않도록 — 실험 4의 "(유지)" 표시와 같은 취지).
"""

import json

from src.llm import ask_json

SYSTEM_PROMPT = """You are a patient-profile update agent.

You receive a structured patient profile and a list of question-answer pairs
from an interview with the patient. Merge the new information into the profile.

Rules:
- Add ONLY what the answers state. Do not invent or infer beyond the answer.
- Never delete existing profile entries; only add or refine.
- Put diagnoses/conditions the patient confirms into "history",
  medications into "medications", test results into "labs",
  symptoms into "findings".
- If the patient explicitly denies something (e.g. "no other cancer"),
  record it as a negative fact, e.g. "denies: other cancer diagnosis".
- If the patient does not know, record "patient unsure: <topic>" in
  "history" so we do not ask again.
- Keep all original fields and formats of the profile.

Respond with ONLY the full updated profile JSON object, no other text."""


def update_profile(profile: dict, qa_pairs: list[dict]) -> dict:
    """답변을 반영한 새 프로필을 반환한다. qa_pairs: [{"question","answer"}, ...]"""
    user = (
        "CURRENT PROFILE:\n"
        + json.dumps(profile, ensure_ascii=False, indent=2)
        + "\n\nINTERVIEW (question-answer pairs):\n"
        + json.dumps(qa_pairs, ensure_ascii=False, indent=2)
    )
    return ask_json(SYSTEM_PROMPT, user)
