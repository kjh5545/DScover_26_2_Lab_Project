"""4번 매칭·판정 에이전트 (임시 v0: 평가 도구의 v3 프롬프트를 그대로 감쌈).

담당: 주희. 프롬프트 개선은 eval/rules_prompt_*.md에서 하고, 여기서는 쓸 버전만 고른다.
해준은 파이프라인에서 judge()만 부르면 된다. 입력·출력 형식(schemas.py)은 바뀌지 않는다.
"""

from .llm import ROOT, structured
from .schemas import TrialJudgment

RULES_FILE = ROOT / "eval" / "rules_prompt_v3.md"

OUTPUT_INSTRUCTION = (
    "[출력 형식]\n"
    "지정된 JSON 형식으로만 답하세요. judgments에는 기준 ID마다 하나씩 판정과 근거를, "
    "final에는 적격 / 부적격 / 정보 부족 중 하나를, questions에는 확인 질문과 해결되는 기준 ID를 넣으세요. "
    "질문이 없으면 빈 배열로 두세요."
)


def judge(patient_text: str, criteria_block: str, effort: str = "high") -> tuple[TrialJudgment, dict]:
    """환자 설명 + 기준 묶음(parse_rules.to_prompt_block 결과) → 기준별 판정, 최종 판단, 질문."""
    # 평가 도구(eval/run_eval.py)와 같은 배치: 규칙 → 출력 형식 → 환자 → 기준을 한 메시지에 넣는다.
    # 평가 때와 조건이 같아야 평가 점수를 그대로 믿을 수 있다.
    rules = RULES_FILE.read_text(encoding="utf-8").strip()
    user = f"{rules}\n\n{OUTPUT_INSTRUCTION}\n\n[환자]\n{patient_text}\n\n{criteria_block}"
    return structured(TrialJudgment, None, user, effort=effort)
