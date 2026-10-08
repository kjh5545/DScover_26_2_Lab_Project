"""최종 평가 세트 만들기: 팀원 레이블 → goldset/goldset_v1.json (평가 도구 입력 겸 원본), goldset/평가세트_v1.md (사람용)

정답을 고치려면 원본 시트(스크리닝1, 스크리닝2)나 _build_cases.py의 팀 결정 규칙을 고친 뒤 이 스크립트만 다시 실행한다.
"""
import json, re, shutil
from collections import Counter
from _parse import parse, raw
from _ko import KO
from _gen import PATIENTS

from _build_cases import build
cases, _notes = build()
L = json.load(open('labels_raw.json', encoding='utf-8'))
TITLE_KO = {
 "NCT04647097": "금주·금연으로 급성 췌장염 재발 예방", "NCT07024199": "소아 급성 췌장염 진통제 비교",
 "NCT06068179": "그레이브스병 관해 (미코페놀레이트+메티마졸)", "NCT07018323": "IMVT-1402 그레이브스병 치료",
 "NCT07206537": "소아 신증후군 스테로이드 골소실 예방 (비타민 K2)", "NCT07499700": "성인 미세변화병·FSGS 치료제 BAT4406F",
 "NCT04369560": "방광벽 MRI로 방광암 병기 결정", "NCT05646485": "방광암 선별검사 (고위험군)",
 "NCT07654647": "3D 프린팅 티타늄 얼굴 재건 임플란트", "NCT05561907": "악성 위 출구 폐쇄의 내시경 vs 수술 위공장문합",
 "NCT07652658": "AZD8965 특발성 폐섬유증", "NCT07299695": "폐섬유증 급성 악화에 면역글로불린",
 "NCT07478952": "EBV 백신 mRNA-1189 (건강한 성인)", "NCT03714503": "망막박리 수술 후 머리 자세",
 "NCT07081945": "하부 열공성 망막박리에 양막 사용",
}
DX = {"S001":"급성 췌장염 의심","S002":"그레이브스병 의심","S003":"소아 신증후군 의심","S004":"방광암 의심","S006":"털곰팡이증 의심",
      "S007":"영아 비후성 유문협착증 의심","S008":"특발성 폐섬유증 의심","S009":"전염성 단핵구증 의심","S010":"망막박리 의심"}
CONSENT = re.compile(r"consent|agree|willing|refuse|unwilling|decline", re.I)

def gold_str(v): return v if isinstance(v, str) else " / ".join(v)
def row_info(pid, nct, cid):
    ev, q, per = [], "", {}
    for w, d in L[pid].items():
        t = [t for t in d["trials"] if t["nct"] == nct][0]
        r = next(r for r in t["rows"] if r["id"] == cid)
        per[w] = r["verdict"]
        if r["evidence"] and r["evidence"] not in ev: ev.append(r["evidence"])
        if not q and r["question"] not in ("", "없음", "-"): q = r["question"]
    return ev, q, per

def cell(s): return str(s).replace("|", "\|").replace("\n", " ")

out_json, md = [], []
dist = Counter(); n_rows = 0
for c in cases:
    for v in c["expected"].values(): dist[gold_str(v)] += 1; n_rows += 1

md += ["# 임상시험 스크리닝 평가 세트 v1", "",
 "> 팀원 2명이 직접 판정한 정답 레이블. 우리 AI 에이전트의 매칭 정확도를 재는 기준으로 씁니다.",
 "> 확정: 2026-10-08 · 레이블: 팀원 1, 팀원 2 · 시험 선택과 시트 구성: Claude (실제 ClinicalTrials.gov 모집 중 시험)", "",
 "## 한눈에 보기", "",
 "| 항목 | 값 |", "|---|---|",
 f"| 환자 | 9명 (S001–S010 중 사전 실험에 쓴 S005 제외) |",
 f"| 환자-시험 조합 | {len(cases)}개 |",
 f"| 판정한 기준 | {n_rows}개 |",
 f"| 정답 분포 | " + " · ".join(f"{k} {v}" for k, v in dist.most_common()) + " |",
 f"| 최종 판단 | 정보 부족 {sum(c['expected_final']==['정보 부족'] for c in cases)}개 · 부적격 {sum(c['expected_final']==['부적격'] for c in cases)}개 |",
 "| 두 사람 일치도 | S004, S008 공동 판정 46개 중 43개 일치 (93%), 최종 판단 4/4 일치. 갈린 3개는 모두 동의서 기준 |", "",
 "## 판정 규칙 (이 세트에 적용된 기준)", "",
 "| 판정 | 뜻 |", "|---|---|",
 "| 통과 | 이 기준 때문에 떨어지지 않는다는 게 환자 설명으로 확인됨 |",
 "| 탈락 | 이 기준 때문에 떨어진다는 게 환자 설명으로 확인됨 |",
 "| 모름 | 지금 환자에게 물어보면 알 수 있지만 정보가 없음 |",
 "| 등록 후 확인 | 시험에 지원한 뒤에야 생기는 정보 |", "",
 "**팀 결정 (2026-10-08)**",
 "1. **동의서·참여 의사·추적 관찰 순응 의사** 기준은 **등록 후 확인**으로 통일 (16개 기준)",
 "2. 논리적으로 탈락을 추론할 수 있어도 **환자 설명에 명시되지 않았으면 모름** 유지",
 "   - 예: S003 × NCT07206537 I2 (3주 병력인데 스테로이드 6개월 사용 요구), S004 × NCT05646485 E2 (지금 받은 CT가 '2년 내 혈뇨 평가'인지)",
 "3. 나이가 기준 목록에 없고 시험 정보에만 있으면, 기준은 그대로 판정하고 최종 판단에 나이를 반영 (S003 × NCT07499700). 시스템에서는 검색 단계 나이 필터로 먼저 거름",
 "4. **\"Other\", \"프로토콜에 정의됨\"처럼 내용이 공개되지 않은 기준**은 **등록 후 확인** (3개 기준). 환자에게 물어서 알 수 있는 정보가 아니라 시험에 지원해야 알 수 있음",
 "5. 공동 판정에서 의학적 판단이 갈린 기준은 없었음", "",
 "## 케이스 목록", "",
 "| # | 환자 | 시험 | 내용 | 기준 수 | 최종 판단 | 레이블 |", "|---|---|---|---|---|---|---|"]
for i, c in enumerate(cases, 1):
    md.append(f"| {i} | {c['patient_id']} {DX[c['patient_id']]} | {c['trial']} | {TITLE_KO[c['trial']]} | {len(c['expected'])} | {' / '.join(c['expected_final'])} | {', '.join(c['annotators'])} |")
md += ["", "## 사용법", "",
 "- 코드용 파일: `goldset/goldset_v1.json`. 평가 도구 입력과 원본 기록(두 레이블러 판정, 근거, 질문)을 함께 담은 하나의 파일",
 "- 자동 평가: `python run_eval.py --goldset --rules rules_prompt_v3.md --models claude-sonnet-5-5 --repeats 3` (`eval/` 폴더에서)",
 "- 정답에 이의가 있으면 이 문서에 표시하고 팀에서 합의 후 v2로 갱신 (원본 시트: `screening/labeling/스크리닝1`, `스크리닝2`)", "",
 "---", ""]

for i, c in enumerate(cases, 1):
    pid, n = c["patient_id"], c["trial"]
    p = raw[n]["protocolSection"]; e = p["eligibilityModule"]
    inc, exc = parse(n); ko = KO[n][0] + KO[n][1]
    cs = list(dict.fromkeys(l.get("country", "") for l in p.get("contactsLocationsModule", {}).get("locations", [])))
    loc = ", ".join(cs) if len(cs) <= 4 else f"{', '.join(cs[:3])} 외 {len(cs)-3}개국"
    age = f'{e.get("minimumAge","제한 없음")} – {e.get("maximumAge","제한 없음")}'.replace(" Years","세").replace(" Year","세")
    md += [f"## {i}. {pid} × {n}", "",
           f"**환자 ({DX[pid]})**: {PATIENTS[pid]}", "",
           f"**시험**: {p['identificationModule']['briefTitle']} ({TITLE_KO[n]})  ",
           f"나이 {age} · 장소 {loc} · https://clinicaltrials.gov/study/{n}", "",
           "| ID | 기준 원문 | 한국어 요약 | 정답 | 레이블러 근거 | 질문 예시 |", "|---|---|---|---|---|---|"]
    rows_json = []
    for (cid, gold), orig, k in zip(c["expected"].items(), inc + exc, ko):
        ev, q, per = row_info(pid, n, cid)
        g = gold_str(gold)
        changed = ""
        if any(v != (gold if isinstance(gold, str) else v) for v in per.values()):
            changed = " ※ 팀 결정으로 조정 (원래 " + ", ".join(f"{w} {v}" for w, v in per.items()) + ")"
        md.append(f"| {cid} | {cell(orig)} | {cell(k)} | **{g}** | {cell(' / '.join(ev))}{cell(changed)} | {cell(q) if g=='모름' else ''} |")
        rows_json.append({"id": cid, "kind": "inclusion" if cid.startswith("I") else "exclusion", "original": orig, "summary_ko": k,
                          "gold": gold, "labels": per, "evidence": ev, "question": q if g == "모름" else ""})
    reasons = [t["reason"] for w in L[pid] for t in L[pid][w]["trials"] if t["nct"] == n and t["reason"]]
    confs = [t["confusions"] for w in L[pid] for t in L[pid][w]["trials"] if t["nct"] == n and t["confusions"].strip("- \n")]
    md += ["", f"**최종 판단: {' / '.join(c['expected_final'])}**", ""]
    for r in reasons[:2]: md.append(f"- 이유: {r}")
    if confs:
        md += ["", "<details><summary>레이블러가 헷갈렸던 점</summary>", ""] + [x for x in confs] + ["", "</details>"]
    md += ["", "---", ""]
    out_json.append({**c, "trial_title": p['identificationModule']['briefTitle'], "trial_title_ko": TITLE_KO[n], "rows": rows_json,
                     "final_reasons": reasons, "confusions": confs})
md.append("> 이 평가 세트의 진단 추정과 판정은 과제용이며 의학적 판단이 아닙니다.")
open('../../goldset/평가세트_v1.md', 'w', encoding='utf-8').write("\n".join(md) + "\n")
json.dump({"version": "v1", "date": "2026-10-08", "decisions": md[md.index("**팀 결정 (2026-10-08)**")+1: md.index("## 케이스 목록")-1],
           "cases": out_json}, open('../../goldset/goldset_v1.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(n_rows, dict(dist))
