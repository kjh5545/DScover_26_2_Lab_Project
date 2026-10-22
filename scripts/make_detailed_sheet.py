"""상세 환자 판정 시트(빈 양식) 만들기 (API 호출 없음).

실행: python scripts/make_detailed_sheet.py S010 --author 주희 [--text 상세설명.txt]
      python scripts/make_detailed_sheet.py N001 --author 주희 [--text ...]   # 새 환자: data/handoff/N001.json 필요

- 평가 세트 환자(S...)는 goldset의 시험·기준을, 새 환자(N...)는 run_intake가 저장한 handoff의 시험·기준을 쓴다
- 판정·근거·질문 칸은 비워 둔다 (사람이 직접 판정). --text를 주면 상세 환자 설명 칸을 채운다
- 저장: screening/detailed/<작성자>/<환자>_detailed_sheet.md (이미 있으면 덮어쓰지 않음)
양식은 docs/튜토리얼_인선.md Part A, 읽는 코드는 src/testing/detailed_sheet.py
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "goldset" / "goldset_v1.json"


def trials_of(pid: str) -> tuple[str, list[dict]]:
    """(짧은 설명, [{nct_id, title, meta, rows: [{id, kind, original, summary_ko}]}])"""
    if pid.startswith("S"):
        cases = [c for c in json.loads(GOLD.read_text(encoding="utf-8"))["cases"] if c["patient_id"] == pid]
        if not cases:
            sys.exit(f"평가 세트에 {pid} 없음")
        out = []
        for c in cases:
            m = re.search(r"Study locations: (.*?)\. Age (.*?)\. Sex (\w+)", c["criteria"])
            meta = f"나이: {m.group(2)} · 성별: {m.group(3)} · 장소: {m.group(1)}" if m else ""
            out.append({"nct_id": c["trial"], "title": c.get("trial_title") or c["trial"], "meta": meta,
                        "rows": [{"id": r["id"], "kind": "선정" if r["kind"] == "inclusion" else "제외",
                                  "original": r["original"], "summary_ko": r.get("summary_ko", "")} for r in c["rows"]]})
        return cases[0]["patient"], out
    bundle = json.loads((ROOT / "data" / "handoff" / f"{pid}.json").read_text(encoding="utf-8"))
    out = [{"nct_id": t["nct_id"], "title": t.get("title", t["nct_id"]), "meta": "",
            "rows": [{"id": c["id"], "kind": "선정" if c.get("type") == "inclusion" else "제외",
                      "original": c["text"], "summary_ko": ""} for c in t["criteria"]]} for t in bundle["trials"]]
    return bundle["case_text"], out


def cell(s: str) -> str:
    return " ".join(str(s).split()).replace("|", "/")


def make(pid: str, author: str, detailed: str | None) -> str:
    short, trials = trials_of(pid)
    lines = [f"# 상세 환자 판정 시트 · {pid}", "", f"작성자: {author}", "",
             f"## 원래 환자 설명 ({pid})", f"> {short}", "",
             "## 상세 환자 설명 (여기에 작성)",
             "원래 문장은 그대로 두고, 그 뒤에 정보를 덧붙여 5~8문장으로 써 주세요. 영어로 써 주세요 (AI 판정 입력이 영어라서).", "",
             f"> {detailed.strip() if detailed else '(여기에 상세 환자 설명)'}", "",
             "## 판정 작성 방법",
             "- **상세 환자 설명을 기준으로** 판정합니다. 원래 판정이 모름이었던 기준도 이제 통과·탈락이 될 수 있어요",
             "- 판정: `통과` / `탈락` / `모름` / `등록 후 확인` · 근거: 상세 설명의 영어 표현 인용 · 질문: 모름일 때만",
             "- 판정은 **직접** 합니다 (AI에게 판정을 묻지 않기). 팀 기준: 명시되지 않으면 모름, 동의·참여 의향·연구자 판단은 등록 후 확인",
             "", "---", ""]
    for i, t in enumerate(trials, 1):
        lines += [f"## 시험 {i} · {t['nct_id']}", f"**{t['title']}**", ""]
        if t["meta"]:
            lines.append(f"- {t['meta']}")
        lines += [f"- 원문: https://clinicaltrials.gov/study/{t['nct_id']}", "",
                  "| ID | 구분 | 기준 원문 | 한국어 요약 | 판정 | 근거 | 질문 |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {r['id']} | {r['kind']} | {cell(r['original'])} | {cell(r['summary_ko'])} |  |  |  |" for r in t["rows"]]
        lines += ["", "**최종 판단** (적격 / 부적격 / 정보 부족 / 적격 가능(등록 후 확인 필요)): ", "",
                  "**최종 판단 이유 (한 줄):** ", "", "**헷갈렸던 점:**", "- ", "", "---", ""]
    lines.append("> 이 시트의 환자는 가상이며, 판정은 과제용입니다.")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("patient")
    ap.add_argument("--author", required=True)
    ap.add_argument("--text", help="상세 환자 설명이 든 텍스트 파일")
    a = ap.parse_args()
    detailed = Path(a.text).read_text(encoding="utf-8") if a.text else None
    out = ROOT / "screening" / "detailed" / a.author / f"{a.patient}_detailed_sheet.md"
    if out.exists():
        sys.exit(f"이미 있음 (덮어쓰지 않음): {out.relative_to(ROOT)}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(make(a.patient, a.author, detailed), encoding="utf-8")
    print(f"저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
