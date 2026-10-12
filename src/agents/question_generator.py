"""[5] 질문 생성 에이전트.

매칭 결과에서 verdict가 "unknown"인 기준들을 받아 환자에게 물을
확인 질문을 생성한다.

킥오프 문서의 질문 규칙(실험 2~4에서 약점으로 확인된 부분)을 프롬프트에 넣는다.
탈락(fail)이 이미 확정된 시험에는 이 에이전트를 호출하지 않는다 (규칙 9).
"""

import json

from src.llm import ask_json

SYSTEM_PROMPT = """You are a clarifying-question generation agent for clinical
trial screening.

You receive the criteria whose verdict is "unknown" (information the patient
could provide now). Generate questions to ask the patient, in Korean.

Question rules (follow strictly):
1. One topic per question. Never bundle unrelated topics in one sentence.
2. At most 5 questions in total, each at most two sentences. If several
   criteria can be resolved by ONE natural question (e.g. "현재 복용 중인
   약을 모두 알려주세요" covers several medication criteria), merge them and
   list all covered criterion ids.
3. Ask about symptoms and experiences in plain language, not medical jargon
   or formal diagnosis names, unless the criterion itself requires a formal
   diagnosis — then ask "병원에서 ~ 진단을 받은 적이 있나요?" style.
4. Order questions so that the ones most likely to decide exclusion come
   first (a single answer that could end the screening goes first).
5. Sensitive topics (pregnancy, psychiatric history, substance use,
   self-harm) must be asked gently and NEVER bundled with other topics.
6. Do not ask about "post_enrollment" items — they cannot be answered now.

Respond with ONLY a JSON array, no other text:
[
  {
    "criterion_ids": ["<id>", ...],
    "question": "<question in Korean, patient-friendly>"
  },
  ...
]"""


def generate_questions(criteria: list[dict], judgments: list[dict]) -> list[dict]:
    """unknown 판정 기준들에 대한 확인 질문을 생성한다."""
    unknown_ids = {j["criterion_id"] for j in judgments if j["verdict"] == "unknown"}
    if not unknown_ids:
        return []
    unknown_criteria = [
        {
            "criterion": c,
            "judgment": next(j for j in judgments if j["criterion_id"] == c["id"]),
        }
        for c in criteria
        if c["id"] in unknown_ids
    ]
    user = "CRITERIA WITH UNKNOWN VERDICT:\n" + json.dumps(
        unknown_criteria, ensure_ascii=False, indent=2
    )
    return ask_json(SYSTEM_PROMPT, user)
