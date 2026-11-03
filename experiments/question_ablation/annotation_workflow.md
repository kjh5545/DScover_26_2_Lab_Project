# 사전 주석 작업 안내

사전 주석자와 조정자, 관리자를 위한 안내문이다. 세부 기준은 `04_annotation_guideline.md` 3절을 따른다. 이 문서는 주석자에게 그대로 전달할 수 있다.

**현재 상태:** S004 13개, S008 23개 후보의 주석이 모두 비어 있다. 아래 작업은 사람이 수행한다. 자동 생성이나 완료 처리를 하지 않는다.

---

## 1. 파일 구분

| 구분 | 파일 | 전달 |
|---|---|---|
| 주석자에게 전달 | `evaluation/preannotation/S004_preannotation.csv`, `S008_preannotation.csv` | 주석자별 사본 |
| | `evaluation/templates/shared_cluster_template.csv` | 주석자별 사본 |
| | `04_annotation_guideline.md`, 이 문서 | 전달 |
| | `evaluation/examples/synthetic_cases.json` | 연습용 가상 사례 |
| 조정자에게 전달 | 위 파일 + `adjudication_template.csv`, 두 주석자의 결과 | 불일치 조정 시 |
| 관리자 보관 | `preannotation_final_template.csv`, `annotation_record_template.json`, `rater_registry_template.csv` | 주석자에게 불필요 |
| **주석자가 열지 않음** | 정답 시트, 평가 세트, 상세 환자 설명, 연구 문서, 프롬프트 폴더, 생성 결과 폴더 | 금지 |

저장소 전체를 주지 말고 위 파일만 따로 전달한다. 이미 저장소 사본이 있는 사람은 금지 파일을 열지 않는다. 이전에 본 적이 있다면 숨기지 말고 관리자에게 알려 기록한다. 본 적이 있어도 참여할 수 있다.

CSV를 Excel로 저장할 때는 **CSV UTF-8** 형식을 쓴다. 열 이름과 `annotation_id`를 바꾸지 않는다.

---

## 2. 왜 46개가 아니라 36개인가

전체 기준은 46개(S004 19, S008 27)이다. 주석 대상은 지금 정보를 물어볼 수 있는 후보 36개(S004 13, S008 23)이다. 초기 판정이 "모름"인 기준만 후보가 된다.

| 환자 | 시험 | 기준 | 초기 판정 | 제외 이유 |
|---|---|---|---|---|
| S004 | NCT04369560 | I1 | pass | 이미 판정됨 |
| S004 | NCT04369560 | E5 | pass | 이미 판정됨 |
| S004 | NCT05646485 | I1 | pass | 이미 판정됨 |
| S004 | NCT04369560 | I2 | post_enrollment | 등록 후에 확인 |
| S004 | NCT04369560 | E8 | post_enrollment | 등록 후에 확인 |
| S004 | NCT05646485 | E3 | post_enrollment | 등록 후에 확인 |
| S008 | NCT07652658 | I1 | pass | 이미 판정됨 |
| S008 | NCT07299695 | I1 | pass | 이미 판정됨 |
| S008 | NCT07299695 | I4 | post_enrollment | 등록 후에 확인 |
| S008 | NCT07299695 | E11 | post_enrollment | 등록 후에 확인 |

제외된 10개는 `is_candidate=0`인 행이다. 맥락 참고용이며 작성하지 않는다. 초기 판정은 정답이 아니다.

---

## 3. 주석자 작업 순서

시작 전에 가상 사례 8개로 연습하고, 지침 해석 차이를 정리한다. 실제 작업은 상대 주석자와 상의하지 않고 혼자 한다.

### 3.1 후보 기준 확인

`is_candidate=1`인 행만 작성한다. `patient_text`, `criterion_text`, `criterion_type`만 읽는다. 다른 자료를 찾아보지 않는다.

### 3.2 미확인 정보와 확보 가능성: `askable`

이 기준을 판정하려면 어떤 정보가 필요한지 생각한다. 그 정보를 지금 확보할 수 있는지 고른다.

| 값 | 기준 |
|---|---|
| ASK_PATIENT | 환자가 직접 답할 수 있다. |
| ASK_RECORD | 기존 기록이나 결과지로 확인할 수 있다. |
| NOT_OBTAINABLE | 등록 후 시험팀만 확인할 수 있다. |
| UNSURE | 판단 불가. `unsure_reason` 필수 |

### 3.3 판정 직접성: `decisiveness`

정보를 받았을 때 그 기준이 얼마나 바로 확정되는지 평가한다. 2는 한 번의 답변이나 기록으로 확정, 1은 추가 정보나 대조 필요, 0은 답을 받아도 확정이 어려움이다. 모르면 UNSURE와 사유를 적는다.

### 3.4 시험 대상 핵심성: `centrality`

그 기준이 시험의 대상을 정의하는 정도를 평가한다. 2는 대상 질환·병기·핵심 치료력·주 안전 조건, 1은 일반 동반 질환·병용 약물·일반 안전 조건, 0은 행정·절차·일반 사항이다. 모르면 UNSURE와 사유를 적는다.

**직접성과 핵심성은 따로 평가한다.** 합계나 등급은 적지 않는다. 등급은 계산으로 정해진다.

**추측하지 않는다.** 이 환자가 해당될 가능성, 질병의 일반적 경향, 여러 시험에 공통인지 여부, 질문 수 제한은 점수에 반영하지 않는다.

### 3.5 공유정보 군집

서로 다른 기준이 **같은 사실**을 필요로 하면 `shared_cluster_template.csv`에 같은 `cluster_id`로 적고 `shared_fact`에 그 사실을 쓴다. 기간·대상·측정값이 다르면 묶지 않는다. 같은 질환이라는 이유만으로 묶지 않는다. 군집이 없으면 빈 표로 제출한다.

### 3.6 판단 근거 기록

`rationale`에 판단 이유를 한 문장 이상 적고 기준 원문의 표현을 인용한다. `rater_id`에는 배정받은 ID를 적는다. 다시 봐야 하면 `needs_review`에 Y를 적는다.

### 3.7 제출

완성한 파일을 조정자에게 제출한다. 제출 후 혼자 수정하지 않는다.

---

## 4. 불일치 확인과 확정 (조정자, 관리자)

| 순서 | 작업 | 담당 | 비고 |
|---|---|---|---|
| 1 | `askable`, 직접성, 핵심성, 등급, 군집의 불일치 비교 | 조정자 | **전용 명령이 없다.** 표 계산이나 스크립트로 비교한다. |
| 2 | 불일치를 `adjudication_template.csv`에 기록 | 조정자 | 항목과 양쪽 값 |
| 3 | 두 주석자 토의, 미합의 시 조정자 결정 | 주석자, 조정자 | 결정 이유 기록 |
| 4 | 직접성 + 핵심성으로 등급 계산 | 조정자 | 3 이상 H, 2 M, 1 이하 L. 숫자가 아니면 빈 값 |
| 5 | 확정표 작성 | 조정자 | 아래 열 참고 |
| 6 | 군집표 확정 | 조정자 | 환자별 1개 |
| 7 | 형식 검증 | 관리자 | `05_5_preflight_review.md`의 명령 |
| 8 | 담당자 기록 작성, 잠금 | 관리자 | 아래 5절 |

확정표 열: `patient_id`, `trial_id`, `criterion_id`, `final_askable`, `final_tier`, `h_strict`, `h_any`, `adjudication_note`

- `h_strict`: `final_tier`가 H이면 `true`, 아니면 `false`
- `h_any`: 조정 전 한 주석자라도 H이면 `true`, 아니면 `false`
- `final_askable`: UNSURE를 남길 수 없다. 조정으로 나머지 세 값 중 하나로 정한다.
- 직접성이나 핵심성이 끝까지 UNSURE이면 `final_tier`를 비우고 `h_strict`를 `false`로 둔다. 건수를 기록한다.
- 환자별 H가 0개이면 잠금이 거부된다. 임의로 H를 늘리지 않고 관리자에게 알린다.

행은 **후보 기준만** 넣는다. 환자별 후보와 정확히 같아야 잠긴다 (S004 13행, S008 23행).

---

## 5. 최종 주석 파일 잠금 (관리자)

저장 위치와 이름은 고정이다.

```text
evaluation/preannotation/S004_final.csv
evaluation/preannotation/S008_final.csv
evaluation/preannotation/S004_clusters.csv
evaluation/preannotation/S008_clusters.csv
```

1. `annotation_record_template.json`을 복사해 초안을 만든다.
2. 다음을 사람이 채운다: 고영향 정의 검토 결과, 판정기 확인자, 담당자별 역할과 정답 노출 범위.
3. 형식 검증 후 잠금 명령을 실행한다.
4. 잠금은 **1회만** 가능하다. 잠금 후 파일이 바뀌면 유료 실행이 차단된다.
5. 오류를 발견하면 원본을 두고 변경 사유와 영향 범위를 기록한다.

잠금 전에는 질문 생성을 시작하지 않는다.
