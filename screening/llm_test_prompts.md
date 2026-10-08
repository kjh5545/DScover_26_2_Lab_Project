# LLM 스크리닝 테스트 — S005 × 시험 A (NCT07018700)

수작업 시트와 같은 작업을 LLM에게 시켜 보고 결과를 비교합니다.
웹 채팅(Claude, ChatGPT 등)에 아래 프롬프트를 **새 대화마다 하나씩** 붙여넣으세요.

- **프롬프트 1 (기본)**: 아무 규칙 없이 시킨 버전. LLM이 어디서 틀리는지 봅니다.
- **프롬프트 2 (개선)**: 수작업에서 배운 규칙을 넣은 버전. 얼마나 나아지는지 봅니다.

두 결과를 맨 아래 비교표에 정리하면 회의 자료가 됩니다.

---

## 프롬프트 1 · 기본

```
Patient:
A 34-year-old woman presents with recurrent episodes of severe unilateral throbbing headache preceded by visual scotomata, accompanied by photophobia, nausea, and phonophobia.

Clinical trial NCT07018700 eligibility criteria:

Inclusion Criteria:
I1. Participant has a diagnosis of EM with or without aura according to current International Classification of Headache Disorders (Edition 3 and Edition 4 alpha) criteria for ≥ 12 months and is able to distinguish migraine headaches from all other types of headaches;
I2. Participant age < 50 years at the time of migraine onset;
I3. Participant meeting the following headache and migraine day criteria in each of the 3 months prior to screening: history of ≤ 14 headache days per month and history of 6 to 14 migraine days per month; and
I4. During the last 28 days of the screening period, participant experiencing: ≤ 14 headache days and 6 to 14 migraine days that qualify as such per the headache diary.

Exclusion Criteria:
E1. Diagnosis of chronic migraine;
E2. Diagnosis of other primary headache types, except tension-type headache, which is permitted;
E3. Diagnosis of aura without headache, migraine with brainstem aura, hemicrania continua, hypnic headache, hemiplegic migraine, retinal migraine, persistent aura without infarction, migraine aura-triggered seizure, or previous migrainous infarction;
E4. Diagnosis of secondary headache types, except medication overuse headache, which is permitted;
E5. Currently taking > 1 prescribed drug for the preventive treatment of migraine;
E6. Discontinuation of anti-calcitonin gene-related peptide (CGRP) / anti-CGRP receptor monoclonal antibody treatment less than 5 months prior to screening.

Is this patient eligible for this trial? Evaluate each criterion and give your answer in Korean.
```

---

## 프롬프트 2 · 개선

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

[임상시험 NCT07018700 기준]
Inclusion Criteria:
I1. Participant has a diagnosis of EM with or without aura according to current International Classification of Headache Disorders (Edition 3 and Edition 4 alpha) criteria for ≥ 12 months and is able to distinguish migraine headaches from all other types of headaches;
I2. Participant age < 50 years at the time of migraine onset;
I3. Participant meeting the following headache and migraine day criteria in each of the 3 months prior to screening: history of ≤ 14 headache days per month and history of 6 to 14 migraine days per month; and
I4. During the last 28 days of the screening period, participant experiencing: ≤ 14 headache days and 6 to 14 migraine days that qualify as such per the headache diary.

Exclusion Criteria:
E1. Diagnosis of chronic migraine;
E2. Diagnosis of other primary headache types, except tension-type headache, which is permitted;
E3. Diagnosis of aura without headache, migraine with brainstem aura, hemicrania continua, hypnic headache, hemiplegic migraine, retinal migraine, persistent aura without infarction, migraine aura-triggered seizure, or previous migrainous infarction;
E4. Diagnosis of secondary headache types, except medication overuse headache, which is permitted;
E5. Currently taking > 1 prescribed drug for the preventive treatment of migraine;
E6. Discontinuation of anti-calcitonin gene-related peptide (CGRP) / anti-CGRP receptor monoclonal antibody treatment less than 5 months prior to screening.
```

---

## 결과 비교표

| ID | 내 판정 (수작업) | 프롬프트 1 | 프롬프트 2 | 메모 |
|---|---|---|---|---|
| I1 | 모름 | 판정 불가 | 모름 | 셋 다 일치. P2는 "다른 두통과 구분 가능" 하위 조건까지 따로 짚음 (수작업에서 놓친 부분) |
| I2 | 통과 | 충족 | 통과 | 셋 다 일치. "현재 34세 → 발병은 34세 이하" 추론까지 같음 |
| I3 | 모름 | 판정 불가 | 모름 | 셋 다 일치 |
| I4 | 등록 후 확인 | 판정 불가 | 등록 후 확인 | P1만 차이. P1은 미래 정보라는 걸 구분하지 못하고 "선별 28일간 두통일수"를 물어보려 함. P2는 규칙대로 구분 |
| E1 | 모름 | 배제 근거 없음 | 모름 | P1만 차이. P1은 언급이 없으면 사실상 통과로 봄 |
| E2 | 모름 | 배제 근거 없음 | 모름 | P1만 차이. P1은 질문도 만들지 않음 |
| E3 | 모름 | 배제 근거 없음 | 모름 | P1은 망막 편두통이 아니라고 근거 없이 단정 + hemicrania continua 오역. P2는 하위 조건별로 따지고 단정하지 않음 |
| E4 | 모름 | 배제 근거 없음 | 모름 | P1만 차이 |
| E5 | 모름 | 판정 불가 | 모름 | 셋 다 일치 |
| E6 | 모름 | 판정 불가 | 모름 | 셋 다 일치. P1 질문은 전문 용어 그대로, P2 질문은 상품명 예시를 듦 |
| 최종 | 정보 부족 | 적격성 미결정 | 정보 부족 | 셋 다 일치 |

사용한 LLM과 모델: Claude Opus 4.8, 추론 수준 "높음" (프롬프트 1, 2 모두 새 대화에서 실행)

---

## 평가 정리

### 프롬프트 1 (기본)
기준 10개 중 **5개 일치** (I1, I2, I3, E5, E6), 5개 차이 (I4, E1–E4). 최종 판단은 일치.

**잘한 점**
- 정보가 없는 선정 기준을 추측으로 "충족" 처리하지 않음
- I2에서 "현재 34세 → 발병은 34세 이하" 추론을 정확히 함
- E1을 판단하려면 I3·I4의 빈도 정보가 필요하다고 기준끼리 연결함
- 필요한 추가 정보를 4개로 묶어 정리함

**아쉬운 점**
- 제외 기준(E1–E4)은 언급이 없으면 "배제 근거 없음", 즉 사실상 통과로 처리함. 그래서 이 기준들에 대한 질문을 하나도 만들지 않음
- E3에서 암점이 한쪽 눈인지 양쪽인지 모르는데 "망막 편두통에 해당하지 않음"이라고 근거 없이 단정함
- hemicrania continua(지속성 편측 두통)를 "지속편마비"로 오역함
- I4가 시험 지원 후에야 생기는 정보라는 걸 구분하지 못하고, "선별 28일간 두통일수"를 지금 물어볼 정보로 착각함
- 질문에 "항-CGRP/수용체 단클론항체" 같은 전문 용어를 그대로 씀

### 프롬프트 2 (개선)
기준 10개 **모두 일치**. 최종 판단도 일치.

**잘한 점**
- 수작업에서 뽑은 규칙이 그대로 반영됨: I4를 "등록 후 확인"으로 구분, 제외 기준도 언급이 없으면 "모름", 추측 금지
- E3를 하위 조건별로 따지고 단정하지 않음. "두통이 있으니 두통 없는 조짐은 해당 안 됨"도 짚음
- I1의 "편두통을 다른 두통과 구분 가능" 하위 조건을 따로 짚음 (수작업에서 놓친 부분)
- 질문 4개로 "모름" 기준 8개를 모두 다루고, 질문마다 해결되는 기준 ID를 표시함
- 약 질문에 상품명 예시를 들어 환자 눈높이에 맞춤

**아쉬운 점**
- 질문 3이 너무 김. 하위 항목 4개를 한 문장에 넣어 "질문을 합쳐라"는 규칙을 과하게 따름
- 질문 3이 "망막 편두통으로 진단받은 적 있나요?"처럼 **진단명**을 물음. 환자는 진단명을 모를 수 있으니 "시야 이상이 한쪽 눈에만 생기나요?"처럼 **증상**을 묻는 수작업 질문이 더 나음
- 약 상품명 표기 오류: "아이모빅"(→ 아이모비그), "앰겔러티"(→ 엠갈리티)
- E3에서 "두통 없는 조짐에는 해당하지 않을 가능성이 높음"이라고 흐림. 두통이 명시돼 있으니 이 하위 조건은 확정적으로 해당 없음이라고 해도 됨 (규칙 2의 "논리적으로 확정되는 것")

### 프롬프트 1 재실행 (같은 프롬프트, 새 대화)
같은 프롬프트를 한 번 더 돌린 결과. 판정은 첫 실행과 같은 패턴이었음.

| ID | 1차 실행 | 2차 실행 |
|---|---|---|
| I1–I4 | 판정 불가 / I2만 충족 | 같음 |
| E1 | 배제 근거 없음 | "해당 없음으로 보이나 확정 불가" |
| E2, E4 | 배제 근거 없음 | 해당 없음 |
| E3 | 배제 근거 없음 (망막 편두통 아니라고 단정) | 해당 없음 (**"시각 암점은 양안성"이라고 단정**) |
| E5, E6 | 판정 불가 | 같음 |
| 최종 | 미결정 | 같음 |

- 표현은 매번 조금씩 다르지만, "제외 기준은 언급이 없으면 넘어간다"는 경향은 그대로 반복됨. 우연이 아니라 기본 성향으로 봐야 함
- E3 오류는 2차에서 더 구체적으로 나옴. 환자 문장에 없는 "양안성"을 사실처럼 씀 → 규칙 없이 두면 그럴듯한 근거를 지어내는 사례로 발표에 쓰기 좋음
- 2차에서도 I4의 "선별 28일간 두통일기"를 추가로 필요한 정보로 요청함 (등록 후에야 생기는 정보라는 걸 구분 못 함)

### 주의할 점
규칙을 이 사례에서 뽑았기 때문에 이 사례에 잘 맞는 건 어느 정도 당연함. 다른 환자·시험(예: 시험 B, S004 방광암)에서도 통하는지 확인해야 진짜 성능이라고 할 수 있음.

### 다음 프롬프트에 추가할 규칙 후보
- 질문 하나에는 한 주제만 담기. 질문은 3–5개, 한 질문은 두 문장 이내
- 진단명보다 증상이나 경험을 묻기
- 약 이름은 LLM이 만들지 말고 정해진 목록에서 가져오기 (코드·도구로 처리)

### 회의 안건
1. 제외 기준에 대한 언급이 없을 때 **"모름"(질문함)**으로 볼지 **"배제 근거 없음"(넘어감)**으로 볼지. 앞쪽은 안전하지만 질문이 많아지고, 뒤쪽은 질문이 줄지만 놓치는 게 생김
2. 질문 수와 질문 하나의 길이 사이 균형
3. 다른 시험·환자로 일반화 테스트를 언제 할지

### 결론 (회의·발표용 한 줄)
수작업에서 발견한 규칙 5개를 프롬프트에 넣었더니 일치하는 기준이 5개에서 10개로 늘었다. 0단계 수작업이 곧 프롬프트 설계였다.
