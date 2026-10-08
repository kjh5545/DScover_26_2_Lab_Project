"""3번 기준 파싱의 규칙 기반 버전 (LLM 없음, 무료).

ClinicalTrials.gov의 기준 원문을 I1, I2 ... / E1, E2 ... 로 나눈다.
레이블 시트를 만들 때 쓴 파서(screening/labeling/_parse.py)와 같은 결과를 낸다 (평가 세트 15개 시험으로 확인).
- 줄 맨 앞의 *, -, 1. 같은 표시가 있는 줄을 기준 하나로 본다
- 들여쓴 하위 항목은 위 기준에 " / "로 이어 붙인다 (기준 하나로 유지)
- "Note:"로 시작하는 줄은 기준이 아니라서 뺀다

나중에 LLM 파서(parse_agent.py)가 하위 조건 쪼개기, 유형 태그, 한국어 요약을 더한다.

사용 예:
    from agents.parse_rules import parse_trial, to_prompt_block
    parsed = parse_trial(candidate.nct_id, candidate.eligibility_text)
    block = to_prompt_block(candidate, parsed)   # 4번 판정 프롬프트에 넣을 기준 문장 묶음
"""

import re

from .schemas import ParsedCriterion, ParsedTrial, TrialCandidate


def _clean(text: str) -> str:
    # ClinicalTrials.gov 마크다운의 이스케이프 문자 제거 (\> \< \- \[ \] \.)
    return re.sub(r"\\([<>\-\[\].])", r"\1", text)


def _split_sections(text: str) -> tuple[str, str]:
    parts = re.split(r"(?im)^\s*exclusion criteria[^\n]*\n", text, maxsplit=1)
    inc = re.sub(r"(?im)^\s*inclusion criteria[^\n]*\n", "", parts[0])
    exc = parts[1] if len(parts) > 1 else ""
    return inc, exc


def _items(block: str) -> list[str]:
    out: list[str] = []
    numbered_siblings = False  # "* 1. ..." 다음에 들여쓴 "2. ..."가 오면 하위 항목이 아니라 같은 수준의 기준
    for line in block.splitlines():
        if not line.strip() or re.match(r"(?i)^\s*note:", line):
            continue
        top = re.match(r"^(\*|-|\d+\.)\s+", line)
        if top:
            numbered_siblings = bool(re.match(r"^(\*|-)\s+\d+\.", line))
            out.append(re.sub(r"^(\*\s+)?(-\s+)?(\d+\.\s*)?", "", line).strip())
        elif re.match(r"^\s+\d+\.\s", line):
            text = re.sub(r"^\s*\d+\.\s*", "", line).strip()
            if numbered_siblings or not out:
                out.append(text)
            else:
                out[-1] += " / " + text
        elif out and re.match(r"^\s+(\*|[a-zA-Z]\))", line) or (out and re.match(r"^\s{2,}", line)):
            out[-1] += " / " + re.sub(r"^\s*(\*|\d+\.|[a-zA-Z]\))\s*", "", line).strip()
        elif out:
            out[-1] += " " + line.strip()
        else:
            out.append(line.strip())
    return [re.sub(r"\s+", " ", o).strip().rstrip(",") for o in out]


def parse_trial(nct_id: str, eligibility_text: str) -> ParsedTrial:
    inc, exc = _split_sections(_clean(eligibility_text or ""))
    crit = [ParsedCriterion(id=f"I{k}", kind="inclusion", original=t) for k, t in enumerate(_items(inc), 1)]
    crit += [ParsedCriterion(id=f"E{k}", kind="exclusion", original=t) for k, t in enumerate(_items(exc), 1)]
    return ParsedTrial(nct_id=nct_id, criteria=crit, parser="rules")


def _age_text(years):
    return "no limit" if years is None else f"{years:g} Years"


def to_prompt_block(candidate: TrialCandidate, parsed: ParsedTrial) -> str:
    """4번 판정 프롬프트에 넣는 기준 묶음. 평가 세트(goldset)와 같은 형식."""
    locs = ", ".join(candidate.countries[:5]) + (" 외" if len(candidate.countries) > 5 else "")
    lines = [f"[임상시험 {parsed.nct_id} 기준]",
             f"Study locations: {locs or 'unknown'}. Age {_age_text(candidate.min_age_years)} - {_age_text(candidate.max_age_years)}. Sex {candidate.sex}.",
             "", "Inclusion Criteria:"]
    lines += [f"{c.id}. {c.original}" for c in parsed.criteria if c.kind == "inclusion"]
    lines += ["", "Exclusion Criteria:"]
    lines += [f"{c.id}. {c.original}" for c in parsed.criteria if c.kind == "exclusion"]
    return "\n".join(lines)
