import json, os
from _parse import parse, raw
from _ko import KO

PATIENTS = {
 "S001": "A 54-year-old man with a history of chronic alcohol use presents with severe epigastric pain radiating to the back, nausea, and vomiting. Labs reveal markedly elevated serum lipase and amylase.",
 "S002": "A 29-year-old woman presents with intermittent palpitations, heat intolerance, and unintentional weight loss. Physical exam reveals a fine tremor, tachycardia, and a diffusely enlarged, non-tender thyroid gland.",
 "S003": "A 7-year-old boy with a 3-week history of periorbital edema and frothy urine. Urinalysis shows heavy proteinuria without hematuria, and serum albumin is low.",
 "S004": "A 68-year-old man with a long smoking history presents with painless gross hematuria. CT urography reveals a mass in the bladder wall.",
 "S006": "A 45-year-old man with poorly controlled type 2 diabetes presents with fever, facial pain, black necrotic eschar on the nasal mucosa, and periorbital swelling.",
 "S007": "A 3-month-old infant with projectile non-bilious vomiting after feeding, visible peristalsis, and a palpable olive-shaped mass in the epigastrium. Labs show hypochloremic, hypokalemic metabolic alkalosis.",
 "S008": "A 60-year-old woman presents with progressive dyspnea, dry cough, and clubbing of the fingers. Chest CT reveals bilateral basal reticular opacities with honeycombing.",
 "S009": "A 19-year-old male presents with fever, sore throat, fatigue, and posterior cervical lymphadenopathy. Physical exam reveals splenomegaly, and a monospot test is positive.",
 "S010": "A 73-year-old man with sudden onset of a painless, curtain-like loss of vision in the right eye, preceded by flashes of light and floaters.",
}
TRIALS = {"S001":["NCT04647097","NCT07024199"],"S002":["NCT06068179","NCT07018323"],"S003":["NCT07206537","NCT07499700"],
          "S004":["NCT04369560","NCT05646485"],"S006":["NCT07654647"],"S007":["NCT05561907"],
          "S008":["NCT07652658","NCT07299695"],"S009":["NCT07478952"],"S010":["NCT03714503","NCT07081945"]}
# 키워드 검색 시 모집 중 시험 수 (2026-09-28 조회)
FEW = {"S006": ("mucormycosis", 7), "S007": ("pyloric stenosis", 20), "S009": ("infectious mononucleosis", 6)}
ASSIGN = {"팀원1": ["S001","S003","S009","S004","S008"], "팀원2": ["S002","S006","S007","S010","S004","S008"]}
SHARED = {"S004","S008"}
SEX = {"ALL":"성별 무관","MALE":"남성만","FEMALE":"여성만"}
TYPE = {"INTERVENTIONAL":"중재 연구(약·시술 등을 실제로 적용)","OBSERVATIONAL":"관찰 연구"}

def cell(s): return s.replace("|","\|").replace("\n"," ")

def trial_block(n, idx):
    p = raw[n]["protocolSection"]; e = p["eligibilityModule"]
    cs = list(dict.fromkeys(l.get("country","") for l in p.get("contactsLocationsModule",{}).get("locations",[])))
    ctry = ", ".join(cs) if len(cs) <= 4 else f"{', '.join(cs[:3])} 외 {len(cs)-3}개국"
    age = f'{e.get("minimumAge","제한 없음")} – {e.get("maximumAge","제한 없음")}'.replace(" Years","세").replace(" Year","세")
    inc, exc = parse(n); ki, ke = KO[n]
    assert len(inc)==len(ki) and len(exc)==len(ke), n
    L = [f"## 시험 {idx} · {n}", f"**{p['identificationModule']['briefTitle']}**", "",
         f"- 나이: {age} · {SEX.get(e.get('sex','ALL'),'')} · 장소: {ctry}",
         f"- 종류: {TYPE.get(p['designModule']['studyType'],p['designModule']['studyType'])}",
         f"- 원문: https://clinicaltrials.gov/study/{n}", "",
         "| ID | 구분 | 기준 원문 | 한국어 요약 | 판정 | 근거 | 질문 |", "|---|---|---|---|---|---|---|"]
    for k,(o,s) in enumerate(zip(inc,ki),1): L.append(f"| I{k} | 선정 | {cell(o)} | {cell(s)} |  |  |  |")
    for k,(o,s) in enumerate(zip(exc,ke),1): L.append(f"| E{k} | 제외 | {cell(o)} | {cell(s)} |  |  |  |")
    L += ["", "**최종 판단** (적격 / 부적격 / 정보 부족 / 적격 가능(등록 후 확인 필요)):", "",
          "**최종 판단 이유 (한 줄):**", "", "**헷갈렸던 점:**", "- ", "", "---", ""]
    return L

def sheet(pid, who):
    L = [f"# 수동 스크리닝 시트 · {pid}", "",
         f"작성자: {who}" + ("  ·  **두 사람이 같이 맡은 환자입니다. 다 채울 때까지 서로 답을 공유하지 마세요.**" if pid in SHARED else ""), "",
         f"## 환자 ({pid})", f"> {PATIENTS[pid]}", "",
         "## 작성 방법",
         "- **판정**: `통과` / `탈락` / `모름` / `등록 후 확인` 중 하나 (뜻은 `README.md` 참고)",
         "- **근거**: 판정에 쓴 환자 설명의 영어 표현을 따옴표로 인용. 추론했다면 추론 과정도 (예: \"34-year-old\" → 발병은 34세 이하)",
         "- **질문**: `모름`일 때만, 환자에게 물어볼 쉬운 질문 한 문장",
         "- **판정은 기준 원문 기준**입니다. 한국어 요약은 이해를 돕는 참고용이라 원문과 다르면 원문을 따르세요", "", "---", ""]
    for i,n in enumerate(TRIALS[pid],1): L += trial_block(n,i)
    if pid in FEW:
        kw,c = FEW[pid]
        L += ["## 이 환자에게 맞는 임상시험", "",
              f"ClinicalTrials.gov에서 `{kw}`로 모집 중인 시험을 검색하면 {c}개 정도만 나옵니다 (2026-09-28 기준, 관련 없는 시험도 섞여 있음).", "",
              "**이 환자에게 추천할 만한 임상시험이 있다고 보나요? (있다 / 없다) 이유는?**", "", "- ", ""]
    elif len(TRIALS[pid]) == 2:
        L += ["## 두 시험 비교", "", "**이 환자에게 어느 쪽을 먼저 추천하겠습니까? (둘 다 아니면 '둘 다 아님') 이유는?**", "", "- ", "",
              "**확인 질문을 하나만 할 수 있다면 무엇을 묻겠습니까? 이유는?**", "", "- ", ""]
    L += ["> 이 시트의 진단 추정과 판정은 과제용이며 의학적 판단이 아닙니다.", ""]
    return "\n".join(L)

for who, pids in ASSIGN.items():
    os.makedirs(who, exist_ok=True)
    for pid in pids:
        open(f"{who}/{pid}_screening_sheet.md","w",encoding="utf-8").write(sheet(pid, who))
print({w: len(p) for w,p in ASSIGN.items()}, sum(len(parse(n)[0])+len(parse(n)[1]) for n in raw))
