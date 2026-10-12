"""팀원 레이블(labels_raw.json) → 평가 케이스. _export_goldset.py가 불러서 goldset/goldset_v1.json으로 저장한다.

- 겹친 환자(S004, S008)는 두 사람이 같으면 그 판정, 다르면 두 판정 모두 정답으로 인정
- 동의·참여 의사 기준은 등록 후 확인으로 통일 (팀 결정 2026-10-08)
- 논리상 탈락 가능하지만 명시되지 않은 기준은 모름 유지 (팀 결정 2026-10-08)
- "Other", "프로토콜에 정의됨"처럼 내용이 공개되지 않은 기준은 등록 후 확인 (팀 결정 2026-10-08)
"""
import json, re
from _parse import parse, raw
from _gen import PATIENTS, TRIALS

L = json.load(open('labels_raw.json', encoding='utf-8'))
CONSENT = re.compile(r"consent|agree|willing|refuse|unwilling|decline", re.I)
UNKNOWN_PROTOCOL = re.compile(r"defined in the protocol|^other$", re.I)
# (환자, 시험, 기준) → 추가로 인정할 판정, 이유
# 팀 결정(2026-10-08): 논리상 탈락 가능성이 있어도 명시되지 않았으면 모름 유지 → 추가 인정 판정 없음
REVIEW = {}
# 팀 결정(2026-10-12, v1.1): 연구자·의사 판단, 순응도 기준은 환자에게 물어서 알 수 없으므로 등록 후 확인
INVESTIGATOR_JUDGMENT = {
    ("S002", "NCT07018323", "E2"),  # in the Investigator's judgment
    ("S003", "NCT07206537", "E2"),  # 약·보충제 복용 순응도
    ("S004", "NCT04369560", "E8"),  # 담당 의사가 위험하다고 판단
    ("S007", "NCT05561907", "I6"),  # 수술·전신마취 가능 여부 (의료진 평가)
    ("S010", "NCT03714503", "E7"),  # 수술 후 치료 순응도
}

def criteria_block(n):
    p = raw[n]["protocolSection"]; e = p["eligibilityModule"]
    cs = list(dict.fromkeys(l.get("country", "") for l in p.get("contactsLocationsModule", {}).get("locations", [])))
    loc = ", ".join(cs[:5]) + (" 외" if len(cs) > 5 else "")
    age = f'{e.get("minimumAge", "no minimum")} - {e.get("maximumAge", "no maximum")}'
    inc, exc = parse(n)
    lines = [f"[임상시험 {n} 기준]", f"Study locations: {loc}. Age {age}. Sex {e.get('sex', 'ALL')}.", "", "Inclusion Criteria:"]
    lines += [f"I{k}. {t}" for k, t in enumerate(inc, 1)] + ["", "Exclusion Criteria:"] + [f"E{k}. {t}" for k, t in enumerate(exc, 1)]
    return "\n".join(lines), inc + exc

def build():
    cases, notes = [], []
    for pid, ncts in TRIALS.items():
        by = L[pid]
        for n in ncts:
            block, originals = criteria_block(n)
            trials = {w: [t for t in by[w]["trials"] if t["nct"] == n][0] for w in by}
            ids = [r["id"] for r in next(iter(trials.values()))["rows"]]
            orig = dict(zip(ids, originals))
            expected, finals = {}, set()
            for cid in ids:
                vs = []
                for w, t in trials.items():
                    v = next(r["verdict"] for r in t["rows"] if r["id"] == cid)
                    if v not in vs: vs.append(v)
                if len(vs) > 1 and not CONSENT.search(orig[cid]): notes.append(f"{pid} {n} {cid}: 두 사람 판정이 다름 {vs} → 둘 다 인정")
                if CONSENT.search(orig[cid]) and set(vs) <= {"모름", "등록 후 확인"}:
                    # 팀 결정(2026-10-08): 동의서·참여 의사 기준은 등록 후 확인으로 통일
                    if vs != ["등록 후 확인"]: notes.append(f"{pid} {n} {cid}: 동의·참여 의사 기준 {vs} → 등록 후 확인")
                    vs = ["등록 후 확인"]
                if UNKNOWN_PROTOCOL.search(orig[cid].strip()) and set(vs) <= {"모름", "등록 후 확인"}:
                    # 팀 결정(2026-10-08): 내용이 공개되지 않은 기준("Other", "프로토콜에 정의됨")은 등록 후 확인
                    if vs != ["등록 후 확인"]: notes.append(f"{pid} {n} {cid}: 비공개 기준 {vs} → 등록 후 확인")
                    vs = ["등록 후 확인"]
                if (pid, n, cid) in INVESTIGATOR_JUDGMENT and set(vs) <= {"모름", "등록 후 확인"}:
                    # 팀 결정(2026-10-12, v1.1): 연구자·의사 판단, 순응도는 등록 후 확인
                    if vs != ["등록 후 확인"]: notes.append(f"{pid} {n} {cid}: 연구자 판단·순응도 {vs} → 등록 후 확인")
                    vs = ["등록 후 확인"]
                if (pid, n, cid) in REVIEW:
                    alt, altf, why = REVIEW[(pid, n, cid)]
                    if alt not in vs: vs.append(alt); finals.add(altf); notes.append(f"{pid} {n} {cid}: 팀 검토 필요 ({why}) → {vs} 인정")
                expected[cid] = vs[0] if len(vs) == 1 else vs
            for t in trials.values():
                finals.add(t["final"].replace("*", "").strip())
            cases.append({
                "id": f"{pid}_{n}", "patient_id": pid, "patient": PATIENTS[pid], "trial": n,
                "note": f"팀원 레이블 ({', '.join(trials)})", "criteria": block,
                "expected": expected, "expected_final": sorted(finals),
                "expect_no_questions": finals == {"부적격"},
                "annotators": list(trials),
            })
    return cases, notes


if __name__ == "__main__":
    cases, notes = build()
    print(len(cases), "cases")
    for line in notes:
        print(line)
