"""[3] 기준 파싱 에이전트.

임상시험의 eligibility criteria 원문(자유 텍스트)을 받아
개별 조건(atomic criterion) 리스트로 분해한다.

킥오프 문서의 설계를 따른다:
- 복합 기준은 하위 조건(sub_conditions)까지 쪼갠다 (실험 4: 하위 조건 누락이 실행마다 달라서
  파싱 단계에서 미리 쪼개두고, 매칭 에이전트는 목록대로만 확인하게 한다)
- 각 조건에 유형 태그: medical / temporal_numeric / administrative / post_enrollment
- 판정에 필요한 환자 정보(needed_info)도 함께 추출 → 질문 생성의 재료
"""

from src.llm import ask_json

SYSTEM_PROMPT = """You are a clinical trial eligibility criteria parser.

Given the raw eligibility criteria text of a clinical trial, split it into
individual atomic criteria. Each atomic criterion must be a single,
independently checkable condition.

Rules:
- Split compound conditions ("A and B", lists of drugs/diseases) into
  sub_conditions so that nothing is missed during matching.
- Keep the original meaning; do not invent conditions that are not stated.
- Classify each criterion as "inclusion" or "exclusion".
- Assign ids: I1, I2, ... for inclusion, E1, E2, ... for exclusion.
- Tag each criterion with a category:
  - "medical": diagnosis, symptoms, medical history, lab values
  - "temporal_numeric": durations, frequencies, washout periods, counts
  - "administrative": residence/location, consent capability, legal requirements
  - "post_enrollment": information that only comes into existence after the
    patient applies (screening diaries, investigator's judgment, on-site tests)
- For each criterion, list what patient information would be needed to check
  it (e.g. "age", "diagnosis", "lab: lipase", "medication history").

Respond with ONLY a JSON array, no other text:
[
  {
    "id": "I1",
    "type": "inclusion",
    "category": "medical",
    "text": "<criterion as stated>",
    "sub_conditions": ["<sub condition>", ...],
    "needed_info": ["<info>", ...]
  },
  ...
]"""


def parse_criteria(eligibility_text: str) -> list[dict]:
    """eligibility criteria 원문을 개별 조건 리스트로 분해한다."""
    return ask_json(SYSTEM_PROMPT, eligibility_text)
