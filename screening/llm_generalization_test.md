# 일반화 테스트 — S005 × 시험 B (NCT04063540)

프롬프트 2의 규칙은 시험 A 사례에서 뽑았습니다. 그 규칙이 **다른 시험에도 통하는지** 확인합니다.

- 규칙 부분은 프롬프트 2와 **한 글자도 바꾸지 않았습니다.** 바뀐 건 맨 아래 임상시험 기준뿐입니다.
- 규칙을 고치고 싶어도 이번에는 참습니다. 규칙과 시험을 동시에 바꾸면 결과가 왜 달라졌는지 알 수 없습니다.
- 지난번과 같은 모델과 설정(Claude Opus 4.8, 추론 수준 높음)으로 **새 대화**에서 실행하세요.

시험 B를 고른 이유: 시험 A에는 없던 유형의 기준이 많습니다.
- 행정·법적 기준 (프랑스 사회보장, 후견, 동의서)
- 연구자 판단 기준 (순응도)
- 여러 조건이 묶인 약물 금기 (B-E1)
- 나이로 확정할 수 있는 제외 기준 (B-E2)

---

## 프롬프트 (그대로 복사해서 붙여넣기)

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

[임상시험 NCT04063540 기준]
Study locations: France only. Age 18-80 years.

Inclusion Criteria:
I1. Diagnosis of migraine with aura code
I2. At least 1 aura with aura per month in the 3 months prior to inclusion
I3. No prophylactic antimigraine treatment for at least 1 month prior to inclusion
I4. For women of childbearing age, use of a reliable contraceptive method at least 3 months before and 1 month after the study
I5. Signature of written informed consent
I6. Patient affiliated with Social Security

Exclusion Criteria:
E1. Existence of contraindication to taking amiloride:
  - Known hypersensitivity to the molecule
  - Hyperkalemia (potassium level (> 5.5 mmol / l))
  - Use of another hyperkalemic diuretic or potassium salts
  - Renal insufficiency (clearance <60 ml / min)
  - Severe hepatocellular insufficiency
  - In combination with lithium, converting enzyme inhibitors, angiotensin II inhibitors (except if there is hypokalemia), ciclosporin, tacrolimus, non-antiarrhythmic drugs giving torsades de pointes
E2. Cardiovascular and renal history, for subjects over 75 years old
E3. Patient, who from an investigator's point of view would not be compliant to the procedure of the study
E4. Pregnant or lactating patient
E5. Patient under trusteeship, under guardianship, protected by law
```

> 원문의 I2 "At least 1 aura with aura per month"는 ClinicalTrials.gov 원문 그대로입니다 (원문 오타로 보임). 고치지 않고 넣었습니다. LLM이 이걸 어떻게 해석하는지도 볼 거리입니다.

---

## 결과 비교표

"내 판정"은 `S005_screening_sheet.md`의 시험 B 판정입니다.

| ID | 내 판정 (수작업) | 프롬프트 2 | 메모 |
|---|---|---|---|
| I1 | 모름 | 모름 | 일치. "증상상 강하게 의심됨, 공식 진단 기록 없음" (규칙 3 그대로) |
| I2 | 모름 | 모름 | 일치. 원문 오타 "aura with aura"를 "전조 동반 발작"으로 무리 없이 해석 |
| I3 | 모름 | 모름 | 일치 |
| I4 | 모름 | 모름 | 일치. "34세 여성 → 가임기, 조건 적용됨"까지 짚음 (폐경·불임 수술 가능성은 고려 안 함) |
| I5 | 등록 후 확인 | 등록 후 확인 | 일치 |
| I6 | 모름 | 모름 | 일치. 시험 장소 "France only"와 연결해 질문 5에 같이 넣음 |
| E1 | 모름 | 모름 | 일치. 하위 조건 6개로 쪼갬 (규칙 4 그대로) |
| E2 | 통과 | 통과 | 일치. 나이로 확정되는 제외 기준을 방향 헷갈리지 않고 통과 처리 |
| E3 | 모름 | 등록 후 확인 | **차이. LLM 쪽이 더 타당.** 연구자의 순응도 판단은 환자에게 물어서 알 수 있는 게 아니라 스크리닝 중에 생기는 정보. 수작업에서도 질문 칸에 질문 대신 메모를 적었던 기준 |
| E4 | 모름 | 모름 | 일치 |
| E5 | 모름 | 모름 | 일치 |
| 최종 | 정보 부족 | 정보 부족 | 일치 |

사용한 LLM과 모델: Claude Opus 4.8, 추론 수준 "높음" (새 대화에서 실행)

추가로 LLM이 만든 행: 시험 정보 줄을 보고 **연령(18–80) → 통과**, **장소(France only) → 모름**을 기준처럼 따로 판정함. 기준 목록에 없던 정보까지 판정 대상으로 삼은 것.

---

## 평가 정리

기준 11개 중 **10개 일치**, 최종 판단 일치. 차이 1개(E3)는 LLM 판정이 더 타당함.
→ 시험 A에서 뽑은 규칙이 **처음 보는 유형의 기준(행정·법적, 연구자 판단, 약물 금기)에도 그대로 통함.**

**잘한 점**
- E2(나이로 확정되는 제외 기준)를 "통과"로 정확히 처리. 시험 A에는 없던 유형인데 규칙 1의 예시만 보고 일반화함
- E3를 "등록 후 확인"으로 분류. 규칙 예시(스크리닝 일지, 동의서)에 없던 경우까지 스스로 확장함
- E1을 하위 조건 6개로 쪼개고, 질문을 약물(Q2)과 질환·알레르기(Q4)로 나눠서 다룸
- 칼륨 수치·신장 기능은 환자가 답하기 어렵고 혈액검사가 필요하다고 짚음 (Q4)
- 약 이름 예시(프로프라놀롤, 토피라메이트, 아미트립틸린)가 정확함. 지난번 같은 표기 오류 없음
- 질문 5개로 "모름" 기준 8개와 장소 정보를 모두 다룸

**아쉬운 점**
- **질문 순서에 전략이 없음.** Q5(거주지·프랑스 사회보장)는 답이 "아니오"면 이 시험 자체가 불가능해지는 질문인데 맨 마지막에 있음. 탈락 가능성이 큰 질문을 먼저 해야 환자가 불필요한 질문에 답하지 않아도 됨
- **Q5에 성격이 다른 질문 3개가 섞임.** 사회보장 가입, 법적 후견, 프랑스 방문 가능 여부를 한 질문에 넣음. 지난번(질문 3)보다는 짧지만 여전히 한 질문에 여러 주제
- **후견 질문이 직설적임.** "법적으로 후견인 등 보호를 받고 계신가요?"는 환자에게 불쾌할 수 있음. 수작업 질문("본인이 직접 의료 동의를 할 수 있는 상태인가요?")이 더 부드러움
- "프랑스 사회보장에 가입되어 있나요?"보다 "어느 나라에 사시나요?"를 먼저 묻는 게 효율적 (프랑스가 아니면 나머지가 필요 없음)

### 다음 프롬프트에 추가할 규칙 후보 (시험 A 결과와 합침)
1. 질문 하나에는 한 주제만 담기. 질문은 3–5개, 한 질문은 두 문장 이내 (시험 A·B 공통)
2. 진단명보다 증상이나 경험을 묻기 (시험 A)
3. 약 이름은 LLM이 만들지 말고 정해진 목록에서 가져오기 (시험 A)
4. **탈락 가능성이 큰 질문부터 순서대로** 묻기. 거주 국가처럼 답 하나로 시험 전체가 불가능해질 수 있는 질문을 맨 앞에 (시험 B)
5. 법적 신분·임신 같은 민감한 질문은 부드러운 표현 사용 (시험 B)
6. "등록 후 확인" 예시에 연구자 판단 항목(순응도 등)과 스크리닝 혈액검사 추가 (시험 B)

### 결론 (회의·발표용 한 줄)
시험 A 하나에서 뽑은 판정 규칙이 유형이 다른 시험 B에서도 11개 중 10개 일치했다. 남은 약점은 판정이 아니라 **질문 설계**(순서, 묶음, 표현)에 있다.

**볼 점**
- E2를 "통과"로 판정했나? (시험 A에는 없던, 나이로 확정되는 제외 기준)
- I5(동의서)를 "등록 후 확인"으로 분류했나? E3(연구자 판단 순응도)는 어떻게 분류했나?
- I6(사회보장)과 "France only" 정보를 연결했나?
- E1을 하위 조건별로 쪼갰나?
- 질문이 5개를 넘지 않으면서 "모름" 기준을 모두 다뤘나? 지난번처럼 너무 긴 질문은 없나?
- 민감한 질문(피임, 후견)을 어떻게 표현했나?
