"""1번 에이전트: 환자 정보 이해. 환자 줄글 → PatientProfile.

사용 예:
    python -m agents.patient_agent                 # synthetic-patients.json 10명 전체
    python -m agents.patient_agent --ids S004 S008
"""

import argparse
import json
from pathlib import Path

from .llm import ROOT, structured
from .schemas import PatientProfile

SYSTEM = """당신은 임상시험 매칭 시스템의 환자 정보 정리 담당입니다. 짧은 영어 환자 설명을 읽고 구조화된 프로필을 만듭니다.

규칙:
- 환자 설명에 있는 내용만 정리합니다. 없는 정보를 지어내지 마세요.
- quote와 quotes에는 환자 설명의 영어 원문 표현을 한 글자도 바꾸지 않고 넣습니다.
- 추정 진단은 증상·소견에서 추론한 것이며, 공식 진단이 아니라는 점을 reasoning에 드러내세요.
- 추정 진단의 name_en은 ClinicalTrials.gov에서 검색이 잘 되는 일반적인 질환명으로 씁니다 (예: "acute pancreatitis", "Graves disease").
- missing_info에는 이 환자에게 맞는 임상시험을 판정할 때 흔히 필요하지만 설명에 없는 정보를 적습니다."""


def understand(patient_id: str, text: str) -> tuple[PatientProfile, dict]:
    user = f"환자 ID: {patient_id}\n환자 설명: {text}"
    profile, usage = structured(PatientProfile, SYSTEM, user, effort="medium")
    profile.patient_id = patient_id
    return profile, usage


def check_quotes(profile: PatientProfile, text: str) -> list[str]:
    """근거 인용이 원문에 실제로 있는지 확인한다. 없는 인용은 지어낸 근거일 수 있다."""
    quotes = [e.quote for group in (profile.symptoms, profile.findings, profile.history, profile.medications) for e in group]
    quotes += [q for d in profile.suspected_diagnoses for q in d.quotes]
    low = text.lower()
    return [q for q in quotes if q.lower() not in low]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--out", default=str(ROOT / "outputs" / "patient_profiles.json"))
    args = ap.parse_args()

    topics = json.loads((ROOT / "synthetic-patients.json").read_text(encoding="utf-8"))["topics"]
    if args.ids:
        topics = [t for t in topics if t["num"] in args.ids]

    results, total = {}, {"input": 0, "output": 0}
    for t in topics:
        profile, usage = understand(t["num"], t["title"])
        bad = check_quotes(profile, t["title"])
        total = {k: total[k] + usage[k] for k in total}
        results[t["num"]] = profile.model_dump()
        dx = ", ".join(f"{d.name_en}({d.confidence})" for d in profile.suspected_diagnoses)
        print(f"{t['num']} | {profile.age_years}세 {profile.sex} | {dx}" + (f" | ⚠ 원문에 없는 인용 {len(bad)}개: {bad}" if bad else ""))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    cost = total["input"] / 1e6 * 2 + total["output"] / 1e6 * 10  # Sonnet 5.5 기준
    print(f"\n저장: {out}\n토큰: 입력 {total['input']}, 출력 {total['output']} · 약 ${cost:.3f}")


if __name__ == "__main__":
    main()
