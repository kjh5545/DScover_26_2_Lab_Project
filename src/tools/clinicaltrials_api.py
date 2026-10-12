"""ClinicalTrials.gov API v2 클라이언트.

미국 NIH가 운영하는 공개 임상시험 데이터베이스에서 시험 정보를 가져온다.
인증 불필요, 무료. 문서: https://clinicaltrials.gov/data-api/api
"""

import requests

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"

# 매칭에 필요한 필드만 요청해서 응답 크기를 줄인다
DEFAULT_FIELDS = [
    "NCTId",
    "BriefTitle",
    "BriefSummary",
    "OverallStatus",
    "EligibilityModule",  # 선정/제외 기준, 나이, 성별 등
    "ConditionsModule",   # 대상 질환
    "Phase",              # 시험 단계 (1상/2상/3상)
]


def search_trials(condition: str, status: str = "RECRUITING", max_results: int = 20) -> list[dict]:
    """질환명으로 임상시험을 검색해 정리된 dict 리스트로 반환한다.

    Args:
        condition: 질환 검색어 (영어, 예: "acute pancreatitis")
        status: 모집 상태 필터 (기본: 모집 중인 시험만)
        max_results: 최대 결과 수 (페이지당 최대 1000)
    """
    params = {
        "query.cond": condition,
        "filter.overallStatus": status,
        "pageSize": str(max_results),
        "fields": ",".join(DEFAULT_FIELDS),
    }
    resp = requests.get(
        BASE_URL,
        params=params,
        headers={"User-Agent": "clinical-trial-matcher/0.1"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    return [_flatten_study(s) for s in data.get("studies", [])]


def _flatten_study(study: dict) -> dict:
    """API 응답의 중첩 구조를 매칭에 쓰기 좋은 평평한 형태로 변환한다."""
    protocol = study.get("protocolSection", {})
    ident = protocol.get("identificationModule", {})
    elig = protocol.get("eligibilityModule", {})
    desc = protocol.get("descriptionModule", {})
    cond = protocol.get("conditionsModule", {})
    status = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})

    return {
        "nct_id": ident.get("nctId"),
        "title": ident.get("briefTitle"),
        "summary": desc.get("briefSummary"),
        "conditions": cond.get("conditions", []),
        "overall_status": status.get("overallStatus"),
        "phases": design.get("phases", []),
        "eligibility_criteria": elig.get("eligibilityCriteria"),
        "minimum_age": elig.get("minimumAge"),
        "maximum_age": elig.get("maximumAge"),
        "sex": elig.get("sex"),
        "healthy_volunteers": elig.get("healthyVolunteers"),
    }
