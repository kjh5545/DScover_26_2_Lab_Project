> ⚠ **이 문서는 `docs/튜토리얼_해준.md`로 대체됨 (2026-10-09).** 해준이 1~4번 파이프라인을 따로 구현해 둔 것을 반영했어요. 아래는 기록용으로만 남겨 둡니다.

# 해준 작업 안내: 1·2번 검증 + 파이프라인 첫 버전

담당 정리: 주희 = 판정(4·6·7번), 해준 = 연결·화면(1·2번 다듬기, 파이프라인, 데모 구현), 서현 = 5번 질문 프롬프트 설계, 인선 = 상세 환자 레이블·발표 기획

## 목표
환자 설명 하나를 넣으면 **1번 환자 이해 → 2번 시험 검색 → 3번 기준 파싱 → 4번 판정**까지 한 번에 돌아서, 후보 시험별 판정표가 파일로 나오게 만들기.

```
환자 설명 ─▶ 1번 patient_agent ─▶ 2번 search_agent ─▶ (후보 시험마다) 3번 parse_rules ─▶ 4번 match_agent ─▶ outputs/<환자ID>_result.json
```

## 할 일 (순서대로)

### 1. 환경 세팅 (30분, 무료)
```bash
git clone https://github.com/kjh5545/DScover_26_2_Lab_Project.git
cd DScover_26_2_Lab_Project
pip install -r requirements.txt
cp eval/.env.example eval/.env     # 메모장으로 열어 API 키 넣기 (키는 주희에게 따로 받기, 절대 커밋 금지)
git checkout -b feature/pipeline
python -m agents.search_agent --condition "bladder cancer" --age 68 --sex male   # 무료, 돌아가면 OK
```

### 2. 1번 환자 이해 실행·검증 (1–2시간, 약 $0.2)
```bash
python -m agents.patient_agent        # 환자 10명 → outputs/patient_profiles.json
```
- **첫 실제 호출이에요.** `agents/llm.py`의 `structured()`(구조화된 출력)는 아직 실제 API로 돌려본 적이 없어요. 오류가 나면 메시지를 주희에게 공유해 주세요.
- 확인할 것
  - 10명 모두 추정 진단이 그럴듯한가 (참고: 레이블 시트의 추정 질환 = S001 급성 췌장염, S002 그레이브스병, S003 신증후군, S004 방광암, S005 조짐 편두통, S006 털곰팡이증, S007 비후성 유문협착증, S008 특발성 폐섬유증, S009 전염성 단핵구증, S010 망막박리)
  - "⚠ 원문에 없는 인용" 경고가 뜨는가 (뜨면 근거를 지어낸 것 → 프롬프트 수정)
  - S007(생후 3개월)의 `age_years`가 0.25로 나오는가
- 이상하면 `agents/patient_agent.py`의 `SYSTEM` 프롬프트를 고치고 다시 돌려요.

### 3. 2번 검색 검증 (2–3시간, 무료)
```bash
python -m agents.search_agent --profiles outputs/patient_profiles.json
```
- 환자마다 후보 수 확인
- **평가 세트의 시험 15개가 검색 결과에 들어오는지 확인** (`goldset/goldset_v1.json`의 `trial` 필드). 정답 시험을 못 찾으면 판정을 아무리 잘해도 추천을 못 하니, 이게 검색 에이전트의 첫 성적표예요.
  - 못 찾은 시험은 왜 못 찾았는지 (검색어? page_size 50 한도? 진단명이 달라서?) 정리
  - 개선 아이디어: 진단명 여러 개로 검색, page_size 늘리기, 영어 동의어 추가
- 결과를 `agents/notes_search.md` 같은 파일에 짧게 정리해 주세요.

### 4. 파이프라인 첫 버전 `agents/pipeline.py` (1–2일, 환자 1명당 약 $0.3)
만들 것:
```bash
python -m agents.pipeline --patient S004 --max-trials 5
# → outputs/S004_result.json (형식: schemas.PatientResult)
```
흐름:
1. `synthetic-patients.json`에서 환자 설명 읽기
2. `patient_agent.understand(pid, text)` → `PatientProfile`
3. `search_agent.search_for_profile(profile)` → (통과 후보, 하드 필터로 걸러진 후보)
4. 통과 후보 중 앞에서 `--max-trials`개만 (비용 때문. 기본 5)
5. 시험마다
   - `parse_rules.parse_trial(c.nct_id, c.eligibility_text)` → `ParsedTrial`
   - `parse_rules.to_prompt_block(c, parsed)` → 기준 묶음 문자열
   - `match_agent.judge(patient_text, block)` → `TrialJudgment`
   - 한 시험이 실패해도 멈추지 말고 `TrialResult.error`에 이유 남기고 다음 시험으로
6. 토큰 사용량을 합쳐 `PatientResult.usage`에 넣고, 끝날 때 대략 비용 출력 (Sonnet 5.5: 입력 100만 토큰당 $2, 출력 $10)
7. `PatientResult`를 JSON으로 저장 (`result.model_dump()`)

**완성 기준**: S004로 실행하면 결과 파일에 후보 시험 5개의 기준별 판정, 최종 판단, 질문이 들어 있음. 실패한 시험이 있으면 error에 이유가 있음.

## 이미 있는 것 (가져다 쓰기)
| 파일 | 쓰는 함수 |
|---|---|
| `agents/schemas.py` | `PatientProfile`, `TrialCandidate`, `ParsedTrial`, `TrialJudgment`, **`TrialResult`, `PatientResult`(파이프라인 출력 형식)** |
| `agents/patient_agent.py` | `understand(patient_id, text)` |
| `agents/search_agent.py` | `search_for_profile(profile, page_size=50)` |
| `agents/parse_rules.py` | `parse_trial(nct_id, text)`, `to_prompt_block(candidate, parsed)` |
| `agents/match_agent.py` | `judge(patient_text, criteria_block)` (주희 담당, 지금은 v3 프롬프트 임시 버전. 함수 모양은 안 바뀜) |

## 규칙
- **`schemas.py` 형식을 바꿔야 하면 먼저 단톡방에 알리기.** 서현·인선 결과물과 데모 화면도 이 형식을 씀
- **API 비용이 드는 실행은 돌리기 전에 단톡방에 한 줄 알리기** (팀 공용 예산 약 $100)
- `eval/.env`(키), `outputs/` 는 커밋하지 않기 (`.gitignore`에 있음)
- 작업은 `feature/pipeline` 브랜치에서. main에 합치기 전에 주희에게 확인받기

## 다음 단계 (참고)
- 5번 질문 생성(서현 프롬프트) → 6번 재평가(주희) → 7번 추천(주희)이 생기면 파이프라인에 차례로 연결
- 그다음 데모 화면(Streamlit): 인선의 화면 스케치·시연 시나리오를 바탕으로 `PatientResult`를 보여주기
