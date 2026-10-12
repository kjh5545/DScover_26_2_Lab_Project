"""에이전트끼리 주고받는 데이터 형식 정의 (로드맵 1단계).

킥오프 문서의 초안을 따른다. 필드는 팀 회의에서 확정 예정.
이 모듈은 "형식의 기준점" 역할 — 각 에이전트의 프롬프트와 출력 검증이 여기를 참조한다.
"""

# 기준별 판정 4단계 (사전 실험 0에서 도출)
VERDICTS = [
    "pass",             # 통과: 이 기준 때문에 탈락하지 않음이 확인됨
    "fail",             # 탈락: 이 기준 때문에 탈락함이 확인됨
    "unknown",          # 모름: 지금 물어보면 알 수 있지만 정보가 없음 → 질문 생성 대상
    "post_enrollment",  # 등록 후 확인: 시험 지원 후에야 생기는 정보 (연구자 판단, 방문 검사 등)
]

# 기준 유형 (사전 실험 0에서 도출)
CRITERION_CATEGORIES = [
    "medical",          # 의학 정보 (진단, 증상, 병력, 검사 수치)
    "temporal_numeric", # 시간·수치 계산 (기간, 빈도, 휴약 기간)
    "administrative",   # 행정·지리 (거주지, 동의 능력, 법적 요건)
    "post_enrollment",  # 등록 후 확인 (스크리닝 일지, 연구자 판단)
]

# 최종 판단 4단계 (제안 1)
FINAL_JUDGMENTS = [
    "eligible",               # 적격: 모든 기준 통과
    "probably_eligible",      # 적격 가능: 등록 후 확인만 남음
    "insufficient_info",      # 정보 부족: 모름이 남음
    "ineligible",             # 부적격: 탈락이 하나라도 있음
]

# 예시 데이터 형식 (문서 초안 그대로)
EXAMPLE = {
    "patient": {
        "id": "S005", "age": 34, "sex": "F",
        "diagnosis": "migraine with aura",
        "findings": ["visual scotomata", "photophobia"],
    },
    "criterion": {
        "id": "E1", "type": "exclusion", "category": "medical",
        "text": "Migraine with aura",
        "sub_conditions": [],          # 복합 기준이면 하위 조건 목록 (실험 4: 누락 방지)
        "needed_info": ["diagnosis"],  # 판정에 필요한 환자 정보
    },
    "judgment": {
        "criterion_id": "E1", "verdict": "fail",
        "evidence": "preceded by visual scotomata",  # 환자 문장에서 그대로 인용
    },
    "question": {
        "criterion_id": "I3",
        "text": "최근 3개월 동안 한 달에 두통이 있던 날은 며칠인가요?",
    },
}
