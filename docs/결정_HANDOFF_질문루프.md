# 결정: 5번 → 6번 연결 형식 (HANDOFF 수정안)

> 작성: 주희 · 2026-10-15 · 상태: **확정 (코드 반영 예정)**
> 대상: `docs/HANDOFF.md`, `src/pipeline.py`, `src/agents/matcher.py`, `app.py`
> 코드에 반영되면 `docs/HANDOFF.md`에 합치고 이 문서는 지웁니다.
>
> **구현 현황 (10/15)**: `src/pipeline.py`에 `next_round()`, `reassess()`, `all_answers()`, `save_bundle()` 완성.
> `match()`·`match_with_rules()`에 `answers` 인자 추가. 판정 출력 검사 완료.
> 해준의 `build_questions()`가 나오기 전까지 `next_round()`는 임시 질문 생성(`questions_per_trial`: 시험별 기존 5번, 묶기 없음)을 씀.
> 점검: `python scripts/check_reassess.py` (무료) · 실제 실행: `python scripts/run_reassess_demo.py` (비용 발생)

## 왜 바꾸나

지금 질문 → 답변 → 재평가 흐름에서 생기는 문제 4가지예요.

| # | 지금 | 문제 |
|---|---|---|
| 1 | 답변을 받으면 `profile_updater`가 **프로필 전체를 AI가 새로 씀** | 기존 정보가 빠지거나 바뀌어도 모름. 판정 근거가 원문인지 답변인지 구분 안 됨 (v3 규칙 1은 "답변을 인용"하라고 함) |
| 2 | 5번이 붙인 `criterion_ids`를 `app.py`가 버리고 질문·답변만 넘김 | 답 하나에 **모든 시험의 모든 기준을 재판정** (시험 3개면 라운드마다 판정 3회). "I1"만으로는 어느 시험 기준인지 모름 |
| 3 | `app.py`, `run_interactive_demo.py`가 파이프라인을 각자 다시 구현 | 평가한 코드와 시연하는 코드가 달라질 수 있음 (v3 넣을 때도 두 곳을 따로 고침) |
| 4 | AI 판정 결과를 검사하지 않음 | AI가 기준을 하나 빠뜨리면, 그게 탈락 기준이어도 최종 판단이 "적격"이 될 수 있음 (안전 오류) |

## 바꾸는 것

### 1. handoff 파일에 `rounds` 추가 (질문·답변·변화 기록)

질문 파일을 따로 두지 않고 **환자 파일 하나에 라운드별로 쌓아요.** 파일이 하나라 어긋날 일이 없어요.

```jsonc
{
  "patient_id": "S004",
  "case_text": "...",
  "profile": { ... },          // 1번 출력. 답변으로 다시 쓰지 않음 (그대로 유지)
  "trials": [ ... ],           // judgments, final_judgment는 항상 "최신" 상태
  "rounds": [                  // 새로 추가. 없으면 질문 전 (기존 파일과 호환)
    {
      "round": 1,
      "questions": [
        {
          "id": "Q1",                          // 라운드를 넘어 고유하게 (R1-Q1 등도 가능)
          "text": "최근에 소변에 피가 섞여 나온 적이 있나요?",
          "needed_info": "hematuria",
          "resolves": [                        // 이 질문의 답으로 다시 판정할 기준 (시험 번호 포함)
            {"trial": "NCT05646485", "criteria": ["E2"]},
            {"trial": "NCT04369560", "criteria": ["E3", "E4"]}
          ],
          "priority": 1                        // 걸린 시험 수 많은 순 → 같으면 기준 수 많은 순
        }
      ],
      "answers": [
        {"question_id": "Q1", "answer": "아니요, 그런 적 없어요"}   // 환자 말 그대로 (요약·번역 안 함)
      ],
      "changed": [                             // 6번이 채움: 이 라운드에서 바뀐 판정
        {"trial": "NCT05646485", "criterion_id": "E2", "from": "unknown", "to": "pass", "source": ["Q1"]}   // 이 기준을 다시 판정하게 한 질문들 (전체 재판정이면 ["full"])
      ]
    }
  ]
}
```

규칙
- `resolves`는 **코드가 채워요** (질문 재료를 모을 때 이미 어느 시험·기준에서 왔는지 앎). 서현 프롬프트(질문 문장 만들기)는 ID를 신경 쓰지 않아도 돼요
- 답이 "모르겠어요"면 그대로 저장. 판정은 모름 유지, 같은 질문은 다시 하지 않음
- 부적격 시험과 `post_enrollment` 기준은 질문 재료에서 제외 (기존 규칙 그대로)

### 2. 판정(4번)에 환자 답변을 직접 넘김

```python
match(profile, criteria, case_text=None, answers=None, system_prompt=None)
# answers: [{"question": "...", "answer": "..."}]  → 프롬프트에 "PATIENT ANSWERS (authoritative)"로 들어감
```
- 판정 근거는 원문 또는 답변을 인용 (`"Q1 답변: '그런 적 없어요'"`)
- `answers`를 안 넣으면 지금과 똑같이 동작 (호환)
- `profile_updater`는 판정에 안 써도 됨. 화면에 "갱신된 프로필"을 보여 주는 용도로만 남길지는 해준 판단

### 3. 재평가 함수 하나로 통일: `reassess()` (6번, 주희)

```python
from src.pipeline import reassess
bundle = reassess(bundle, answers)   # answers: [{"question_id": "Q1", "answer": "..."}]
```
안에서 하는 일
1. 마지막 라운드에 답변 기록
2. 답한 질문의 `resolves`에 있는 기준만 모음 (시험별)
3. 그 기준만 다시 판정 (원문 + 지금까지의 모든 답변) → 나이·임신 코드 판정 → 출력 검사
4. 기존 판정에 합치고 최종 판단 다시 계산
5. `changed` 기록 후 bundle 반환 (저장은 `save=True`일 때)

`app.py`, `run_interactive_demo.py`, 평가 스크립트가 모두 이 함수를 부르면, **평가한 코드 = 시연하는 코드**가 돼요.
1~4번도 `app.py`가 `src/pipeline.py`의 함수(`understand_patient`, `find_candidates`, `parse_trial`, `screen`)를 부르게 맞추면 좋아요.

### 4. 판정 출력 검사 (주희, 무료)

`match_with_rules()` 마지막에 코드로 검사해요.
- AI가 빠뜨린 기준 → `unknown` (근거: "AI 출력 누락 → 안전하게 모름 처리")
- 이상한 판정값 → `unknown`
- 같은 기준이 두 번 → 앞의 것만
- 검사로 바뀐 항목에는 `"checked_by": "validator"` 표시 (코드 판정은 지금처럼 `"code"`)

## 5번 코드가 지켜 줄 것 (해준)

5번은 **파일을 직접 읽고 쓰지 않는 함수**로 만들어 주세요. 저장은 파이프라인이 해요.

```python
def build_questions(bundle: dict, max_questions: int = 5) -> list[dict]:
    """handoff bundle을 받아 이번 라운드에 물을 질문 목록을 반환 (파일 저장 안 함)."""
    return [
        {
            "text": "최근에 소변에 피가 섞여 나온 적이 있나요?",
            "needed_info": "hematuria",
            "resolves": [{"trial": "NCT05646485", "criteria": ["E2"]}],
            "priority": 1,
        },
    ]
```
- `id`는 안 붙여도 돼요. 파이프라인이 `Q1, Q2, ...` 통번호로 붙여요
- 질문 재료에서 빼는 것: 부적격 시험, `post_enrollment` 기준, **이미 물어본 기준** (`bundle["rounds"]`의 `resolves`에 있는 것)
- 개발·실험 중에는 반환값을 아무 파일에나 저장해서 봐도 괜찮아요. 최종 저장 위치만 handoff 파일의 `rounds`예요

## 누가 무엇을

| 할 일 | 담당 | 비고 |
|---|---|---|
| 판정 출력 검사 (4) | 주희 | 형식 변화 없음 |
| `match()`에 `answers` 인자 (2) | 주희 | 안 넣으면 지금처럼 동작 |
| `next_round(bundle)`: `build_questions()` 호출 → ID 붙여 `rounds`에 추가 | 주희 | |
| `reassess(bundle, answers)`: 관련 기준만 재판정 → `changed` 기록 (3) | 주희 | 6번 |
| `build_questions(bundle)`: 질문 재료 모으기·묶기·문장 만들기 | 해준 | 지금 하는 "여러 시험에 걸친 질문 묶기"를 이 모양으로 |
| `app.py`가 파이프라인 함수(`run_intake`, `next_round`, `reassess`)를 쓰게 | 해준 | `reassess()`가 나온 뒤. 주희가 도와도 됨 |
| 질문 문장 프롬프트 | 서현 | 변화 없음. ID는 신경 안 써도 됨 |

## 정한 것

| 항목 | 결정 | 이유 |
|---|---|---|
| 질문 저장 위치 | **handoff 파일 안 `rounds` (한 파일)** | 판정이 바뀌어도 질문과 어긋나지 않음. 파일 하나로 전체 흐름이 보이고 평가·데모가 같은 파일을 읽음 |
| 5번 코드 형태 | **파일을 안 건드리는 함수 (`build_questions`)** | 5번은 판정 파일을 신경 쓰지 않고 개발·실험 가능 (따로 두기의 장점) |
| `profile_updater` | **판정에는 안 씀.** 화면에 "갱신된 프로필"을 보여 줄 때만 사용 (필요 없으면 해준이 빼도 됨) | 판정은 원문 + 답변을 직접 봄 |
| 질문 ID | **`Q1, Q2, ...` 라운드를 넘어 통번호** | 라운드가 바뀌어도 "Q3 답변"처럼 근거를 하나로 가리킬 수 있음 |
