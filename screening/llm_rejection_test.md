# 탈락 케이스 테스트 — S005 × 시험 C, 시험 D

지금까지 시험 A, B에서는 "탈락" 판정이 한 번도 나오지 않았습니다. "모름"만 남발해도 같은 결과가 나왔을 수 있습니다.
이번에는 **S005가 탈락해야 정답인 시험** 두 개로, LLM이 확실한 탈락 사유를 찾아내는지 확인합니다.

| | 시험 C · NCT04748601 | 시험 D · NCT06959004 |
|---|---|---|
| 내용 | 소아 편두통 예방약 (Qudexy XR) | 서브스턴스 P로 조짐 없는 편두통 발작 유발 연구 |
| 대상 | 6–11세, 미국 | 18–65세, 덴마크 |
| 탈락 사유 | 나이 (34세) | **조짐 동반 편두통 병력** |
| 난이도 | 쉬움. 숫자 비교만 하면 됨 | 어려움. 환자 문장의 "preceded by visual scotomata"를 읽고 기준과 연결해야 함 |

규칙 부분은 프롬프트 2와 **한 글자도 바꾸지 않았습니다.** 지난번과 같은 모델·설정으로, 시험마다 **새 대화**에서 실행하세요.

---

## 프롬프트 C (쉬움 · 나이 탈락)

```
당신은 임상시험 적격성 스크리닝 담당자입니다. 아래 환자 설명과 임상시험 기준을 대조해 기준마다 판정하세요.

[판정 규칙]
1. 판정은 다음 넷 중 하나만 씁니다. 선정 기준과 제외 기준 모두 "환자가 이 시험에 남을 수 있는가" 관점으로 판정합니다.
   - 통과: 이 기준 때문에 탈락하지 않음이 환자 정보로 확인됨
   - 탈락: 이 기준 때문에 탈락함이 환자 정보로 확인됨
   - 모름: 지금 환자에게 물어보면 알 수 있지만 정보가 없음
   - 등록 후 확인: 시험 지원 이후에야 생기는 정보 (스크리닝 일지, 동의서 등)
   예) 제외 기준 "75세 초과"에 34세 환자 → 통과 (조건에 해당하지 않으므로)
2. 환자 설명에 없는 정보를 추측해서 통과로 처리하지 마세요. 단, 명시된 정보로 논리적으로 확정되는 것은 통과/탈락으로 판정하고 추론 과정을 적으세요.
   예) 현재 34세 → 발병 나이는 34세 이하로 확정
3. 증상은 진단과 부합하지만 공식 진단 기록이 없으면 "모름"으로 하고 근거에 "증상상 강하게 의심됨"이라고 적으세요.
4. 여러 조건이 묶인 기준은 하위 조건별로 따져서 근거에 적으세요. 하나라도 탈락이면 탈락입니다.
5. 근거에는 환자 설명의 영어 원문 표현을 따옴표로 인용하세요.

[질문 규칙]
- "모름" 기준에 대해서만, 환자가 이해할 수 있는 쉬운 한국어로 질문을 만드세요. 전문 용어는 풀어 쓰거나 약 이름 예시를 드세요.
- 답 하나로 여러 기준을 해결할 수 있으면 질문을 합치세요. 질문은 최대 5개입니다.
- 질문마다 해결되는 기준 ID를 적으세요.

[출력 형식]
1. 표: | ID | 판정 | 근거 |
2. 최종 판단: 적격 / 부적격 / 정보 부족 중 하나와 한 줄 이유
3. 확인 질문 목록: 질문 — 해결되는 기준 ID

[환자]
A 34-year-old woman presents with recurrent episodes of severe unilateral throbbing headache preceded by visual scotomata, accompanied by photophobia, nausea, and phonophobia.

[임상시험 NCT04748601 기준]
Study locations: United States only. Age 6-11 years.

Inclusion Criteria:
I1. Subject is a female or male 6 to 11 years of age, inclusive, at Visit 1 (Screening)
I2. Subject weighs at least 17.0 kg and less than 50.0 kg at Visit 1 (Screening) based on 95 percentile weight for the age range.
I3. Subject has at least a 6-month history of headaches consistent with a diagnosis of migraine with or without aura (International Classification of Headache Disorders, 3rd Edition [ICHD 3]).
I4. Subject had ≥8 self-reported headache days in the 28 days prior to Screening.
I5. Subject has a PedMIDAS score >10, indicating at least mild disruption in daily activities, and <140, indicating extreme disability that may require more comprehensive, multi component therapy.

Exclusion Criteria:
E1. Subject has continuous migraines, defined as an unrelenting headache for a 28-day period.
E2. Subject is currently receiving treatment or has used Botulinum toxin (Botox®) within 3 months prior to Visit 1 (Screening).
E3. Subject is currently receiving migraine prevention medication and has initiated or changed the dose within 28 days of Screening or is unwilling to avoid making a change during the duration of the study.
E4. Subject has previously failed an adequate trial of topiramate (at least 3 months duration at a clinically appropriate dose) for prophylaxis of migraine headache due to lack of efficacy or AEs.
E5. Subject has previously failed an adequate trial of >3 migraine preventative medications.
E6. Subject has a known history of allergic reaction to topiramate or any excipient in Qudexy XR.
E7. Subject has a diagnosis or history of disease that may interfere with safety or evaluation of the study drug.
E8. Subject is currently using an investigational drug or device or has used such within 30 days prior to Visit 1.
E9. Subject has begun menses and any of the following:
  a. Subject has tested positive for pregnancy; OR
  b. Subject is pregnant, planning pregnancy, or lactating; OR
  c. Subject is taking an oral hormonal contraceptive (either combined [estrogen and progestogen containing] or progestogen-only) and is unable or unwilling to switch to an alternative highly effective contraceptive method.
```

---

## 프롬프트 D (어려움 · 조짐 병력 탈락)

```
당신은 임상시험 적격성 스크리닝 담당자입니다. 아래 환자 설명과 임상시험 기준을 대조해 기준마다 판정하세요.

[판정 규칙]
1. 판정은 다음 넷 중 하나만 씁니다. 선정 기준과 제외 기준 모두 "환자가 이 시험에 남을 수 있는가" 관점으로 판정합니다.
   - 통과: 이 기준 때문에 탈락하지 않음이 환자 정보로 확인됨
   - 탈락: 이 기준 때문에 탈락함이 환자 정보로 확인됨
   - 모름: 지금 환자에게 물어보면 알 수 있지만 정보가 없음
   - 등록 후 확인: 시험 지원 이후에야 생기는 정보 (스크리닝 일지, 동의서 등)
   예) 제외 기준 "75세 초과"에 34세 환자 → 통과 (조건에 해당하지 않으므로)
2. 환자 설명에 없는 정보를 추측해서 통과로 처리하지 마세요. 단, 명시된 정보로 논리적으로 확정되는 것은 통과/탈락으로 판정하고 추론 과정을 적으세요.
   예) 현재 34세 → 발병 나이는 34세 이하로 확정
3. 증상은 진단과 부합하지만 공식 진단 기록이 없으면 "모름"으로 하고 근거에 "증상상 강하게 의심됨"이라고 적으세요.
4. 여러 조건이 묶인 기준은 하위 조건별로 따져서 근거에 적으세요. 하나라도 탈락이면 탈락입니다.
5. 근거에는 환자 설명의 영어 원문 표현을 따옴표로 인용하세요.

[질문 규칙]
- "모름" 기준에 대해서만, 환자가 이해할 수 있는 쉬운 한국어로 질문을 만드세요. 전문 용어는 풀어 쓰거나 약 이름 예시를 드세요.
- 답 하나로 여러 기준을 해결할 수 있으면 질문을 합치세요. 질문은 최대 5개입니다.
- 질문마다 해결되는 기준 ID를 적으세요.

[출력 형식]
1. 표: | ID | 판정 | 근거 |
2. 최종 판단: 적격 / 부적격 / 정보 부족 중 하나와 한 줄 이유
3. 확인 질문 목록: 질문 — 해결되는 기준 ID

[환자]
A 34-year-old woman presents with recurrent episodes of severe unilateral throbbing headache preceded by visual scotomata, accompanied by photophobia, nausea, and phonophobia.

[임상시험 NCT06959004 기준]
Study locations: Denmark only. Age 18-65 years.

Inclusion Criteria:
I1. Age 18 to 65 years of age upon entry into screening
I2. A body weight of 50 to 100 kg
I3. History of migraine without aura for ≥12 months and in accordance with ICHD-3
I4. Between 1-5 monthly migraine days without aura on average across the 3 months prior to screening

Exclusion Criteria:
E1. Any history of a primary or secondary headache disorder other than migraine without aura and infrequent episodic tension-type headache
E2. Any history of moderate to severe traumatic brain injury
E3. Any history of cardiovascular disease, including cerebrovascular diseases
E4. Any history of pulmonary disease
E5. Any other clinically significant disorders, conditions, or diseases that might impact the safety of the subject or interfere with the study's evaluation, procedures, or completion, aside from those mentioned above. This includes any relevant medical history or evidence that, in the opinion of the site investigator, might pose a risk to the subject or impact the validity of the study results
E6. The subject is at risk of self-harm or harm to others as evidenced by past suicidal behavior
E7. Female subjects of childbearing potential with a positive pregnancy test during any study visit
E8. Cardiovascular disease of any kind, including cerebrovascular diseases
E9. Hypertension (systolic blood pressure of ≥150 mmHg and/or diastolic blood pressure of ≥100 mmHg) prior to the start of infusion on the experimental day
E10. Hypotension (systolic blood pressure of ≤90 mmHg and/or diastolic blood pressure of ≤50 mmHg)
E11. Daily use of any medication other than contraceptives
E12. Intake of any medication other than contraceptives within 48 hours of infusion start
E13. Headache of any intensity within 48 hours of infusion start
E14. Migraine attack within 5 days of infusion start
E15. Aura within 48 hours of infusion start
```

---

## 예상 판정 (Claude 작성 · LLM 답변을 받은 뒤에 보세요)

이번에는 수작업 판정이 없어서 Claude가 작성한 예상 판정을 기준으로 비교합니다. 의견이 갈릴 수 있는 항목은 "허용"에 함께 적었습니다.

### 시험 C · 예상 판정
| ID | 예상 | 허용 | 이유 |
|---|---|---|---|
| I1 | **탈락** | | 34세는 6–11세 범위 밖. 이 기준 하나로 부적격 확정 |
| I2 | 모름 | | 체중 정보 없음 |
| I3 | 모름 | | 증상상 강하게 의심되나 6개월 이상 여부와 진단 기록 없음 |
| I4 | 모름 | | 최근 28일 두통일수는 과거 정보라 물어보면 알 수 있음 |
| I5 | 모름 | 등록 후 확인 | PedMIDAS는 소아용 설문 점수. 스크리닝 때 측정하는 값으로 볼 수도 있음 |
| E1 | 통과 | 모름 | "recurrent episodes"는 발작이 반복된다는 뜻이라 28일 내내 계속되는 두통과는 맞지 않음 |
| E2–E6 | 모름 | | 투약 이력 정보 없음 |
| E7 | 모름 | 등록 후 확인 | 연구자 판단이 들어가는 기준 |
| E8 | 모름 | | 임상시험 약 사용 정보 없음 |
| E9 | 모름 | | 34세 여성이라 월경 시작은 사실상 확정이나 임신·피임 정보 없음 |
| 최종 | **부적격** | | I1 탈락 |
| 질문 | **없음이 이상적** | | 이미 부적격이 확정됐으니 질문할 이유가 없음 |

### 시험 D · 예상 판정
| ID | 예상 | 허용 | 이유 |
|---|---|---|---|
| I1 | 통과 | | 34세는 18–65세 범위 안 |
| I2 | 모름 | | 체중 정보 없음 |
| I3 | 모름 | | 조짐 없는 발작도 따로 있는지 알 수 없음. 설명된 발작은 모두 조짐 동반 |
| I4 | 모름 | | 조짐 없는 편두통일수 정보 없음 |
| E1 | **탈락** | 모름 (논쟁 항목) | 아래 설명 참고 |
| E2–E4, E6, E8 | 모름 | | 해당 병력 정보 없음 |
| E5 | 모름 | 등록 후 확인 | 연구자 판단이 들어가는 기준 |
| E7 | 등록 후 확인 | | "during any study visit" 임신 검사는 시험 방문 때 하는 것 |
| E9, E10 | 등록 후 확인 | 모름 | 실험 당일 주입 전 혈압 |
| E11 | 모름 | | 매일 먹는 약 정보 없음 |
| E12–E15 | 등록 후 확인 | | 모두 "주입 시작 전 48시간/5일" 기준. 실험 날짜가 정해져야 판단 가능 |
| 최종 | **부적격** | 정보 부족 | E1 탈락 |

**E1이 이번 테스트의 핵심입니다.**
- 이 시험은 "조짐 없는 편두통"과 "드문 긴장형 두통" 외의 두통 병력이 있으면 제외합니다. 조짐 동반 편두통은 ICHD-3에서 조짐 없는 편두통과 별개 질환(1.2 vs 1.1)입니다.
- 환자 설명에 "recurrent episodes ... preceded by visual scotomata"라고 **조짐 동반 발작이 반복됐다는 사실**이 명시돼 있습니다. 이 기준은 공식 진단이 아니라 "병력(history)"을 묻고 있으므로, 탈락이 타당하다고 봅니다.
- 그런데 규칙 3("공식 진단 기록이 없으면 모름")이 LLM을 "모름" 쪽으로 끌어당길 수 있습니다. **규칙 3이 지나치게 보수적으로 작동해서 확실한 탈락을 놓치는지**가 이번에 볼 지점입니다.

---

## 결과 비교표

| | 시험 C | 시험 D |
|---|---|---|
| 핵심 탈락 기준 판정 | I1: **탈락** ✔ | E1: **탈락** ✔ |
| 최종 판단 | **부적격** ✔ | **부적격** ✔ |
| 예상과 다른 기준 | 없음 (14개 기준 모두 예상 또는 허용 범위 안) | I3 (예상 모름 → LLM 탈락) |
| 질문 개수 | **0개** ("해당 없음") ✔ | **5개** ("참고용"이라며 생성) |
| 메모 | 아래 참고 | 아래 참고 |

### 시험 C 평가
사용한 모델: Claude Opus 4.8, 추론 수준 "높음" (새 대화)

**잘한 점**
- I1을 나이로 탈락시키고 최종 판단을 "부적격"으로 내림. "다른 항목의 답변으로 뒤집히지 않는다"고 이유도 명확함
- **질문을 하나도 만들지 않음.** 규칙에는 "모름이면 질문하라"고만 돼 있는데, 이미 부적격이니 질문이 의미 없다고 스스로 판단함
- 탈락이 확정된 뒤에도 나머지 기준을 대충 넘기지 않고 끝까지 판정함 (I2에서 "성인이니 50kg 이상"이라고 추측하지 않은 것도 규칙 2를 지킨 것)
- E1(지속성 편두통)을 "recurrent episodes"에서 논리적으로 통과 처리함. 규칙 2의 "명시된 정보로 확정되는 것"을 제대로 적용
- 마지막에 "성인 편두통 시험을 따로 찾아보라"고 권함. 추천 에이전트가 해야 할 일을 미리 보여준 셈

**아쉬운 점 · 주의할 점**
- 질문을 생략한 건 **규칙이 아니라 모델의 판단**이었음. 더 작은(저렴한) 모델로 바꾸면 규칙대로 질문 12개를 만들 수도 있음 → "탈락이 하나라도 확정되면 질문하지 않는다"를 규칙으로 명시하는 게 안전함
- 시험 B 때처럼 "위치(US only)"를 따로 판정함. 이번처럼 이미 탈락이면 상관없지만, 위치를 기준처럼 다룰지 메타 정보로 다룰지 팀에서 정해야 함

**결론**: 쉬운 탈락은 완벽하게 처리. 판정·최종 판단·질문 생략 모두 예상대로.

**볼 점**
- 탈락 사유를 정확히 찾았나? (C는 I1, D는 E1)
- 탈락이 하나 나왔을 때 최종 판단을 "부적격"으로 내렸나?
- 이미 부적격인데도 질문을 만들었나? (지금 규칙에는 "탈락이면 질문하지 마라"가 없음 → 만들었다면 규칙 빈틈)
- 시험 D에서 규칙 3 때문에 E1을 "모름"으로 놓쳤나?
- 시험 D의 E12–E15(주입 전 48시간 등)를 "등록 후 확인"으로 분류했나?

### 시험 D 평가
사용한 모델: Claude Opus 4.8, 추론 수준 "높음" (새 대화)

**잘한 점**
- **E1을 탈락으로 정확히 판정함. 이번 테스트의 핵심 통과.** 규칙 3("공식 진단 기록이 없으면 모름")에 끌려가지 않고, 이 기준이 진단이 아니라 병력을 묻는다는 걸 구분함
- 최종 판단 "부적격"
- "등록 후 확인" 분류가 정확함. E7(시험 방문 때 임신 검사), E9–E10(실험 당일 혈압), E12–E15(주입 전 48시간·5일)를 모두 맞힘. 규칙 예시에 없던 유형인데 스스로 확장함
- E5(연구자 의견)도 "등록 후 확인"으로 분류. 시험 B의 E3와 같은 판단을 일관되게 유지
- E8이 E3과 같은 내용이라는 것(원문 중복)을 알아채고 질문 하나로 묶음
- 시험 장소(Denmark only)는 이번엔 기준처럼 판정하지 않고 참고 메모로만 처리

**아쉬운 점**
- **I3 과잉 추론.** "설명된 발작에 조짐이 있다 → 조짐 없는 편두통 병력이 없다"로 탈락 처리함. 하지만 조짐 동반 편두통 환자도 조짐 없는 발작을 따로 겪을 수 있어서, 이 문장만으로는 확정할 수 없음 (예상: 모름)
- **판정끼리 모순.** I3에서는 "조짐 없는 편두통이 아니다"라고 탈락시켜 놓고, I4 질문에서는 "전조 없이 두통만 있는 날은 며칠인가요?"라고 물음. 조짐 없는 날이 있을 수 있다고 스스로 인정한 셈
- 최종 결론은 E1 덕분에 맞았지만, 만약 E1이 없는 시험이었다면 I3 하나로 **잘못 탈락시켰을 것**. 결론이 맞아도 근거가 틀릴 수 있다는 사례
- **부적격인데 질문 5개를 만듦.** 시험 C에서는 "해당 없음"이라고 했는데 이번엔 "참고용"이라며 만듦. 같은 모델·같은 규칙인데 행동이 달라짐 → "탈락 확정 시 질문하지 않는다"를 규칙으로 명시해야 한다는 근거가 확실해짐
- **민감한 질문을 일상 질문과 묶음.** 질문 5에서 "매일 드시는 약"과 "스스로를 해치려 한 적"을 한 질문에 넣음. 자해 이력 같은 질문은 따로, 신중한 표현으로 해야 함

---

## 탈락 케이스 테스트 결론

**판정 능력**: 확실한 탈락 사유를 두 시험 모두 찾아냄. 쉬운 것(나이)도 어려운 것(병력 해석)도 통과.
→ 지금 규칙은 "모름"만 남발하는 게 아니라 **탈락도 제대로 판정함**이 확인됨.

**새로 발견한 약점**
1. 질문 생략 여부가 실행마다 달라짐 (C: 0개, D: 5개)
2. 근거 하나(I3)가 과잉 추론이고, 다른 판정(I4 질문)과 모순됨
3. 민감한 질문을 일상 질문과 묶음

### 규칙 후보 (누적 · 시험 A, B, C, D)
1. 질문 하나에는 한 주제만 담기. 질문은 3–5개, 한 질문은 두 문장 이내 (A, B)
2. 진단명보다 증상이나 경험을 묻기 (A)
3. 약 이름은 LLM이 만들지 말고 정해진 목록에서 가져오기 (A)
4. 탈락 가능성이 큰 질문부터 순서대로 묻기 (B)
5. 법적 신분·임신·자해 이력 같은 민감한 질문은 부드러운 표현으로, **다른 질문과 묶지 않기** (B, D)
6. "등록 후 확인" 예시에 연구자 판단, 시험 방문 때 검사, 실험 당일 측정값 추가 (B, D)
7. **탈락이 하나라도 확정되면 질문을 만들지 않기** (C, D)
8. **판정을 마친 뒤 판정끼리 모순이 없는지 스스로 점검하기** (D)
9. 규칙 3을 보완: "진단"을 묻는 기준과 "병력·증상"을 묻는 기준을 구분하기. 환자 설명에 명시된 증상·발작 이력은 병력으로 인정 (D)

### 회의·발표용 한 줄
탈락해야 정답인 시험 2개에서 LLM은 탈락 사유를 모두 찾았다. 다만 결론이 맞아도 근거 하나는 과잉 추론이었고, 같은 규칙에서도 질문을 할지 말지는 실행마다 달랐다. 규칙으로 명시하지 않은 행동은 모델의 그때그때 판단에 맡겨진다.
