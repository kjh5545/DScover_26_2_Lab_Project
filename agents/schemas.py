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


# ---------- 3번 기준 파싱 (아직 미구현, 형식만 약속) ----------


class SubCondition(BaseModel):
    sub_id: str = Field(description="원래 기준 ID에 붙임. 예: E3-a")
    text: str


class ParsedCriterion(BaseModel):
    id: str = Field(description="I1, E1처럼 원문 순서대로. 팀원 레이블 시트의 ID와 같은 규칙")
    kind: Literal["inclusion", "exclusion"]
    original: str = Field(description="기준 원문 그대로")
    summary_ko: str
    category: Literal["medical", "time_or_number", "administrative", "post_enrollment"] = Field(
        description="의학 정보 / 시간·수치 계산 / 행정·법적 / 등록 후에야 알 수 있는 정보")
    sub_conditions: list[SubCondition] = Field(default=[], description="한 줄에 조건이 여러 개면 쪼갬. 하나면 빈 배열")


class ParsedTrial(BaseModel):
    nct_id: str
    criteria: list[ParsedCriterion]
