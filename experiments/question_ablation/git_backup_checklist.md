# Git 백업 점검표

**승인 전에는 `git add`, `commit`, `push`를 실행하지 않는다.** 2026-11-02 기준 브랜치 `exp/question-ablation`, HEAD `7c7b7f8`, 미추적 항목은 `experiments/question_ablation/`뿐이다.

**2026-11-03 기록:** 사용자 승인으로 4절 점검을 모두 통과한 뒤 로컬 커밋 `c9b71a9`를 만들었다 (56개 파일, 모두 실험 폴더 안). `.env`, `sealed/`, 결과 폴더, `__pycache__`는 포함되지 않았고 키 패턴 검색 결과는 없었다. 작성자는 사용자 요청으로 seohyun jung으로 지정하였다 (이 커밋에만 적용, 전역 설정 변경 없음). 푸시는 하지 않았다. 3절의 줄바꿈 규칙은 아직 추가하지 않았다 (잠긴 주석 커밋 전에 필요).

## 1. 파일 분류

| 분류 | 경로 | 처리 | 근거 |
|---|---|---|---|
| 연구 문서 | `01`~`06_*.md`, `05_5_*.md`, `M4a_team_review.md`, `annotation_workflow.md`, `phase6_execution_plan.md`, `git_backup_checklist.md`, `README.md`, `cost_estimate.md` | 포함 | 재현 기록 |
| 프롬프트 | `prompts/*.txt`, `manifest.json`, `diffs/`, `.gitattributes` | 포함 | 해시 고정 대상 |
| 실행 코드 | `run_pilot.py`, `build_prompts.py`, `evaluation/scoring.py`, `scoring_schema.json` | 포함 | |
| 고정 기록 | `pilot_lock.json` | 포함 | 실행 조건의 기준 |
| 테스트 | `tests/`, `evaluation/tests/`, `evaluation/test_results.txt`, `dryrun/` | 포함 | mock 결과만 있음 |
| 주석·평가 양식 | `evaluation/templates/`, `evaluation/preannotation/S00x_preannotation.csv`, `evaluation/examples/` | 포함 | 빈 양식. 환자 문구는 추적 중인 `goldset/`과 같음 |
| 잠금 주석 | `S00x_final.csv`, `S00x_clusters.csv`, `annotation_record.json` | 잠금 후 포함 | 아래 3절의 줄바꿈 처리 선행. 담당자는 가명 ID |
| 가상환경 | `../.venv-question-ablation` | 제외 | 저장소 밖 |
| API 키 | `.env`, `eval/.env` | 제외 | 저장소 `.gitignore`가 이미 차단 |
| 조건 매핑 | `sealed/` | 제외 | 실행 시 생기는 `.gitignore`가 차단 |
| 생성 결과 | `data/processed/question_ablation/` | **제외** | **현재 무시되지 않는다.** 아래 2절 |
| 비용 기록 | `attempts/`의 호출 기록 | 제외 | 원시 출력 포함. 정산 요약만 문서로 남긴다 |
| 담당자 실명표 | 실명 ↔ 가명 ID 대응 | 제외 | 저장소 밖 보관 |
| 실제 환자 정보 | 새로 추가한 것 없음 | 해당 없음 | 사례가 실제 환자인지는 저장소만으로 판단할 수 없어 팀 확인 |

## 2. 확인된 위험

| 위험 | 내용 | 대응 |
|---|---|---|
| 결과 폴더가 무시되지 않음 | `git check-ignore`에서 `data/processed/question_ablation/`이 걸리지 않았다. 실험 폴더의 `.gitignore`는 `sealed/`만 막는다. | `git add .`와 `git add data` 금지. 경로를 지정해 추가. 필요하면 공유되지 않는 `.git/info/exclude`에 추가 (승인 필요). |
| 푸시가 맹검을 깬다 | 원격에 올리면 평가자가 조건명, 프롬프트, 루브릭을 볼 수 있다. | **채점 잠금 전에는 로컬 커밋까지만 한다.** |
| 공용 파일 | 저장소 `.gitignore`는 공용 파일이다. | 수정하지 않는다. |

## 3. 커밋 전 해결 사항

**잠금 파일의 줄바꿈:** 이 환경은 `core.autocrlf=true`이다. `.gitattributes`는 프롬프트만 보호한다. 주석 파일 잠금은 바이트 해시이므로, 줄바꿈이 바뀌어 체크아웃되면 해시가 달라져 유료 실행이 차단될 수 있다. 잠긴 주석을 커밋하기 전에 다음 규칙을 `experiments/question_ablation/.gitattributes`에 추가하길 권장한다 (승인 필요).

```text
evaluation/preannotation/*.csv -text
evaluation/preannotation/annotation_record.json -text
```

## 4. 로컬 커밋 전 점검

| 상태 | 항목 |
|---|---|
| ☐ | 브랜치가 `exp/question-ablation`이다 |
| ☐ | 테스트 53 + 28 + 47건이 통과했다 |
| ☐ | `run_pilot.py check`에서 `versions`가 통과하고 `outside_changes`가 비어 있다 |
| ☐ | `git diff --cached --name-only` 결과가 모두 `experiments/question_ablation/` 아래이다 |
| ☐ | 추가 대상에 `.env`, `sealed/`, 실제 결과가 없다 |
| ☐ | `sk-ant-` 패턴 검색 결과가 없다 |
| ☐ | 실명이나 정답 노출 실명 기록이 없다 |

커밋은 고정 값을 바꾸지 않는다. `pilot_lock.json`의 대조 대상은 `versions`뿐이고 `git_head`는 비교 대상이 아니다. 실행 후 기록되는 커밋 값만 새 커밋으로 남는다.

## 5. 승인 후 사용할 명령 (PowerShell, 지금 실행하지 않음)

```powershell
git branch --show-current
git add -- experiments/question_ablation
git diff --cached --name-only
git diff --cached --name-only | Select-String -NotMatch '^experiments/question_ablation/'
git grep --cached -n 'sk-ant-' -- experiments/question_ablation
```

네 번째와 다섯 번째 명령은 출력이 없어야 한다.

## 6. 권장 커밋 메시지

```text
실험: 질문 프롬프트 ablation STEP 1~5.5 산출물 추가

설계·프롬프트 5종·루브릭·채점 도구·실행기·테스트·점검 문서를 추가한다.
유료 실행 결과와 사전 주석 결과는 포함하지 않는다.
공용 코드, 판정 프롬프트, 평가 데이터는 변경하지 않았다.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

## 7. 원격 작업

원격 작업은 별도 승인 사항이다. 채점 잠금 전 푸시 금지를 권장한다. 팀이 백업을 위해 먼저 푸시하기로 하면 평가자의 조건 노출로 기록해야 한다.
