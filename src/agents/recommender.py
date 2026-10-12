"""[6] 추천 에이전트 + [7] 결과 설명 에이전트.

- 순위 결정은 **코드 규칙** (결정적·재현 가능 — 킥오프: "deterministic priority order"):
  1) 최종 판단 등급순 (적격 > 적격 가능 > 정보 부족 > 부적격 제외)
  2) 같은 등급이면 통과 비율 높은 순
  3) 그래도 같으면 모름 개수 적은 순 (질문 부담이 적음)
- 설명 리포트 생성만 LLM: 어느 기준이 어느 환자 정보와 맞았는지 한국어로 풀어쓰기.
- 적합한 시험이 없으면 억지로 추천하지 않고 "없음"을 근거와 함께 (S006/S009 케이스 대비).
"""

import json

from src.llm import ask

JUDGMENT_ORDER = {"eligible": 0, "probably_eligible": 1, "insufficient_info": 2, "ineligible": 3}

EXPLAIN_SYSTEM = """You are the final report writer for a clinical trial
recommendation system. Write in Korean.

You receive a ranked list of screened trials for one patient. Write a short
report (환자용 아님, 연구팀/의료진용 요약):
- 추천 순위대로 각 시험을 2~3문장으로: 왜 이 순위인지, 어떤 기준이 환자의
  어떤 정보와 맞았는지(인용), 남은 미확인 항목은 무엇인지.
- 부적격 시험은 "제외된 시험"으로 따로 묶고 탈락 사유 기준을 명시.
- 추천할 시험이 없으면 그 이유를 명확히.
- 마지막 줄에 반드시: "※ 본 결과는 의학적 자문이 아닌 참고용입니다. 실제
  임상시험 참여 여부는 반드시 의료진과 상의하세요."
- 과장 없이, 프로필에 없는 사실을 지어내지 말 것."""


def rank_trials(screenings: list[dict]) -> dict:
    """스크리닝 결과 목록을 순위 매긴다 (LLM 없이 코드로)."""

    def sort_key(s: dict):
        judgments = s["judgments"]
        total = len(judgments) or 1
        passes = sum(1 for j in judgments if j["verdict"] == "pass")
        unknowns = sum(1 for j in judgments if j["verdict"] == "unknown")
        return (JUDGMENT_ORDER[s["final_judgment"]], -passes / total, unknowns)

    ranked = sorted(screenings, key=sort_key)
    recommended = [s for s in ranked if s["final_judgment"] != "ineligible"]
    excluded = [s for s in ranked if s["final_judgment"] == "ineligible"]
    return {"recommended": recommended, "excluded": excluded}


def explain(profile: dict, ranking: dict) -> str:
    """추천 결과를 한국어 리포트로 풀어쓴다 (LLM 1회)."""
    # 리포트에 필요한 요약만 추려서 토큰 절약
    def summarize(s: dict) -> dict:
        return {
            "nct_id": s["nct_id"],
            "title": s["title"],
            "final_judgment": s["final_judgment"],
            "judgments": s["judgments"],
        }

    payload = {
        "patient_profile": profile,
        "recommended_in_order": [summarize(s) for s in ranking["recommended"]],
        "excluded": [summarize(s) for s in ranking["excluded"]],
    }
    return ask(EXPLAIN_SYSTEM, json.dumps(payload, ensure_ascii=False, indent=2))
