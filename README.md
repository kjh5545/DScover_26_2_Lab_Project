# DScover_26_2_Lab_Project

디스커버(DScover) 26-2 랩실 산학협력 프로젝트: **인터랙티브 임상시험 추천 멀티 에이전트**

성균관대 AIHC Lab의 *Healthcare Agentic AI Challenge 2026* 주제를 그대로 수행합니다. 짧은 환자 설명을 받아 ClinicalTrials.gov에서 임상시험을 찾고, 선정·제외 기준과 한 줄씩 대조해 판정하고, 모자란 정보는 질문으로 채운 뒤, 적절한 임상시험을 근거와 함께 추천하는 시스템을 만듭니다.

- 평가 비중: 매칭 정확성 30% · 랩 내 정성 평가 30% · 발표 40%
- 판정 모델: Claude Sonnet 5.5 (팀 결정)

## 진행 상황

| 단계 | 내용 | 상태 |
|---|---|---|
| 사전 실험 | S005(편두통)로 수작업 스크리닝 → 판정 규칙 도출 → 프롬프트 v2 | 완료 |
| 자동 평가 | Claude API로 반복 실행, 모델 4개 비교, 규칙 보완한 프롬프트 v3 | 완료 |
| 정답 레이블 | 팀원 2명이 환자 9명 × 시험 15개, 기준 173개를 직접 판정 (공동 판정 일치도 93%) | 완료 → `goldset/` |
| 에이전트 1 · 2 | 환자 정보 이해, 후보 검색 | 코드 작성 (`agents/`) |
| 에이전트 3–7 | 기준 파싱, 매칭, 질문 생성, 재평가, 추천·설명 | 진행 예정 |

## 폴더 구조

```
.
├── agents/        에이전트 코드 (schemas.py = 에이전트 간 데이터 형식 약속)
├── eval/          자동 평가 도구 (run_eval.py, compare.py), 판정 규칙 프롬프트 v2·v3
├── goldset/       최종 평가 세트 v1 (goldset_v1.json = 평가 입력 겸 원본, 평가세트_v1.md = 사람용)
├── screening/     사전 실험 기록, 팀원 레이블 원본 시트(labeling/스크리닝1, 스크리닝2)와 변환 도구
├── synthetic-patients.json   대회 제공 예시 환자 10명
├── info.txt       대회 공고
├── 사전실험_정리.md / API_자동평가_정리.md   실험 정리 문서 (노션용)
└── requirements.txt
```

## 시작하기

```bash
pip install -r requirements.txt
```

API 키는 `eval/.env.example`을 복사해 `eval/.env`로 이름을 바꾸고 키를 넣습니다. **`.env`는 git에 올라가지 않으며, 키를 코드나 채팅에 붙여넣지 마세요.** 팀 공용 키라 실행 전에 예상 비용을 공유합니다.

### 에이전트 실행
```bash
python -m agents.patient_agent                                            # 1번: 환자 10명 → outputs/patient_profiles.json
python -m agents.search_agent --profiles outputs/patient_profiles.json   # 2번: 후보 시험 검색
python -m agents.search_agent --condition "bladder cancer" --age 68 --sex male   # 검색만 따로
```

### 자동 평가
```bash
cd eval
python run_eval.py --smoke                                                          # 연결 확인
python run_eval.py --goldset --rules rules_prompt_v3.md --models claude-sonnet-5-5 --repeats 3   # 평가 세트로 채점
python compare.py --a runs/<A 실행> --b runs/<B 실행> --cases-file ../goldset/goldset_v1.json --out 비교.md
```
결과는 `eval/runs/<날짜_시간>/report.md`에 저장됩니다.

## 판정 규칙 (팀 합의)

| 판정 | 뜻 |
|---|---|
| 통과 | 이 기준 때문에 탈락하지 않음이 환자 정보로 확인됨 |
| 탈락 | 이 기준 때문에 탈락함이 환자 정보로 확인됨 |
| 모름 | 지금 환자에게 물어보면 알 수 있지만 정보가 없음 |
| 등록 후 확인 | 시험에 지원한 뒤에야 생기는 정보 |

- 동의서·참여 의사·순응 의사 기준, 내용이 공개되지 않은 기준("Other", "프로토콜에 정의됨")은 **등록 후 확인**
- 논리적으로 탈락을 추론할 수 있어도 환자 설명에 명시되지 않았으면 **모름**
- 최종 판단: 적격 / 부적격 / 정보 부족. "적격 가능(등록 후 확인 필요)" 추가 여부는 실험 후 결정
- 자세한 내용: `goldset/평가세트_v1.md`

## 주요 결과

- 수작업에서 찾은 규칙을 프롬프트에 넣자 정답 일치가 10개 중 5개 → 10개로 증가 (사전 실험)
- 규칙 3개를 보완한 v3에서 모델 4개 모두 최종 판단 18/18 일치, Opus는 기준 100%, Sonnet 5.5는 99% (S005 케이스 기준)
- 자세한 내용: `사전실험_정리.md`, `API_자동평가_정리.md`, `eval/결과_2차_v3비교.md`

## 데이터 출처

- 임상시험 정보: [ClinicalTrials.gov](https://clinicaltrials.gov) API v2 (미국 국립의학도서관 NLM 제공 공개 데이터)
- 예시 환자: 대회 주최 AIHC Lab 제공 합성 데이터 (`synthetic-patients.json`, 실제 환자 정보 아님)
- 정답 레이블: 팀원 직접 작성

## 의료 면책

이 프로젝트의 진단 추정, 판정, 추천은 과제·연구용이며 의학적 자문이 아닙니다. 실제 임상시험 참여 여부는 담당 연구진과 의료진이 판단합니다.
