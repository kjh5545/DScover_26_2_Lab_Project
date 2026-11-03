# STEP 5.5 실행 전 점검

점검일: 2026-11-02. **유료 API 호출, `git add`, commit, push를 실행하지 않았다.** 기존 연구 산출물은 변경하지 않았고, 이 문서를 포함한 새 문서 5개만 추가하였다.

**결론: 현재 유료 실행 불가.** 실행기는 `[차단] 사전 주석 기록 없음`으로 멈춘다 (PowerShell, exit 2).

표기: **[확인]** 이번에 직접 확인한 사실. **[팀]** 사람이 결정·확인할 사항.

---

## 1. 현재 상태 [확인]

| 항목 | 결과 |
|---|---|
| 브랜치, HEAD | `exp/question-ablation`, `7c7b7f8` |
| Git 상태 | 추적 파일 변경 0건. `experiments/question_ablation/`만 미추적 |
| 원격 상태 | 확인하지 않음 (Git 원격 작업 미승인) |
| 프롬프트 5종 해시 | `pilot_lock.json`과 일치 |
| 프롬프트 검증 | 53/53 통과 |
| 채점 도구 테스트 | 28/28 통과 |
| 실행기 테스트 | 47/47 통과 |
| `check` | versions 통과, 실험 폴더 밖 변경 없음, annotation 차단, `api_key_present: false` |
| 평가 분모 | S004 19/13/6, S008 27/23/4, 설계와 일치 |
| 사전 주석 | 후보 36개 모두 비어 있음 |
| `06_preflight_checklist.md` | 전 항목 미표시. 사람이 확인하므로 임의로 표시하지 않음 |

| 프롬프트 | SHA-256 앞 16자리 |
|---|---|
| C0 | `ec97da014bcfdc5e` |
| C_full | `da845f66efbb1681` |
| A1 | `af5ae19b697a6048` |
| A2 | `ed0ac5be71424b91` |
| A2s | `ac7d6c52495093fc` |

`pilot_lock.json`에는 "미충족 조건" 필드가 없다. 고정 값만 있고, 미충족 여부는 `check`와 `annotation_record.json`으로 판단한다.

---

## 2. 이번 점검에서 새로 발견한 사항

| 번호 | 발견 | 영향 | 대응 |
|---|---|---|---|
| 1 | **소규모 실행 CLI가 없다.** `questions`는 항상 30회 전부 실행한다. | Phase 6A를 현재 명령으로 실행할 수 없다. | `smoke` 명령 구현 승인 필요. 다른 실험 ID로 `questions`를 실행하면 안 된다. |
| 2 | `report`는 1회만 실행할 수 있다. | 6C에서 M1~M7만 먼저 집계할 수 없다. | 6D 끝에서 함께 집계 |
| 3 | 사전 주석 일치도 계산, 등급 계산, 확정표 생성 도구가 없다. | 수작업 오류 위험. 등급은 "계산"이라고 지침에 있으나 CLI가 없다. | 수동 수행 또는 보조 스크립트 승인 |
| 4 | 잠금 전 검증 전용 명령이 없다. `lock-annotation`은 검증에 통과하면 바로 잠근다. | 시험 삼아 실행할 수 없다. | 7절의 비잠금 검증 사용. 등급과 `h_strict`의 일치는 이 검증도 보지 않는다. |
| 5 | `.env`는 파일 존재만 검사한다. | 빈 파일도 키 있음으로 표시된다. | 6A-0에서 실제 인증 확인 |
| 6 | SDK 버전은 대조 대상이 아니다. | SDK를 올리면 API 버전이 바뀌어도 차단되지 않는다. | 가상환경의 SDK를 올리지 않는다. 다른 PC 실행 금지 또는 `anthropic==2.3.0` 설치 |
| 7 | 응답 `model`이 가격표에 없으면 비용이 0으로 기록되고 멈추지 않는다. | 모델 불일치를 놓칠 수 있다. | 6A에서 확인. `attempts/`의 `model` 필드 점검 |
| 8 | `lock-scores`와 `merge`는 재실행 시 덮어쓴다. | 잠금 후 수정이 코드로 막히지 않는다. | 1회만 실행, 해시 별도 기록 |
| 9 | 결과 폴더가 `.gitignore`에 없고, 잠긴 CSV는 줄바꿈 보호가 없다. | 실수 커밋, 해시 불일치 | [git_backup_checklist.md](git_backup_checklist.md) |
| 10 | 설계의 "M4a 상한 병기"가 구현되어 있지 않다. | 보고 누락 가능 | [M4a_team_review.md](M4a_team_review.md) 결정 6번 |
| 11 | 비용 초과 자동 차단이 없다. | $4.05 중단 조건은 사람이 지켜야 한다. | 6B 후 정산 |

---

## 3. M4a와 사전 주석

- M4a 검토 자료: [M4a_team_review.md](M4a_team_review.md). 1~3절만 주석자에게 전달할 수 있다.
- 주석 절차: [annotation_workflow.md](annotation_workflow.md). 전체를 주석자에게 전달할 수 있다.

**평가 분모 (운영자용):** 전체 46개 중 후보 36개가 주 평가 모집단이다. 비후보 10개(pass 5, post_enrollment 5)는 질문 대상이 아니며 M8d의 분모로만 쓴다. 후보 36개는 M8a 15개와 M8b 21개로 나뉜다. 환자별로 M8a 6, 9, M8b 7, 14, M8d 6, 4이다. 이 수치는 정답에서 나오므로 주석자에게 주지 않는다.

---

## 4. 담당자와 정답 노출

### 4.1 역할안 (4인) [팀]

실제 이름과 노출 여부는 정하지 않았다. 아래 P1~P4를 팀이 배정한다.

| 사람 | 역할 | 조건 |
|---|---|---|
| P1 | 실험 운영 관리자 | 채점하지 않음. 질문 프롬프트 작성자가 맡기 적합 |
| P2 | 사전 주석자 1, 블라인드 채점자 1 | 질문 프롬프트 작성자가 아닐 것 |
| P3 | 사전 주석자 2, 블라인드 채점자 2 | 질문 프롬프트 작성자가 아닐 것 |
| P4 | 불일치 조정 담당 (주석, 채점) | 해당 단계의 평가자가 아닐 것 |

### 4.2 겸임과 이해상충

| 조합 | 판단 | 이유 |
|---|---|---|
| 사전 주석자 + 채점자 | 가능 | 지침이 허용. 주석 내용을 기억한 채 채점한다는 한계는 보고 |
| 관리자 + 프롬프트 작성자 | 가능 | 채점에 참여하지 않음 |
| 관리자 + 채점자 | **불가** | 조건 매핑 접근 |
| 조정자 + 같은 단계 평가자 | **불가** | 자기 판단을 조정 |
| 프롬프트 작성자 + 주석자·채점자 | **불가** | 질문 의도를 안다 |
| 프롬프트 작성자 + 조정자 | 피함 | 지침상 금지는 아니나 불일치 세트의 출처를 짐작할 수 있음 |
| 판정기 담당자 + 채점자 | 주의 | 가능하나 판정 관련 노출 범위 기록 |
| M4a 4~6절 검토자 + 주석자 | 피함 | 가설을 알고 주석하게 됨. 1~3절로 승인 |

실행기는 역할 조합을 검사하지 않는다. 사람이 지켜야 한다.

### 4.3 기록 방법

양식 2개를 쓴다. `annotation_record.json`의 `people`과 `rater_registry.csv`의 내용이 같아야 한다. `report`에 `--registry`를 넘기지 않으면 독립 평가로 표시되지 않는다.

ID는 `P1`처럼 가명을 쓴다. `gold_exposed`는 `none`, `partial`, `full` 중 하나이고, `exposure_scope`에 다음을 본인 신고로 적는다.

```text
gold:<본 정답 범위>; factsheet:<본 상세 설명 범위>; prior_questions:<과거 생성 질문을 본 환자>; prompts:<본 프롬프트>; 시점:<주석 전|채점 전|채점 후>
```

저장소에는 정답 시트와 상세 설명이 추적되어 있으므로, 사본을 가진 사람은 접근할 수 있었다. 노출 여부는 **접근 가능성이 아니라 본인 신고**로 적는다.

### 4.4 독립 평가로 주장할 수 없는 범위

| 상황 | 주장 불가 | 주장 가능 |
|---|---|---|
| 주석자 1명 이상 정답 노출 | 사전 주석이 정답과 독립이라는 주장. H 정의의 정답 블라인드 | 지침에 따른 사전 잠금 |
| 평가자 1명 이상 정답 노출 | 독립적인 정답 블라인드 평가, 정답 관련 판단의 독립성 | 조건 블라인드 채점 |
| 조정자 노출 | 조정 결과의 정답 블라인드 | 조건 블라인드 조정 |
| 과거 생성 질문을 본 주석자 | 질문과 독립인 사전 주석 | 해당 범위를 밝힌 주석 |
| 시뮬레이터 감사 뒤 | 평가자가 Fact Sheet 미노출 상태라는 주장 | 잠금 전 채점의 미노출 |
| 주석자 1명 | `h_strict`와 `h_any`의 분리, 주석자 일치도 | 1인 주석임을 밝힌 결과 |
| 전원 `none`이어도 | 외부 독립 평가, 일반화 | 내부 파일럿의 블라인드 수행 |

조건 블라인드는 정답 노출과 별개이므로 그대로 유지한다.

---

## 5. 판정기 고정 확인 자료

**아래 값은 저장소 사실이며 팀 승인이 아니다.** `judge_freeze_confirmed_by`는 비워 둔다.

| 항목 | 현재 고정 값 [확인] | 인선 님·주희 님 확인 [팀] |
|---|---|---|
| 판정 프롬프트 버전 | `matcher.SYSTEM_PROMPT` (v3, 2026-10-12), 규칙 1~10. `404e82537c0ccab4…` | 이 버전을 파일럿에 쓰는가 ☐ |
| 답변 지시문 | `ANSWERS_HEADER`, `c18310c28d33c5d4…` | 변경 예정이 없는가 ☐ |
| 판정 코드 commit | `7c7b7f8`. `matcher.py` blob `6558ccd1…`, `pipeline.py` `479e937d…`, `rule_checks.py` `a2b05683…` | 원격 `main`의 변경 여부 확인, 변경이 있어도 이 커밋을 유지하는가 ☐ |
| 규칙 11·12 | 현재 프롬프트에 없음. 10/18 실험 후 보류. 브랜치 `exp/judge-rules-11-12`, 커밋 `cfed391`, `docs/실험_판정규칙11-12_보류.md` | 파일럿에서 미포함으로 고정하는가 ☐ |
| "기억나지 않아요" | 전용 규칙 없음. 지시문은 "unsure, have not checked"만 unknown으로 둔다. 10/22 기록상 S008 E1을 없음으로 읽어 통과 처리. 시뮬레이터도 "기억이 잘 안 나요"류로 답할 수 있다. 팀 안건 미결 | 현행 고정 또는 처리 방침 결정 ☐ |
| Agent 4·6 연결 | `reassess` → `match_with_rules` → `match` → `ask_json`, 이후 `apply_code_checks`, `validate_judgments`. 답변은 `ANSWERS_HEADER`와 함께 입력. `final_check`는 `reassess(full=True)`. `reassess`는 답과 관련된 기준만 다룸 | 이 연결이 현행과 같은가 ☐ |
| 초기 판정 | `goldset_cache_v3_claude-sonnet-5-5`의 캐시 4개를 재호출 없이 사용 | 파일럿 시작점으로 유지하는가 ☐ |
| 모델·호출 설정 | `claude-sonnet-5-5`, `max_tokens` 16000, `thinking: adaptive`, 일반 호출(배치 아님), 캐시 없음 | 회의 결정과 같은가 ☐ |
| 해시 고정 방법 | `pilot_lock.json`의 해시·blob을 `check`와 유료 실행마다 대조. 다르면 차단 | 방법에 동의하는가 ☐ |

판정기가 바뀌면 M1~M7a는 유지되지만 M8은 다시 측정해야 한다. 잠금 후 변경은 실행기가 차단한다. 임의로 `pilot_lock.json`을 재생성하지 않는다.

---

## 6. API 모델과 실행 환경 [확인]

| 항목 | 결과 | 근거 |
|---|---|---|
| 모델 ID | `claude-sonnet-5-5` | 코드, lock, 공식 Models overview 일치 |
| 가격 | 입력 $2, 출력 $10 / MTok | 코드와 공식 문서 일치 |
| `temperature`, `top_p`, `top_k` | **요청에 없음** | 실제 SDK 요청을 로컬 서버로 캡처 |
| `fallbacks` | 없음 | 같은 캡처 |
| 요청 본문 키 | `max_tokens`, `messages`, `model`, `system`, `thinking` | 같은 캡처 |
| API 버전 | `2026-10-21` | SDK 2.3.0 상수와 캡처 일치 |
| 호환성 | 이 버전은 위 세 샘플링 값을 거부한다. 요청에 없으므로 문제없다. | API 참조 자료 |
| adaptive thinking | 지원. 기본 effort는 `high`로, 요청에 명시하지 않고 기본값 사용 | 공식 문서, 캡처 |
| SDK | `anthropic` 2.3.0, Python 3.11.2 | 설치본 |
| 재시도 | 기본 2회, 연결 5초, 읽기 600초 | SDK 상수 |
| 비스트리밍 16000 | SDK가 요청을 거부하지 않음 | 로컬 호출 성공 |
| 인증 | 키는 `ANTHROPIC_API_KEY` 또는 저장소 `.env`, `eval/.env`에서 읽음. 쉘 값이 우선. 키를 넘기면 SDK가 `authorization` 헤더를 보냄 | 코드, 헤더 이름 캡처 |
| 다른 자격 증명 | 자동 발견 자격 증명 없음. 현재 키도 없음 | SDK 확인 |
| **실제 인증과 모델 접근** | **미확인** | 키 없음, 유료 호출 미승인 |

**비밀정보 점검:** 실험 폴더에 키 패턴이 없다. `.env`는 저장소 규칙으로 무시되고, 현재 파일은 없다. 키 값은 출력하지 않았다.

---

## 7. Windows PowerShell 실행 절차

실제 CLI의 `--help`로 옵션을 확인하였다. 저장소 최상위에서 실행한다. **5, 6, 9번은 유료이므로 승인 후에만 실행한다.** 표기: [실행함]은 이번에 PowerShell에서 동작을 확인한 명령이다.

### 7.1 가상환경 경로 [실행함]

```powershell
$py = Resolve-Path "..\.venv-question-ablation\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
& $py --version
$R = "experiments\question_ablation\run_pilot.py"
```

### 7.2 사전 주석 파일 검증 (잠그지 않음)

`S00x_final.csv`를 저장한 뒤 실행한다. 빈 목록 `[]`이 나와야 한다. 전용 CLI가 없어 기존 함수를 직접 호출한다.

```powershell
& $py -c "import sys; sys.path.insert(0,'experiments/question_ablation'); import run_pilot as r; b=r.ANNOTATION_RECORD.parent; [print(p, r.check_annotation_population(p, r.sc.read_csv(b/(p+'_final.csv')))) for p in r.PATIENTS]"
```

### 7.3 사전 주석 잠금 (무료, 1회)

```powershell
& $py $R lock-annotation experiments\question_ablation\evaluation\preannotation\annotation_record_draft.json
```

### 7.4 실행 전 점검 (무료) [실행함]

```powershell
& $py experiments\question_ablation\build_prompts.py --check
& $py experiments\question_ablation\evaluation\tests\test_scoring.py
& $py experiments\question_ablation\tests\test_run_pilot.py
& $py $R check
& $py $R estimate
```

### 7.5 소규모 실제 API 호출 (유료)

**실행 가능한 명령이 없다.** Phase 6A의 `smoke`는 제안 상태이다. 대신 `questions`를 쓰면 30회가 호출된다.

### 7.6 전체 질문 생성 (유료, 승인 후)

```powershell
& $py $R questions --experiment pilot1 --paid pilot1
```

### 7.7 블라인드 평가 패킷 생성 (무료)

시드는 관리자만 보관한다.

```powershell
$W = "data\processed\question_ablation\pilot1"
$seed = Get-Random -Maximum 2147483647
& $py $R packet --workspace $W --seed $seed
```

### 7.8 평가 결과 잠금 (무료)

`<평가자1 폴더>`에는 30세트 전체의 `question_sheet.csv`, `link_sheet.csv`가 있어야 한다.

```powershell
& $py experiments\question_ablation\evaluation\scoring.py validate <question_sheet.csv> <link_sheet.csv>
& $py $R compare-raters <평가자1 폴더> <평가자2 폴더> --out "$W\scores"
& $py $R merge --workspace $W --primary <평가자1 폴더> --adjudication "$W\scores\adjudication.csv"
& $py $R lock-scores --workspace $W
```

### 7.9 후속 판정 (유료, 승인 후)

```powershell
& $py $R downstream --experiment pilot1 --paid pilot1
& $py $R sim-audit --workspace $W
& $py $R report --workspace $W --registry <담당자 기록.csv> --sim-audit "$W\scores\simulator_audit.csv"
```

`sim-audit`와 `report`는 무료이다. 감사표를 평가자가 채운 뒤 `report`를 **한 번** 실행한다.

### 비용 정산 (무료)

```powershell
(Get-ChildItem "$W\attempts" -Filter *.json | ForEach-Object { (Get-Content $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json).cost_usd } | Measure-Object -Sum).Sum
```

---

## 8. 팀 결정 사항

| 번호 | 결정 | 담당 | 권장 |
|---|---|---|---|
| 1 | M4a 정의 승인과 민감도 범위 | 팀 | [M4a_team_review.md](M4a_team_review.md) 6절 |
| 2 | P1~P4 배정과 노출 신고 | 팀 | 4절 |
| 3 | 판정기 고정 항목 확인 | 인선 님, 주희 님 | 5절 |
| 4 | "기억나지 않아요" 처리 | 팀 | 파일럿은 현행 고정, 한계로 보고 |
| 5 | API 키 수령과 비용 공지 | 주희 님, 팀 | 저장소 팀 규칙 |
| 6 | `smoke` 구현 승인 | 사용자 | 승인 권장 |
| 7 | 주석 보조 스크립트 승인 | 사용자 | 승인 권장 |
| 8 | Git 백업 시점과 푸시 | 사용자 | 로컬 커밋 먼저, 푸시는 채점 잠금 후 |
| 9 | M1~M7 집계 시점 | 사용자 | 6D 끝 |
| 10 | 해준 님 실행 코드와 중복 여부 | 팀 | 실행 전 확인 |
