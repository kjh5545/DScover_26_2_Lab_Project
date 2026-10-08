# 에이전트 코드

| 파일 | 에이전트 | 상태 | LLM 사용 |
|---|---|---|---|
| `schemas.py` | 에이전트 간 데이터 형식 (공통 약속) | 완료 | - |
| `llm.py` | Claude API 호출 공통 함수 (기본 모델 Sonnet 5.5) | 완료 | - |
| `patient_agent.py` | 1. 환자 정보 이해: 줄글 → `PatientProfile` | 완료 | O |
| `search_agent.py` | 2. 후보 검색: `PatientProfile` → `TrialCandidate` 목록 (ClinicalTrials.gov API, 나이·성별 코드 필터) | 완료 | X |
| (예정) `parse_agent.py` | 3. 기준 파싱: 기준 원문 → `ParsedTrial` (하위 조건, 유형 태그) | 형식만 정함 | O |
| `../eval/rules_prompt_v3.md` | 4. 매칭·판정 프롬프트 (검증 완료) | 코드화 예정 | O |
| (예정) | 5. 질문 생성 · 6. 재평가 · 7. 추천·설명 | - | O |

## 실행
```bash
pip install -r requirements.txt
# API 키: 프로젝트 루트 또는 eval/ 폴더의 .env 에 ANTHROPIC_API_KEY=... (git에 올라가지 않음)
python -m agents.patient_agent                                # 환자 10명 → outputs/patient_profiles.json
python -m agents.search_agent --profiles outputs/patient_profiles.json   # → outputs/trial_candidates.json
python -m agents.search_agent --condition "bladder cancer" --age 68 --sex male   # 검색만 따로
```

## 규칙
- 에이전트끼리는 `schemas.py`의 형식으로만 데이터를 주고받습니다. 필드를 바꿀 때는 서로 알리고 바꿉니다.
- 기준 ID(I1, E1)는 팀원 레이블 시트와 같은 규칙(원문 순서)을 씁니다. 그래야 정답과 비교할 수 있습니다.
- 하드 필터(코드)는 나이·성별처럼 명백한 불일치만 거릅니다. 애매한 건 거르지 않고 매칭 에이전트에 넘깁니다.
