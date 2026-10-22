"""인선 상세 환자 시트(screening/detailed/<작성자>/<환자>_detailed_sheet.md)를 읽는다 (API 호출 없음).

시트 양식: docs/튜토리얼_인선.md Part A. 사람이 직접 채운 표라서 칸이 조금 어긋나도 읽히게 만들었고,
읽다가 이상한 곳(빈 판정, 모르는 판정값, 평가 세트와 다른 기준 ID)은 problems에 모아 알려 준다.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
GOLD = ROOT / "goldset" / "goldset_v1.json"

VERDICT = {"통과": "pass", "탈락": "fail", "모름": "unknown", "등록후확인": "post_enrollment",
           "pass": "pass", "fail": "fail", "unknown": "unknown", "post_enrollment": "post_enrollment"}
FINAL = {"적격": "eligible", "부적격": "ineligible", "정보부족": "insufficient_info",
         "적격가능": "probably_eligible", "적격가능(등록후확인필요)": "probably_eligible"}
PLACEHOLDER = "(여기에 상세 환자 설명)"


def _norm(s: str) -> str:
    return re.sub(r"[\s*`]", "", s)


def _section(text: str, start: str, *ends: str) -> str:
    """start 다음부터 ends 중 가장 먼저 나오는 곳까지 (칸을 지운 시트도 읽히게)."""
    i = text.find(start)
    if i < 0:
        return ""
    i += len(start)
    found = [j for j in (text.find(e, i) for e in ends) if j >= 0]
    return text[i:min(found) if found else len(text)]


def parse_sheet(path: Path) -> dict:
    """시트 → {"patient_id", "author", "short_text", "detailed_text", "memo", "trials": [...], "problems": [...]}

    trials: [{"nct_id", "rows": [{"id", "verdict", "evidence", "question", "raw_verdict"}], "final", "final_raw"}]
    verdict는 pass/fail/unknown/post_enrollment, 비었거나 모르는 값이면 None.
    """
    text = Path(path).read_text(encoding="utf-8")
    problems = []
    m = re.search(r"·\s*([SN]\d+)", text)   # S: 평가 세트 환자, N: 새 환자 (10/22)
    patient_id = m.group(1) if m else Path(path).stem.split("_")[0]
    m = re.search(r"작성자:\s*(\S+)", text)
    author = m.group(1) if m else Path(path).parent.name

    short = _section(text, "## 원래 환자 설명", "## 상세 환자 설명")
    short_text = " ".join(l.lstrip("> ").strip() for l in short.splitlines()[1:] if l.strip())

    # 상세 설명: 안내 문장, 빈 줄, 자리표시를 빼고 남은 줄 (인용 기호 ">"는 있어도 없어도 됨)
    detailed = _section(text, "## 상세 환자 설명", "**덧붙인 정보 메모", "## 판정 작성 방법")
    lines = [l.lstrip(">").strip() for l in detailed.splitlines()[1:]]
    lines = [l for l in lines if l and l != PLACEHOLDER and not l.startswith("원래 문장은 그대로")]
    detailed_text = " ".join(lines)
    if not detailed_text:
        problems.append("상세 환자 설명이 비어 있음")
    elif short_text and not detailed_text.startswith(short_text[:40]):
        problems.append("상세 설명이 원래 문장으로 시작하지 않음 (원래 문장은 그대로 두고 덧붙이는 규칙)")

    memo_block = _section(text, "**덧붙인 정보 메모", "## 판정 작성 방법")
    memo = [l.strip()[1:].strip() for l in memo_block.splitlines()
            if l.strip().startswith("-") and l.strip()[1:].strip()]

    trials = []
    for block in re.split(r"\n## 시험 \d+ · ", text)[1:]:
        nct = block.split()[0].strip()
        rows = []
        for line in block.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not line.lstrip().startswith("|") or not re.fullmatch(r"[IE]\d+", cells[0]):
                continue
            # 열: ID | 구분 | 원문 | 요약 | 판정 | 근거 | 질문 — 원문에 "|"가 섞여도 판정 칸을 값으로 찾는다
            vi = next((i for i in range(4, len(cells)) if _norm(cells[i]) in VERDICT), 4 if len(cells) > 4 else None)
            raw = cells[vi] if vi is not None else ""
            verdict = VERDICT.get(_norm(raw))
            if verdict is None:
                problems.append(f"{nct} {cells[0]}: 판정 {'없음' if not raw else repr(raw)}")
            rows.append({"id": cells[0], "verdict": verdict, "raw_verdict": raw,
                         "evidence": cells[vi + 1] if vi is not None and vi + 1 < len(cells) else "",
                         "question": cells[vi + 2] if vi is not None and vi + 2 < len(cells) else ""})
        m = re.search(r"\*\*최종 판단\*\*[^:\n]*\)?:[ \t]*(.*)\n+(.*)", block)
        final_raw = (m.group(1) if m else "").strip()
        if m and not final_raw and not m.group(2).startswith("**"):   # 다음 줄에 적은 경우
            final_raw = m.group(2).strip()
        final = FINAL.get(_norm(final_raw).split("(")[0]) or FINAL.get(_norm(final_raw))
        if final is None:
            problems.append(f"{nct}: 최종 판단 {'없음' if not final_raw else repr(final_raw)}")
        trials.append({"nct_id": nct, "rows": rows, "final": final, "final_raw": final_raw})

    problems += _check_against_goldset(patient_id, trials)
    return {"patient_id": patient_id, "author": author, "short_text": short_text,
            "detailed_text": detailed_text, "memo": memo, "trials": trials, "problems": problems,
            "path": str(Path(path).relative_to(ROOT)) if Path(path).is_relative_to(ROOT) else str(path)}


def _check_against_goldset(patient_id: str, trials: list[dict]) -> list[str]:
    """시트의 시험·기준 ID가 판정할 기준 목록과 같은지 — 평가 세트 환자(S)는 goldset, 새 환자(N)는 handoff."""
    if patient_id.startswith("N"):
        bundle = json.loads((ROOT / "data" / "handoff" / f"{patient_id}.json").read_text(encoding="utf-8"))
        by_trial = {t["nct_id"]: [c["id"] for c in t["criteria"]] for t in bundle["trials"]}
        source = "handoff"
    else:
        gold = json.loads(GOLD.read_text(encoding="utf-8"))
        by_trial = {c["trial"]: [r["id"] for r in c["rows"]] for c in gold["cases"] if c["patient_id"] == patient_id}
        source = "평가 세트"
    out = []
    for t in trials:
        if t["nct_id"] not in by_trial:
            out.append(f"{t['nct_id']}: {source}에 없는 시험")
            continue
        ids = [r["id"] for r in t["rows"]]
        if ids != by_trial[t["nct_id"]]:
            out.append(f"{t['nct_id']}: 기준 ID가 {source}와 다름 (시트 {ids} / {source} {by_trial[t['nct_id']]})")
    return out


def is_filled(sheet: dict) -> bool:
    """상세 설명이 있고 판정이 하나라도 채워졌으면 True (빈 양식 거르기)."""
    return bool(sheet["detailed_text"]) and any(r["raw_verdict"] for t in sheet["trials"] for r in t["rows"])
