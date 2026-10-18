"""환자 역할 시뮬레이터 (테스트·데모용 — 시스템 에이전트 아님).

질문 루프를 자동으로 검증하려면 질문에 답해줄 "환자"가 필요하다.
실제 데모에서는 사람이 답하지만, 개발·평가 중에는 이 시뮬레이터가
미리 정의된 사실관계(fact sheet)만 보고 환자처럼 답한다.

킥오프 실험 4의 "답변 세트"를 자동화한 것. fact sheet를 바꿔가며
함정 답변(예: 결론을 뒤집는 복용약)을 테스트할 수 있다.
"""

import json

from src.llm import ask_json

SYSTEM_PROMPT = """You are role-playing a PATIENT answering screening
questions for a clinical trial, in Korean.

You receive a FACT SHEET about yourself and a list of questions.

Rules:
- Answer each question in 1-2 short, natural sentences, like a real patient.
- Use ONLY the fact sheet. If the fact sheet does not cover the question,
  answer that you don't know ("잘 모르겠어요", "그건 기억이 잘 안 나요" 등).
- Something missing from the fact sheet is NOT a "no". Say "no", "never",
  "들은 적 없어요", "없었어요" only when the fact sheet states it (e.g. "urine
  culture was negative"). Do not infer a "no" from silence.
- If a question asks several things, answer the parts the fact sheet covers
  and say you don't know the rest.
- When the fact sheet gives a test result, repeat its qualifiers as written
  (e.g. "hemoglobin-corrected", "of predicted"), in simple words.
- Do not volunteer information that was not asked.
- Do not use medical jargon a patient would not use.

Respond with ONLY a JSON array, same order as the questions:
[{"question": "<the question>", "answer": "<your answer in Korean>"}, ...]"""


def answer_questions(fact_sheet: str, questions: list[dict]) -> list[dict]:
    """질문 목록에 환자 입장에서 답한다."""
    user = (
        "FACT SHEET (나에 대한 사실):\n"
        + fact_sheet
        + "\n\nQUESTIONS:\n"
        + json.dumps([q["question"] for q in questions], ensure_ascii=False, indent=2)
    )
    return ask_json(SYSTEM_PROMPT, user)


# S004 (68세 남성, 방광암 의심) 검증용 사실관계.
# 케이스 원문과 모순되지 않게 지은 가상 설정 — 일부는 일부러 "모름"으로 둠.
S004_FACT_SHEET = """
- 68세 남성, 담배를 45년간 하루 한 갑 정도 피웠고 지금도 피움
- 3주 전부터 소변에 피가 섞여 나왔는데 아프지는 않았음
- 동네 병원에서 CT 찍었더니 방광에 혹이 있다고 들음
- 아직 조직검사(내시경으로 떼어보는 검사)는 안 받았고, 큰 병원 예약만 한 상태
- 암이 퍼졌는지(병기)는 아직 모름
- 지병: 혈압이 높아서 암로디핀을 매일 복용 중. 그 외 지병 없음
- 암 진단을 받은 적 없고, 항암치료나 방사선치료를 받은 적도 없음
- 최근 1년 내 피검사는 안 해봐서 신장 기능 수치는 모름
- 다른 임상시험에 참여하고 있지 않음
- 거동에 문제 없고 혼자 생활 가능
"""
