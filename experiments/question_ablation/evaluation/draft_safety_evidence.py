"""안전 조건 공통 근거 목록 초안 생성 (API 호출 없음, 무료). 결과는 모두 "작성·검토 대기"이다.

근거: evaluation/evidence_sources/ 의 ClinicalTrials.gov 등록 기록 스냅숏 (공식 시험 문서). 허가 자료는 쓰지 않았다.
후보 1단계: 기준 원문이 (1) 시험 중재 이름(또는 "study drug" 같은 시험약 일반 표현)과 (2) 과민반응·금기·독성 같은
안전 표현을 **함께** 언급하는 기준.
후보 2단계: 안전 표현은 있으나 시험 중재와의 연결이 원문에서 바로 보이지 않는 기준 (계열명 등). 판단 이유는 비워 두고
등록 기록의 중재 목록이나 공식 허가 자료로 연결을 확인하도록 한다.
약물명 언급만으로는 후보로 넣지 않는다. 후보가 아니라고 1점이라는 뜻은 아니다 (근거가 부족하면 주석에서 UNSURE).
환자 정보와 정답은 읽지 않는다 (시험 기준과 등록 기록만 사용).

  python experiments/question_ablation/evaluation/draft_safety_evidence.py --out <파일>   # 기존 파일은 덮어쓰지 않음
"""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent))

import holdout as ho  # noqa: E402
import scoring as sc  # noqa: E402

SOURCES = HERE / "evidence_sources"
GENERIC = r"study (drug|treatment|medication|intervention|agent)s?|investigational (product|drug|agent)s?|trial drugs?|IMP\b|excipients?"
SAFETY = (r"hypersensitiv\w*|allerg\w*|contraindicat\w*|intoleran\w*|toxicit\w*|anaphyla\w*|serious adverse|severe adverse"
          r"|reactions?\b")   # 2026-11-05: "to preclude IVIG reactions" 누락 후 추가


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def registry_quote(criterion: str, eligibility: str) -> tuple[str, bool]:
    """기준 문장을 등록 기록의 적격성 원문에서 찾는다. 그대로 있으면 그대로, 없으면 가장 비슷한 줄."""
    if norm(criterion).lower() in norm(eligibility).lower():
        return norm(criterion), True
    lines = [norm(l.lstrip("*-• 0123456789.")) for l in eligibility.splitlines() if len(norm(l)) > 10]
    best = max(lines, key=lambda l: difflib.SequenceMatcher(None, l.lower(), criterion.lower()).ratio(), default="")
    return best, False


def names(intervention: dict) -> list[str]:
    out = [intervention.get("name", "")] + intervention.get("otherNames", [])
    out += re.findall(r"\(([^)]+)\)", intervention.get("name", ""))   # 괄호 속 약어 (예: IVIG)
    words = set()
    for n in out:
        n = re.sub(r"\(.*?\)", " ", n)
        for w in re.split(r"[,/+;]| and ", n):
            w = norm(w)
            if len(w) >= 4 and w.lower() not in ("placebo", "drug", "standard of care", "best supportive care"):
                words.add(w)
    return sorted(words, key=len, reverse=True)


def candidates() -> list[dict]:
    rows = []
    trials = {}
    for pid in ho.PILOT + ho.CONFIRM:
        for t in ho.load_bundle(pid)["trials"]:
            trials[t["nct_id"]] = t["criteria"]
    for nct, criteria in sorted(trials.items()):
        rec = json.loads((SOURCES / f"{nct}.json").read_text(encoding="utf-8"))
        ps = rec["protocolSection"]
        ivs = ps.get("armsInterventionsModule", {}).get("interventions", [])
        eligibility = ps.get("eligibilityModule", {}).get("eligibilityCriteria", "")
        updated = ps.get("statusModule", {}).get("lastUpdatePostDateStruct", {}).get("date", "")
        accessed = json.loads((SOURCES / "index.json").read_text(encoding="utf-8"))[nct]["accessed"]
        iv_names = {n: f"{i.get('type', '')}: {i.get('name', '')}" for i in ivs for n in names(i)}
        n = 0
        for c in criteria:
            text = c["text"]
            hit = [n_ for n_ in iv_names if re.search(rf"\b{re.escape(n_)}\b", text, re.I)]
            generic = re.search(GENERIC, text, re.I)
            safety = re.search(SAFETY, text, re.I)
            if not safety:
                continue
            n += 1
            linked = bool(hit or generic)
            quote, exact = registry_quote(text, eligibility)
            all_ivs = "; ".join(f"{i.get('type', '')}: {i.get('name', '')}" for i in ivs)
            target = (", ".join(sorted({iv_names[h] for h in hit})) if hit else
                      f"시험약 일반 표현 '{generic.group(0)}' (중재: {all_ivs})" if generic else f"(연결 확인 필요) 중재: {all_ivs}")
            rows.append({
                "evidence_id": f"EV-{nct}-{n:02d}", "trial_id": nct, "criterion_ids": c["id"],
                "intervention": target,
                "source": f"ClinicalTrials.gov 등록 기록 {nct} (API v2, eligibilityModule·armsInterventionsModule)"
                          + ("" if exact else " — 원문 문장 일치 확인 필요"),
                "source_version_or_accessed": f"최종 갱신 {updated}; 조회 {accessed}",
                "quoted_text": quote,
                "relation_to_intervention": (f"초안 1단계: 기준 원문이 시험 중재({'이름 직접 언급' if hit else '시험약 일반 표현'})와 "
                                             f"안전 표현('{safety.group(0)}')을 함께 명시" if linked else
                                             f"초안 2단계: 안전 표현('{safety.group(0)}')은 있으나 시험 중재와의 연결이 원문에 "
                                             "직접 보이지 않음. 등록 기록 중재 목록·공식 허가 자료로 확인 필요"),
                "reason_for_2": ("초안: 원문이 시험 중재에 대한 안전 제외 조건을 명시하므로 중재 관련 핵심 안전 조건 후보. "
                                 "약물명 언급만이 아니라 안전 관계가 원문에 있는지 검토 필요") if linked else "",
                "prepared_by": "Claude (초안, 2026-11-04)", "review_status": "작성·검토 대기",
                "reviewed_by": "", "fixed_date": ""})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        print(f"[중단] 이미 있음: {args.out}", file=sys.stderr)
        return 2
    rows = candidates()
    sc.write_csv(args.out, sc.SCHEMA["safety_evidence_columns"], rows)
    by_trial = {}
    for r in rows:
        by_trial[r["trial_id"]] = by_trial.get(r["trial_id"], 0) + 1
    print(json.dumps({"rows": len(rows), "by_trial": by_trial,
                      "quote_needs_check": sum("일치 확인 필요" in r["source"] for r in rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
