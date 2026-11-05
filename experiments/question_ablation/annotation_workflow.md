# 사전 주석 작업 안내

사전 주석자와 조정자, 관리자를 위한 안내문이다. 세부 기준은 `04_annotation_guideline.md` 3절을 따른다. 이 문서는 주석자에게 그대로 전달할 수 있다.

**현재 상태 (2026-11-05):** 파일럿은 6절의 **미검증 AI 주석 경로**로 진행한다. 확정표 `S004_final.csv`·`S008_final.csv`는 AI 주석 버전 고정본이며, **2026-11-05에 잠갔다** (`annotation_record.json`). 사람 주석자 작업본(`work/`)은 비어 있고 이번 파일럿에는 쓰지 않는다. 1~5절은 사람 주석 절차로 유지하며, 확인 실험은 이 절차를 따른다.

---

## 1. 파일 구분

| 구분 | 파일 | 전달 |
|---|---|---|
| 주석자에게 전달 | `evaluation/preannotation/work/S004_preannotation_annotator.csv`, `S008_preannotation_annotator.csv` (원본 `S00x_preannotation.csv`의 작업본. 원본은 형식 검사 기준이므로 고치지 않는다) | 주석자별 사본 |
| | `evaluation/preannotation/work/S004_clusters_annotator.csv`, `S008_clusters_annotator.csv` | 주석자별 사본 |
| | `evaluation/templates/shared_cluster_template.csv` | 주석자별 사본 |
| | `04_annotation_guideline.md`, 이 문서 | 전달 |
| | `evaluation/examples/synthetic_cases.json` | 연습용 가상 사례 |
| | `evaluation/preannotation/safety_evidence.csv` | 고정된 안전 조건 공통 근거 목록. 읽기 전용 |
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

`is_candidate=1`인 행만 작성한다. `patient_text`, `criterion_text`, `criterion_type`과 공통 근거 목록만 읽는다. 다른 자료를 찾아보지 않는다.

### 3.2 미확인 정보와 확보 가능성: `askable`

이 기준을 판정하려면 어떤 정보가 필요한지 생각한다. 그 정보를 지금 확보할 수 있는지 고른다.

| 값 | 기준 |
|---|---|
| ASK_PATIENT | 환자가 직접 답할 수 있다. |
| ASK_RECORD | 기존 기록이나 결과지로 확인할 수 있다. |
| NOT_OBTAINABLE | 등록 후 시험팀만 확인할 수 있다. |
| UNSURE | 판단 불가. `unsure_reason` 필수 |

### 3.3 시험 대상 핵심성: `centrality`

그 기준이 연구 대상과 시험 중재 안전에서 얼마나 핵심인지 평가한다. **핵심 기준(H)은 이 값으로 정해진다.** 세부 기준과 판단 원칙은 지침 3.1절을 따른다.

- 2: 연구 대상 집단을 정의하는 핵심 조건(대상 질환·병기·필수 치료력), 또는 근거가 있는 중재 관련 핵심 안전 조건
- 1: 일반 건강·안전 요건
- 0: 운영·행정·절차 요건
- UNSURE: 근거만으로 구분하기 어려움 (사유 필수)

안전 조건의 2점은 **원문·시험 문서의 명시적 설명이나 공통 근거 목록에 근거가 있을 때만** 준다. 약물명이나 계열이 나온다는 것만으로는 2점이 아니다. 근거가 부족하면 1점으로 낮추지 말고 UNSURE로 적는다. 2점이면 `centrality_evidence`에 `원문: <문구>` 또는 근거 ID(`EV01` 등)를 적는다.

**핵심 부분 (2점이면 필수):** 하위 조건 중 일부만 핵심이면 그 원문 표현을, 기준 전체가 핵심이면 `전체`를 `core_part`에 적는다. 빈칸은 표시 누락으로 걸린다. 그 핵심 부분 판정에 필요한 정보를 `core_info`에 적는다. 핵심 부분은 이 단계에서 정해 잠그며, 생성 질문을 본 뒤 바꾸지 않는다.

근거 ID는 공통 근거 목록에서 `review_status`가 "고정"인 항목만 쓸 수 있다.

판정 직접성(`decisiveness`)은 주석하지 않는다 (2026-11-04 확정).

**추측하지 않는다.** 이 환자가 해당될 가능성, 질병의 일반적 경향, 여러 시험에 공통인지 여부, 질문 수 제한은 점수에 반영하지 않는다.

### 3.4 공유정보 군집

서로 다른 기준이 **같은 사실**을 필요로 하면 `shared_cluster_template.csv`에 같은 `cluster_id`로 적고 `shared_fact`에 그 사실을 쓴다. 기간·대상·측정값이 다르면 묶지 않는다. 같은 질환이라는 이유만으로 묶지 않는다. 군집이 없으면 빈 표로 제출한다.

### 3.5 판단 근거 기록

`rationale`에 판단 이유를 한 문장 이상 적고 기준 원문의 표현을 인용한다. `rater_id`에는 배정받은 ID를 적는다. 다시 봐야 하면 `needs_review`에 Y를 적는다.

### 3.6 제출

제출 전에 관리자에게 형식 검사(`annotation_tools.py check`)를 요청하거나 직접 실행한다. 빈 칸, 값 오류, 사유 없는 UNSURE를 찾아 준다. 완성한 파일을 조정자에게 제출한다. 제출 후 혼자 수정하지 않는다.

---

## 4. 불일치 확인과 확정 (조정자, 관리자)

| 순서 | 작업 | 담당 | 비고 |
|---|---|---|---|
| 1 | `askable`, 핵심성, 근거·핵심 부분 문구, 군집의 불일치 비교 | 관리자 | `annotation_tools.py compare`. 일치율·κ와 조정 양식을 만든다 |
| 2 | 조정 양식 확인 | 조정자 | 값이 다르거나 양쪽 모두 UNSURE인 항목, 그리고 한 명이라도 핵심성 2점을 준 기준의 근거·핵심 부분 문구 차이가 들어 있다 |
| 3 | 두 주석자 토의, 미합의 시 조정자 결정 | 주석자, 조정자 | `final_value`, `reason`, `adjudicator_id` 기록 |
| 4 | H 계산 | 스크립트 | 확정 핵심성 2점이 H |
| 5 | 확정표 생성 | 관리자 | `annotation_tools.py finalize`. 조정이 비었거나 낡았으면 만들지 않는다 |
| 6 | 군집표 확정 | 조정자 | 환자별 1개 |
| 7 | 형식 검증 | 관리자 | `05_5_preflight_review.md`의 명령 |
| 8 | 담당자 기록 작성, 잠금 | 관리자 | 아래 5절 |

확정표 열: `patient_id`, `trial_id`, `criterion_id`, `final_askable`, `final_centrality`, `final_centrality_evidence`, `final_core_part`, `final_core_info`, `h_strict`, `h_any`, `adjudication_note`

- `h_strict`: `final_centrality`가 2이면 `true`, 아니면 `false`
- `final_centrality_evidence`: 2점이면 필수. 근거 ID는 잠금 시 근거 목록과 대조된다
- `final_core_part`, `final_core_info`: 2점 기준에는 필수(`전체` 포함), 다른 기준에는 비운다
- `h_any`: 조정 전 한 주석자라도 핵심성 2이면 `true`
- `final_askable`: UNSURE를 남길 수 없다. 조정으로 나머지 세 값 중 하나로 정한다.
- 핵심성이 끝까지 UNSURE이면 `h_strict`는 `false`이다. 건수를 기록한다.
- 위 계산은 `annotation_tools.py finalize`가 한다. 손으로 고치면 잠금 검사에서 거부된다.
- 환자별 H가 0개여도 잠금은 가능하다. 그 환자의 M4a는 값 없음으로 보고된다. 임의로 H를 늘리지 않는다.
- 공통 근거 목록에 `작성·검토 대기` 행이 남아 있으면 잠금이 거부된다.

행은 **후보 기준만** 넣는다. 환자별 후보와 정확히 같아야 잠긴다 (S004 13행, S008 23행).

---

## 5. 최종 주석 파일 잠금 (관리자)

저장 위치와 이름은 고정이다.

```text
evaluation/preannotation/S004_final.csv
evaluation/preannotation/S008_final.csv
evaluation/preannotation/S004_clusters.csv
evaluation/preannotation/S008_clusters.csv
evaluation/preannotation/safety_evidence.csv   # 근거 목록. 쓰지 않으면 머리글만 있는 파일
```

1. `annotation_record_template.json`을 복사해 초안을 만든다.
2. 다음을 사람이 채운다: 핵심 기준(M4a) 정의 검토 결과, 판정기 확인자, 담당자별 역할과 정답 노출 범위.
3. 형식 검증 후 잠금 명령을 실행한다.
4. 잠금은 **1회만** 가능하다. 잠금 후 파일이 바뀌면 유료 실행이 차단된다.
5. 오류를 발견하면 원본을 두고 변경 사유와 영향 범위를 기록한다.

잠금 전에는 질문 생성을 시작하지 않는다.

---

## 6. 파일럿 전용: 미검증 AI 사전 주석 (2026-11-05)

**적용 범위:** 파일럿 S004·S008만. 확인 실험 네 환자에는 적용하지 않는다(실행기가 거부한다). 목적은 절차와 지표의 점검이며, 사람 주석과 같은 신뢰도를 주장하지 않는다.

**바뀌는 것 (지침 2절 2~3번 대체):** 사람 주석자 2명의 독립 작성과 조정 대신, AI 주석 1부를 값 변경 없이 확정표로 옮긴다. 상태는 **"AI 주석 버전 고정"**으로 기록한다. "사람 검수 완료"나 "전문가 확정"으로 쓰지 않는다.

**그대로인 것:** 핵심성 2점 = H, 2점의 근거·핵심 부분 필수, 고정 근거 목록 대조, UNSURE 처리, 잠금 1회, 잠금 전 질문 생성 금지, 같은 환자의 모든 조건·반복에 같은 확정표 사용.

| 순서 | 작업 | 명령·파일 |
|---|---|---|
| 1 | AI 초안 원본 보관 (수정 금지) | `evaluation/preannotation/ai_draft/source/` |
| 2 | 형식 검사 (원본 주석표와 `annotation_id` 대조) | `annotation_tools.py check S004 <AI 초안>` |
| 3 | 확정표로 옮김. 값은 바꾸지 않는다. askable UNSURE가 있으면 거부한다. 군집이 없으면 머리글만 쓰고 "미주석"으로 표시한다 | `annotation_tools.py finalize-ai S004 <AI 초안> --out evaluation/preannotation` |
| 4 | 작성 이력·검토 기록 | `ai_draft/ai_annotation_log.md`, `ai_draft/annotation_record_draft.json`의 `annotation_source` |
| 5 | 사람 기록 칸 작성 (M4a 정의 검토, 판정기 확인, 담당자·정답 노출) | 기록 초안을 복사해 사람이 채운다 |
| 6 | 잠금 | `run_pilot.py lock-annotation <기록 초안>` |

**잠금 검사가 추가로 보는 것** (`run_pilot.py`의 `ai_source_problems`):
- 환자가 S004·S008뿐인지
- 상태가 "AI 주석 버전 고정"이고 `human_item_review`가 `false`로 명시되었는지
- 작성 도구·모델·입력·시점이 적혀 있는지 (모르면 "미확인")
- AI 원본 해시
- 확정표 값이 AI 원본과 같은지. 다르면 거부한다. AI 값을 고쳐야 하면 수정 전후 값·이유·근거·수정 주체를 적고 새 버전으로 다시 고정한다.

**보고:** 사전 주석은 "미검증 AI 주석", 질문 채점은 "사람의 채점"으로 구분한다. M4a는 "AI가 핵심으로 분류한 기준의 커버리지"로 쓴다. 한계는 `ai_annotation_log.md` 5절을 따른다. 채점자가 1명이면 "단일 평가자"로 적고 일치도·κ를 보고하지 않는다. 채점자가 정답 노출자이면 "정답 노출 연구자의 탐색적 채점"으로 적고 독립 평가로 보고하지 않는다(`04_annotation_guideline.md` 1절). `report`가 이 표시를 출력에 넣는다.
