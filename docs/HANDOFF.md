# HANDOFF.md — 에이전트 1~4번 출력 형식 (담당: 해준)

> 에이전트 1~4번 파이프라인의 출력 명세입니다. 질문 생성([5])·추천([6~7]) 담당자는
> `data/handoff/{환자ID}.json` 파일만 읽으면 됩니다.
> 팀 깃허브에서 형식이 확정되면 이 문서와 코드를 그쪽에 맞춥니다 — 바꿀 때 여기부터 수정.
>
> **2026-10-15 변경 예정**: 질문·답변·재평가 기록을 이 파일의 `rounds`에 쌓기로 결정 → `docs/질문루프_정리.md`

## 생성 방법

```bash
python scripts/run_intake.py S005          # 전 단계 (1→2→3→4)
python scripts/run_intake.py S005 --no-screen   # 매칭 생략 (1→2→3)
```

코드에서: `from src.pipeline import run_intake` → `bundle = run_intake(case_text, patient_id="S005")`

## 파일 형식 (data/handoff/{환자ID}.json)

```jsonc
{
  "patient_id": "S005",
  "case_text": "A 34-year-old woman presents with ...",   // 입력 원문

  // [1] 환자 정보 이해 에이전트 출력 — 케이스에 없는 정보는 null / []
  "profile": {
    "age": 34, "age_unit": "years", "sex": "F",
    "suspected_diagnosis": "Migraine with aura",     // 추정 진단 (확정 아님!)
    "findings": ["..."], "history": ["..."], "medications": ["..."], "labs": ["..."]
  },

  // [2] 후보 검색 에이전트 메타 (나이·성별 하드 필터는 코드로 수행)
  "search": {
    "queries": ["migraine with aura", "migraine"],   // LLM이 정한 검색어
    "rationale": "...",
    "total_found": 18,
    "after_hard_filter": 14
  },

  // 후보 시험 목록 (max_candidates 개)
  "trials": [
    {
      "nct_id": "NCT07022496",
      "title": "...",
      "eligibility_criteria": "...",                 // ClinicalTrials.gov 원문
      "minimum_age": "18 Years", "maximum_age": null, "sex": "ALL",

      // [3] 기준 파싱 에이전트 출력 — 원자 조건 목록
      "criteria": [
        {
          "id": "I1",                    // I=선정, E=제외
          "type": "inclusion",           // inclusion | exclusion
          "category": "medical",         // medical | temporal_numeric | administrative | post_enrollment
          "text": "...",                 // 조건 원문
          "sub_conditions": ["..."],     // 복합 조건을 쪼갠 하위 조건
          "needed_info": ["age", "..."]  // 판정에 필요한 환자 정보 → 질문 생성 재료
        }
      ],

      // [4] 매칭·추론 에이전트 출력 (--no-screen 이면 없음)
      "judgments": [
        {
          "criterion_id": "I1",
          "verdict": "pass",             // pass(통과) | fail(탈락) | unknown(모름) | post_enrollment(등록 후 확인)
          "evidence": "...",             // 프로필 인용 근거
          "sub_condition_notes": ["..."]
        }
      ],
      "final_judgment": "insufficient_info"
      // eligible(적격) | probably_eligible(적격 가능) | insufficient_info(정보 부족) | ineligible(부적격)
      // 코드 규칙: fail 있으면 ineligible → unknown 있으면 insufficient_info
      //           → post_enrollment만 남으면 probably_eligible → 전부 pass면 eligible
    }
  ],

  "meta": { "model": "claude-sonnet-5-5", "prompt_version": "v2", "created": "2026-10-09", "stages": "1-4" }
}
```

## 다음 단계 담당자가 쓰는 방법

- **질문 생성([5]) 담당**: `trials[i].judgments`에서 `verdict == "unknown"`인 항목과
  해당 `criteria`의 `needed_info`를 사용. `final_judgment == "ineligible"`인 시험은
  질문 생성 금지 (회의 결정·골드셋 `expect_no_questions` 검증 완료)
- **추천([6~7]) 담당**: `trials[*].final_judgment`와 `judgments`의 verdict 분포 사용.
  참고 구현: `src/agents/recommender.py` (순위는 코드 규칙, 설명만 LLM)

## 판정 규칙 버전

- `meta.prompt_version = "v2"`: 2026-10-08 회의 결정 반영 — 동의서·참여 의사·열린 기준은
  `post_enrollment`, 명시되지 않은 사실은 추론으로 확정하지 않음(`unknown` 유지).
  goldset_v1 기준 일치 90.2%, 최종 판단 15/15. (※ 이 수치는 claude-opus-5로 측정. 2026-10-12 기본 모델을 claude-sonnet-5-5로 바꿨으니 다시 측정 필요)

## 판정 값 대응표 (파일의 영어 값 ↔ 평가셋·시트의 한국어)

| 파일의 `verdict` | 한국어 | 뜻 |
|---|---|---|
| `pass` | 통과 | 이 기준 때문에 탈락하지 않음이 확인됨 |
| `fail` | 탈락 | 이 기준 때문에 탈락함이 확인됨 |
| `unknown` | 모름 | 지금 환자에게 물어보면 알 수 있는 정보가 없음 → 질문 대상 |
| `post_enrollment` | 등록 후 확인 | 시험에 지원해야 생기는 정보 (동의서, 연구자 판단, 스크리닝 측정) |

| 파일의 `final_judgment` | 한국어 |
|---|---|
| `eligible` | 적격 |
| `probably_eligible` | 적격 가능 (등록 후 확인 필요) |
| `insufficient_info` | 정보 부족 |
| `ineligible` | 부적격 |

## 질문 파일 형식 제안 (questions/<환자ID>.json — 5번 단계 출력)

handoff 파일을 받아 질문 재료 수집(코드) → 같은 정보 묶기(코드) → 질문 문장 생성(LLM, 서현 프롬프트) 순서로 만들 예정:

```jsonc
{
  "patient_id": "S004",
  "questions": [
    {
      "text": "최근 신장 기능 검사(크레아티닌) 결과를 받은 적 있나요?",
      "needed_info": "renal function",
      "resolves": [{"trial": "NCT04369560", "criteria": ["I5"]}],  // 6번 재평가가 이걸 보고 관련 기준만 다시 판정
      "priority": 1          // 걸린 시험 수 많은 순 → 같으면 걸린 기준 수 많은 순
    }
  ]
}
```

규칙: `final_judgment == "ineligible"`(부적격) 시험과 `post_enrollment` 항목은 질문 재료에서 제외.
