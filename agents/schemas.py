"""에이전트끼리 주고받는 데이터 형식.

흐름: 환자 줄글 → PatientProfile (1번) → TrialCandidate 목록 (2번)
      → ParsedTrial (3번) → 판정 (4번, eval/의 v3 프롬프트) → 질문·재평가·추천 (5–7번)

두 사람이 나눠 개발할 때 이 파일이 약속입니다. 필드를 바꿀 때는 서로 알리고 바꿉니다.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

# ---------- 1번 환자 정보 이해 ----------


class Evidence(BaseModel):
    text: str = Field(description="한국어로 정리한 내용")
    quote: str = Field(description="환자 설명 원문에서 그대로 가져온 근거 표현 (영어 원문 그대로)")


class Diagnosis(BaseModel):
    name_en: str = Field(description="영어 질환명. ClinicalTrials.gov 검색에 그대로 쓸 수 있는 일반적인 이름")
    name_ko: str
    confidence: Literal["high", "medium", "low"]
    reasoning: str = Field(description="이 진단을 추정한 이유 한두 문장")
    quotes: list[str] = Field(description="근거가 된 환자 설명 원문 표현들 (영어 원문 그대로)")


class PatientProfile(BaseModel):
    patient_id: str
    age_years: Optional[float] = Field(description="나이(년). 생후 3개월이면 0.25. 알 수 없으면 null")
    age_text: str = Field(description="원문의 나이 표현 그대로 (예: '3-month-old')")
    sex: Literal["male", "female", "unknown"]
    symptoms: list[Evidence] = Field(description="환자가 호소하는 증상")
    findings: list[Evidence] = Field(description="신체검사·검사·영상 소견")
    history: list[Evidence] = Field(description="과거력, 위험 요인, 생활습관 (예: 흡연, 음주, 당뇨)")
    medications: list[Evidence] = Field(description="언급된 약물. 없으면 빈 배열")
    suspected_diagnoses: list[Diagnosis] = Field(description="가능성 높은 순서. 1–3개")
    missing_info: list[str] = Field(description="임상시험 판정에 흔히 필요하지만 설명에 없는 정보 (예: 진단 확정 여부, 복용약, 임신 여부)")


# ---------- 2번 후보 검색 ----------


class TrialCandidate(BaseModel):
    nct_id: str
    title: str
    conditions: list[str]
    study_type: str
    phases: list[str] = []
    min_age_years: Optional[float] = None
    max_age_years: Optional[float] = None
    sex: str = "ALL"
    countries: list[str] = []
    eligibility_text: str
    url: str
    search_query: str = Field(description="이 시험을 찾은 검색어")
    filter_notes: list[str] = Field(default=[], description="코드 필터 결과 메모 (예: 나이 범위 밖)")


# ---------- 3번 기준 파싱 ----------
# 지금은 규칙 기반 파서(parse_rules.py)가 id·kind·original만 채운다.
# summary_ko, category, sub_conditions는 LLM 파서(parse_agent.py, 예정)가 채울 자리다.


class SubCondition(BaseModel):
    sub_id: str = Field(description="원래 기준 ID에 붙임. 예: E3-a")
    text: str


class ParsedCriterion(BaseModel):
    id: str = Field(description="I1, E1처럼 원문 순서대로. 팀원 레이블 시트의 ID와 같은 규칙")
    kind: Literal["inclusion", "exclusion"]
    original: str = Field(description="기준 원문 그대로")
    summary_ko: str = ""
    category: Optional[Literal["medical", "time_or_number", "administrative", "post_enrollment"]] = Field(
        default=None, description="의학 정보 / 시간·수치 계산 / 행정·법적 / 등록 후에야 알 수 있는 정보")
    sub_conditions: list[SubCondition] = Field(default=[], description="한 줄에 조건이 여러 개면 쪼갬. 하나면 빈 배열")


class ParsedTrial(BaseModel):
    nct_id: str
    criteria: list[ParsedCriterion]
    parser: str = Field(default="rules", description="어떤 파서가 만들었는지: rules / llm")


# ---------- 4번 매칭·판정 ----------
# 평가 도구(eval/run_eval.py)의 출력 형식과 같다. 판정 단어는 팀 합의(goldset/평가세트_v1.md)를 따른다.

Verdict = Literal["통과", "탈락", "모름", "등록 후 확인"]
FinalVerdict = Literal["적격", "부적격", "정보 부족"]  # "적격 가능(등록 후 확인 필요)" 추가 여부는 실험 후 결정


class CriterionJudgment(BaseModel):
    id: str = Field(description="ParsedCriterion.id와 같은 ID")
    verdict: Verdict
    evidence: str = Field(description="판정 근거. 환자 설명 원문 표현을 따옴표로 인용")


class Question(BaseModel):
    text: str = Field(description="환자가 이해할 수 있는 쉬운 한국어 질문")
    resolves: list[str] = Field(description="이 질문으로 해결되는 기준 ID들")


class TrialJudgment(BaseModel):
    judgments: list[CriterionJudgment]
    final: FinalVerdict
    final_reason: str
    questions: list[Question] = Field(default=[], description="4번이 함께 내는 확인 질문. 5번 질문 생성 에이전트가 생기면 그쪽 결과로 대체")


# ---------- 파이프라인 결과 (해준 담당 pipeline.py의 출력) ----------


class TrialResult(BaseModel):
    candidate: TrialCandidate
    parsed: ParsedTrial
    judgment: Optional[TrialJudgment] = None
    error: Optional[str] = Field(default=None, description="이 시험 처리 중 실패했으면 이유")


class PatientResult(BaseModel):
    patient_id: str
    patient_text: str
    profile: PatientProfile
    trials: list[TrialResult]
    skipped: list[TrialCandidate] = Field(default=[], description="나이·성별 등 하드 필터로 걸러진 시험")
    usage: dict = Field(default={}, description="토큰 사용량 합계 {'input': .., 'output': ..}")
