# 질문 생성 프롬프트 Ablation 실험

Agent 5 질문 프롬프트 v2.3.3의 전체 효과와 규칙별 기여를 통제 실험으로 검증한다. 개발 환자 S004·S008로 하는 파일럿은 탐색 연구이며 가설을 입증하지 않는다.

**판정 프롬프트, 공용 코드, 기존 평가 데이터는 수정하지 않는다.** 실험 코드는 모두 이 폴더에 있다.

## 폴더 구성

| 경로 | 내용 |
|---|---|
| `01`~`04_*.md` | 분석, 설계, 프롬프트 비교, 루브릭, 오류 분류, 주석 지침 |
| `prompts/` | 조건별 프롬프트, diff, `manifest.json` |
| `build_prompts.py` | 프롬프트 생성·검증 |
| `run_pilot.py` | 실행기 |
| `pilot_lock.json` | 고정 값 (모델, 프롬프트, 판정기, 시뮬레이터, 데이터 해시) |
| `evaluation/` | 채점 도구, 사전 주석 보조(`annotation_tools.py`), 양식, 사전 주석표, 가상 예시 |
| `tests/` | 실행기 테스트 |
| `dryrun/` | mock 실행 결과 |
| `cost_estimate.md` | 비용 추정 |
| `06_preflight_checklist.md` | STEP 6 실행 전 점검표 |

실제 결과는 `data/processed/question_ablation/<실험 ID>/`에 저장된다. 기존 결과 파일은 건드리지 않는다.

## 환경

저장소 밖의 격리 가상환경을 쓴다. 저장소 최상위에서 실행한다.

```bash
py -3.11 -m venv ../.venv-question-ablation
../.venv-question-ablation/Scripts/python.exe -m pip install "anthropic>=1.11" "python-dotenv>=1.0" "pydantic>=2.0" "requests>=2.31" certifi
```

이후 `PY=../.venv-question-ablation/Scripts/python.exe`로 표기한다. Windows에서는 `PYTHONIOENCODING=utf-8`을 함께 설정한다.

## 무료 명령

```bash
$PY experiments/question_ablation/build_prompts.py --check        # 프롬프트 검증 53건
$PY experiments/question_ablation/evaluation/tests/test_scoring.py # 채점 도구 28건
$PY experiments/question_ablation/tests/test_run_pilot.py          # 실행기 55건
$PY experiments/question_ablation/evaluation/tests/test_annotation_tools.py  # 주석 보조 10건
$PY experiments/question_ablation/evaluation/annotation_tools.py check|compare|finalize ...  # 사전 주석 검사·일치도·확정표
$PY experiments/question_ablation/run_pilot.py check               # 평가 분모, 고정 값, 유료 실행 조건
$PY experiments/question_ablation/run_pilot.py plan                # 실행 순서 30건
$PY experiments/question_ablation/run_pilot.py estimate            # 호출 수·비용
$PY experiments/question_ablation/run_pilot.py dry-run --out <새 폴더>
```

dry-run은 API 키와 사전 주석 없이 동작한다. 응답은 모두 가짜이며 결과 폴더에 `mock: true`로 표시된다. 실제 결과 폴더에 섞을 수 없다.

## 실행 순서

```bash
# 0. 유료: 연동 테스트 (분석 제외). ping은 잠금 없이, questions·downstream은 잠금 후. 단계마다 승인
$PY experiments/question_ablation/run_pilot.py smoke ping --experiment smoke1 --paid smoke1
# 1. 사전 주석 확정 파일을 evaluation/preannotation/에 둔 뒤 잠금
$PY experiments/question_ablation/run_pilot.py lock-annotation <작성한 기록.json>
# 2. 유료: 질문 생성 30회. --paid에 실험 ID를 다시 적어야 시작된다
$PY experiments/question_ablation/run_pilot.py questions --experiment pilot1 --paid pilot1
# 3. 무료: 채점표 생성
W=data/processed/question_ablation/pilot1
$PY experiments/question_ablation/run_pilot.py packet --workspace $W --seed <비공개 정수>
# 4. 유료: 핵심 4조건 후속 판정. 결과 파일은 열지 않는다
$PY experiments/question_ablation/run_pilot.py downstream --experiment pilot1 --paid pilot1
# 5. 무료: 평가자 비교 → 조정 → 확정 → 잠금
$PY experiments/question_ablation/run_pilot.py compare-raters <평가자1 폴더> <평가자2 폴더> --out $W/scores
$PY experiments/question_ablation/run_pilot.py merge --workspace $W --primary <평가자1 폴더> --adjudication $W/scores/adjudication.csv
$PY experiments/question_ablation/run_pilot.py lock-scores --workspace $W
# 6. 무료: 잠금 후 조건 공개, 시뮬레이터 감사, 정답 대조
$PY experiments/question_ablation/run_pilot.py sim-audit --workspace $W
$PY experiments/question_ablation/run_pilot.py report --workspace $W --registry <담당자 기록.csv> --sim-audit $W/scores/simulator_audit.csv
```

중단되면 같은 명령을 다시 실행한다. 완료된 실행은 건너뛴다. 결과가 저장된 실행은 다시 뽑지 않는다.

## 실행기 동작

| 항목 | 동작 |
|---|---|
| 호출 단위 | 질문: 실행당 1회. 시뮬레이터: 1회. `reassess`: 대상 시험당 1회. `final_check`: 시험당 1회. |
| 코드 재사용 | `write_questions`, `arrange`, `next_round`, `answer_questions`, `reassess`, `final_check`를 그대로 호출한다. `ask_json`만 실행 중에 기록 함수로 바꾼다. |
| 재시도 | 형식 실패(JSON, 스키마, `max_tokens` 절단, 답변 개수·순서)만 1회. 2회 실패하면 실패로 기록하고 다시 뽑지 않는다. |
| 전송 재시도 | SDK 기본값(2회: 연결 오류, 408, 409, 429, 5xx). 응답 내용을 보기 전의 재시도이므로 표본 선택과 무관하다. |
| 거부 | `refusal`은 재시도하지 않고 기록한다. `fallbacks`는 쓰지 않는다. 다른 모델로 넘어가면 모델 고정이 깨지기 때문이다. |
| API 오류 | 결과를 남기지 않고 재개 시 다시 시도한다. 3회 연속이면 중단한다. |
| 코드 버그 | API 오류로 처리하지 않고 즉시 멈춘다. |
| D9 | 0.5 미만은 휴리스틱 표시일 뿐이다. 오류 판정이나 재생성 사유가 아니다. |

## 데이터 분리

| 데이터 | 접근 위치 |
|---|---|
| 질문 생성 입력 | 짧은 환자 설명, 기준 원문, 초기 판정. 상세 설명과 정답을 읽지 않는다. |
| 상세 설명 (Fact Sheet) | 시뮬레이터 호출 전용. 저장 파일에 넣지 않는다. |
| 정답 | `report`에서 잠금 통과 후에만 읽는다. |
| 조건 매핑 | `sealed/`. 평가자에게 주지 않는다. |
