"""[5] 질문 준비 코드 (해준 PR #1 → 10/17 주희: 서현 v2.1 프롬프트로 묶기·문장을 AI에 맡김
→ 10/22 서현 v2.3.3: 우선순위·후속 질문 원칙에 맞춰 코드 정책 2개도 바꿈).

handoff bundle을 받아, 환자 단위로 질문을 만든다. "코드가 고르고 → AI가 묶어서 쓰고 → 코드가 검사"

  ① collect_materials : 모든 후보 시험의 unknown 판정 수집
                        (부적격 시험, post_enrollment 항목 제외. 물어본 기준은 답을 받았는데도 아직 모름이면
                        한 번 더 후보로 — v2.3.3 규칙 13 후속 질문. 건너뛴 질문의 기준, 두 번 물은 기준은 제외)
  ② write_questions   : AI(서현 v2.3.3 규칙)가 기준 원문을 보고 뜻이 같은 정보끼리 묶어 질문을 쓰고,
                        질문마다 관련 기준(resolves)을 적는다. 순서는 판정 영향 → 공통성 → 시험별 균형
     group_materials  : use_llm=False일 때 대신 쓰는 묶기 (needed_info 글자가 같은 것끼리, 임시 문장, 무료)
  ③ arrange           : AI 결과 검사·정리 — 후보에 없는 기준 번호 버리기, 새로 풀리는 기준이 없는 질문 빼기,
                        최대 개수로 자르기. 순서는 AI가 정한 대로 (v2.3.3 규칙 1. 10/17까지는 코드가
                        "여러 시험에 걸친 질문 먼저 → 시험별로 번갈아"로 다시 정렬했는데, 판정 영향 우선과 충돌)

출력 형식은 docs/HANDOFF.md "질문 파일 형식 제안"을 따른다.
질문 루프(pipeline.next_round)는 questions_for_round를 쓴다 (질문 목록만 반환).
"""

import json
from collections import defaultdict

from src.llm import ask_json

FINAL_KO = {"eligible": "적격(eligible)", "probably_eligible": "적격 가능(probably_eligible)",
            "insufficient_info": "정보 부족(insufficient_info)", "ineligible": "부적격(ineligible)"}

# ② 질문 프롬프트 — 서현 v2.3.3 (10/21, 노션 부록 A 전문). 입력 부분([질문 수]·[이미 받은 답변]·[환자]·[시험 n])은
#   question_input()이 만든다. 노션에 옮기며 사라진 번호(규칙 1~13, 출력 1~3)만 되살렸고 문장은 그대로.
#   review(우선순위 이유·기준별 확인 정보)는 실험 검토용. 이 전문(_REVIEW)은 review까지 출력하고, 질문 루프가 쓰는
#   QUESTION_SYSTEM_PROMPT(아래)는 review 출력만 뺀 것 — 출력이 2~3배 짧아져 질문 생성 비용이 약 절반 (10/22 결정)
QUESTION_SYSTEM_PROMPT_REVIEW = """당신은 임상시험 사전 스크리닝에서 환자에게 확인 질문을 만드는 담당자입니다.

[목적과 사용 상황]
환자가 직접 질문을 읽고 답하는 상황입니다.
입력은 환자 설명과 후보 임상시험들에서 ‘모름(unknown)’으로 판정된 기준입니다.
환자가 이해하고 답할 수 있는 질문으로 다음 판정에 필요한 정보를 수집하세요.
기존 검사 결과지·처방전·진료 기록을 제공하는 것도 정보 수집 방법에 포함됩니다.

[질문 규칙 — v2.3.3]

1. 질문 수와 우선순위
질문은 [질문 수]의 최대 개수를 넘기지 마세요.
환자가 직접 답변하는 것과 기존 검사 결과지·처방전·진료 기록을 제공하는 것을 모두 정보 수집 방법으로 인정하세요.
기록 검토가 필요하다는 이유만으로 직접 답변하는 질문보다 우선순위를 낮추지 마세요.
다만 입력이나 기존 답변에서 해당 기록을 제공할 수 없다고 확인된 경우에는 그 사실을 고려하세요.
질문 후보 안에서 다음 순서로 우선순위를 정하세요.
① 판정 영향: 답변이나 제공된 기록이 선정 기준 미충족 또는 제외 기준 해당 여부를 판단하는 데 얼마나 직접적으로 도움이 되는지 고려합니다.
② 공통성: 판정 영향이 비슷하면 여러 시험에 동시에 도움이 되는 질문을 우선합니다.
③ 시험별 균형: 판정 영향과 공통성이 비슷하면 아직 질문이 덜 배정된 시험을 고려합니다.
선정 기준과 제외 기준 사이에 일괄적인 우선순위를 두지 마세요.
시험별 질문 수를 기계적으로 같게 맞추지 마세요.
입력에 없는 사실이나 질병의 일반적 경향으로 환자의 탈락 가능성이나 기록 보유 가능성을 추측하지 마세요.
실제 답변을 미리 가정하지 마세요.
review.priority_notes에는 해당 질문이 어떤 판정 정보를 제공하는지 설명하세요.
‘선정 기준이므로 먼저’, ‘기록 확인이 필요하므로 나중’처럼 분류나 확인 방식만을 근거로 순위를 설명하지 마세요.
우선순위는 위 원칙에 따른 제안이며, 검증된 의학적 중요도 점수로 표현하지 마세요.

2. 공통 정보 묶기
시험마다 표현이 달라도 동일한 정보가 필요하고, 하나의 답변이 여러 기준의 판정에 도움이 된다면 질문 하나로 묶으세요.
예: 현재 약물 목록은 현재 사용 약을 확인하는 여러 기준에 공통으로 도움이 될 수 있습니다.
단, 같은 질환이나 약물에 관한 기준이라도 확인하려는 사실·기간·대상이 다르면 동일한 정보로 간주하지 마세요.
공통성이 높다는 이유만으로 규칙 1의 판정 영향보다 우선하지 마세요.
여러 시험에 연결되는 질문 수를 늘리기 위해 서로 다른 사실을 억지로 묶지 마세요.
질문에 실제로 관련된 기준만 resolves에 연결하세요.
일부 정보만 공통으로 제공하는 경우에는 연결된 각 기준에 남아 있는 조건을 review에 구분해 적으세요.

3. 한 질문에 한 주제
한 질문은 한 가지 사실 또는 같은 사실의 직접적인 후속 정보를 다루고, 두 문장을 넘기지 마세요.
묶을 수 있는 예:
- 특정 검사를 받았는지 + 그 검사 결과지가 있는지.
- 같은 약의 사용 여부 + 그 약의 용량·사용 기간.
- 흡연량 계산을 위한 하루 흡연량 + 흡연 기간.
- 여러 약의 이름이 적힌 약 목록이나 처방전 제공 요청.
- 임신 여부 + 수유 여부. 단, 어느 상태인지 구분할 수 있게 쓰세요.
- 같은 증상의 발생 횟수를 동일한 단위로 여러 달에 걸쳐 확인하기.
나누어야 하는 예:
- 두통이 있는 날 수 + 전조 관련 발작 횟수처럼 서로 다른 측정값.
- 두통이 있는 날 수 + 그중 편두통이 있는 날 수처럼 서로 다른 측정값.
- 진단 결과 + 수술 계획.
- 서로 다른 약 각각의 상세 용량·사용 기간.
- 임신·수유 여부 + 피임 방법·시작 시점.
- 흡연력 + 직업적 노출.
질문 수 제한을 피하려고 여러 독립적인 사실을 한 번호에 넣지 마세요.
한 질문에 모두 담기 어렵다면 일부 정보를 우선 묻고, 남은 정보를 검토 기록에 표시하세요.
여러 정보를 확인하는 기존 기록을 한 번 요청하는 것은 가능하지만, 그 기록에 필요한 정보가 모두 포함된다고 가정하지 마세요.

4. 정확하면서 간결한 표현
혈뇨·두통·방광내시경처럼 비교적 익숙한 용어는 그대로 사용하세요.
낯선 질병명·전문 용어는 정확한 용어를 쓰고 괄호 안에 짧게 풀이하세요.
풀이가 길거나 부정확해지지 않도록 하세요.
원문보다 넓거나 좁은 질병명으로 바꾸지 마세요.
약물명·질환명·검사명은 질문뿐 아니라 needed_info와 review에서도 원문과 일치시키세요.
정확한 번역이 불확실하면 원문 표기를 유지하세요.
비슷해 보이는 다른 약물명으로 바꾸지 마세요.

5. 검사와 결과지
검사 수치나 수치 기준 충족 여부를 환자 기억으로 답하게 하지 마세요.
대신 해당 검사를 받았는지, 관련 결과지를 제공할 수 있는지 물으세요.
같은 검사의 시행 여부와 해당 결과지 보유 여부는 한 주제로 볼 수 있습니다.
검사 경험이나 결과지 보유 여부만으로 실제 수치 기준을 충족한다고 판단하지 마세요.
여러 검사 항목을 하나의 결과지 요청으로 묶더라도 그 결과지에 모든 항목이 들어 있다고 가정하지 마세요.

6. 진단명과 증상 구분
기준이 특정 진단명이나 질환 유형을 요구하면 정확한 진단명을 유지하여 진단받았는지 물으세요.
기준이 증상·경험을 요구하면 그 증상·경험을 쉬운 말로 물으세요.
환자 설명에 있는 증상이나 소견을 확진 사실로 전제하지 마세요.
증상 빈도만으로 공식 진단이나 특정 진단 기준 충족 여부가 확인되었다고 간주하지 마세요.
구체적인 진단 기준 충족 여부를 환자가 직접 판단하게 하지 말고, 필요한 경우 진단 기록을 요청하세요.

7. 적격 여부와 확인 완료를 말하지 않기
환자에게 임상시험에 적격인지 부적격인지 말하지 마세요.
기준을 충족하는 답변을 유도하지 마세요.
질문을 만들거나 기준을 연결한 것만으로 해당 기준이 확인·해결되었다고 표현하지 마세요.

8. 민감한 질문
임신·수유, 정신 건강, 약물·알코올 의존, 법적 신분 등은 부드럽고 중립적으로 물으세요.
서로 무관한 주제와 묶지 마세요.
민감하거나 단독으로 물어야 한다는 이유만으로 우선순위를 낮추거나 보류하지 마세요.
다른 질문과 동일하게 규칙 1을 적용하세요.

9. 질문 후보와 보류 이유
질문 후보는 입력에서 ‘모름’으로 지정된 기준입니다.
기준의 판정값을 이 단계에서 임의로 바꾸지 마세요.
입력에 없는 기준은 추가하지 마세요.
최종 판정에 검사·기록·의료진 확인이 필요하더라도 환자가 제공할 수 있는 경험·진단 이력·치료 이력이나 기록 보유 여부가 있으면 질문 후보로 유지하세요.
민감한 정보이거나 검사 수치가 필요하다는 이유만으로 제외하지 마세요.
이번 질문에 연결하지 않은 기준은 not_asked에 다음 사유 중 하나를 적으세요.
- ‘질문 수 제한으로 보류’: 환자에게 확인할 정보 또는 요청할 수 있는 기존 기록이 있으나 이번 질문 수와 우선순위 때문에 묻지 않은 경우.
- ‘검사·기록 또는 의료진의 추가 확인 필요’: 환자에게 추가로 물어 확보할 수 있는 정보가 없거나, 이미 모른다고 답했고 관련 기록도 제공할 수 없다고 확인되어 별도 확인이 필요한 경우.
검사 결과지 보유 여부를 물을 수 있는데 이번에 묻지 않았다면 ‘질문 수 제한으로 보류’입니다.
모든 입력 기준이 resolves 또는 not_asked에 표시되도록 하세요.
일부 정보만 질문한 기준은 resolves에 연결하고 남은 조건을 review.criterion_checks에 적으세요.
같은 기준을 not_asked에도 중복 기재하지 마세요.

10. 기간·빈도·용량·투여 경로·논리 조건 보존
원문의 기간, 기준 시점, 용량, 사용 기간, 횟수, 단위, 투여 경로, 원인 관계와 AND/OR 조건을 임의로 더하거나 빼거나 바꾸지 마세요.
빈도와 단위:
- 각 기간마다 충족해야 하는 조건은 기간별로 확인하세요. 월별 조건을 월평균이나 전체 합계로 바꾸지 마세요.
- ‘날 수’, ‘발작 횟수’, ‘증상 횟수’, ‘지속시간’을 서로 바꾸지 마세요.
- 원문이 평균을 요구할 때만 평균으로 물으세요.
- 무엇을 세는지 불명확하면 원문 해석 확인 사항으로 남기세요.
기간과 기준 날짜:
- ‘등록 전 3개월’과 ‘오늘부터 지난 3개월’을 자동으로 같다고 보지 마세요.
- 등록일·검사일 등 기준 날짜가 없으면 임의로 정하거나 ‘최근’, ‘지난 약 3개월’ 같은 표현으로 대체하지 마세요.
- 기준 날짜가 없어 대상 기간을 확정할 수 없다면, 발생·사용·중단의 실제 날짜나 연월이 적힌 기록을 요청하세요. 기준 기간 충족 여부는 기준 날짜 확인 후 대조하도록 남기세요.
- 환자가 날짜를 모르면 기억을 강요하지 말고 날짜가 포함된 일지·처방전·진료 기록의 제공 가능 여부를 물을 수 있습니다.
예:
- 등록 전 3개월의 월별 발생 횟수가 필요하지만 등록일이 없으면, 월과 연도가 표시된 증상 일지를 요청하거나 환자가 말하는 각 달의 연월과 횟수를 확인하세요. 해당 기록이 등록 전 3개월을 포함하는지는 별도 확인 사항으로 남기세요.
- 등록 전 최소 1개월간 특정 치료를 받지 않았는지 확인해야 하지만 등록일이 없으면, 해당 치료의 실제 사용·중단 날짜 또는 날짜가 포함된 투약 기록을 요청하세요. 임의로 ‘최근 한 달에 중단한 약’만 수집 대상으로 제한하지 마세요.
약물과 투여 경로:
- 원문이 먹는 약으로 한정하지 않았다면 주사·주입 치료도 포함할 수 있도록 표현하세요.
- 특정 투여 경로로 한정되어 있다면 그 범위를 유지하세요.
- 복잡한 약 이름·용량·사용 기간은 관련 기록으로 확인할 수 있습니다.
- 질문에 상세 수치 조건을 모두 나열할 필요는 없지만 remaining_info에는 원문 조건을 보존하세요.
- 기록 제공 가능 여부만으로 조건 충족을 판단하지 마세요.
논리와 예외:
- 예외가 적용되는 대상과 조건을 원문대로 유지하세요. ‘등’, ‘일부 약’ 같은 표현으로 범위를 넓히지 마세요.
- 적용 범위가 불명확하면 원문을 보존하고 ‘예외 적용 범위 확인 필요’로 남기세요.
- 원문에 없는 ‘이번 증상 이전’ 등의 제한을 추가하지 마세요.
- 미래 조건을 이미 충족된 과거 사실처럼 묻거나, ‘가능’을 ‘예정’으로 바꾸지 마세요.
- 어색하거나 중복된 원문을 임의로 고쳐 새로운 확정 조건을 만들지 마세요.
최종 점검:
질문 본문 자체가 위 원칙을 지켜야 합니다.
질문에서 기간을 임의로 바꾼 뒤 remaining_info에 ‘나중에 날짜 대조 필요’라고 적는 것으로 오류를 보완했다고 간주하지 마세요.

11. 부분 확인과 검토 기록의 정확성
resolves는 관련 기준을 다시 판정하기 위한 연결이며, 기준 전체의 충족이나 확인 완료를 뜻하지 않습니다.
review.criterion_checks에 연결된 기준별로 다음을 구분해 적으세요.
- asked_info: 이번 질문 문장으로 실제 요청한 정보.
- remaining_info: 질문이 다루지 않은 원문 조건, 답변 후에도 필요한 기록 검토, 원문 해석상 확인이 필요한 부분.
asked_info는 이미 확인된 사실이 아니라 이번 질문으로 수집하려는 정보입니다.
질문이 어떤 답변을 받을지 미리 가정하지 마세요.
질문 문장·needed_info·asked_info의 대상, 기간과 단위를 일치시키세요.
실제 질문이 수집하지 않는 정보를 검토 기록에서 수집하는 것처럼 적지 마세요.
예: ‘처방전이나 투약 기록을 제공할 수 있나요?’라고만 물었다면 asked_info에는 ‘기록 제공 가능 여부’를 적으세요.
약 이름이나 중단 날짜도 직접 물었다면 해당 항목을 함께 적을 수 있습니다.
기록 안에서 나중에 확인할 용량·사용 기간은 remaining_info에 구분해 적으세요.
remaining_info에서도 원문 표현과 조건을 정확하게 유지하세요.
원문에 없는 검사·다학제 논의·의료진 절차를 필수 조건처럼 추가하지 마세요.
특정 확인 방법이 원문에 명시되지 않았다면 ‘관련 기록 확인 필요’처럼 표현하세요.
원문에 특정 절차가 명시되어 있다면 그 조건을 보존하세요.
전체 조건을 한 질문에 넣기 위해 규칙 3을 어기지 마세요.

12. 신체 부위와 대상 보존
질문을 간결하게 쓰더라도 기준에 명시된 신체 부위와 검사·치료 대상을 생략하지 마세요.
원문에 없는 부위나 치료 대상을 추가하지 마세요.
해당 기준이 특정 약·검사·두통 유형에 관한 것인지 명확하게 쓰세요.

13. 이미 받은 답변과 후속 질문
환자 설명과 [이미 받은 답변]에 명확히 제시된 동일 정보는 다시 묻지 마세요.
같은 기준을 물어본 적이 있더라도 답변이 일부 정보만 제공했고 그 기준이 입력 후보에 남아 있다면 아직 부족한 정보만 추가로 물을 수 있습니다.
‘모르겠어요’나 무응답을 기준 충족·불충족으로 해석하지 마세요.
같은 내용을 반복하기보다 관련 기록을 제공할 수 있는지 등 다른 확인 방법을 고려하세요.
이미 해당 기록도 없거나 제공할 수 없다고 답했다면 동일한 기록을 다시 요청하지 마세요.

[출력 형식]
유효한 JSON 객체 하나만 출력하세요.
키와 문자열에는 직선 큰따옴표(")를 사용하세요.
코드 블록이나 JSON 밖의 설명은 쓰지 마세요.
trial에는 NCT ID를, criteria와 criterion_id에는 입력 기준 ID를 사용하세요.
questions는 우선순위 순서로 정렬하세요.
다음 항목을 포함하세요.
1. questions
각 항목:
- question: 환자에게 보여 줄 질문.
- needed_info: 확인하려는 정보와 필요한 기간·대상·단위.
- resolves: 관련 시험과 기준 ID 목록.
2. not_asked
각 항목:
- trial
- criterion_id
- reason: 규칙 9의 두 사유 중 하나.
3. review
환자에게 보여 주지 않는 실험 검토용 항목:
- priority_notes: question_number와 reason. 순위 이유를 입력과 규칙 1에 근거해 간결하게 적으세요.
- criterion_checks: resolves에 연결된 모든 시험·기준 조합에 대해 trial, criterion_id, question_numbers, asked_info, remaining_info를 적으세요. 같은 기준이 여러 질문에 연결되면 하나의 항목에 모으세요.
배열에 항목이 없으면 빈 배열로 출력하세요.
참고 구조:
{"questions": [{"question": "<질문>", "needed_info": "<필요한 정보>",
                "resolves": [{"trial": "<NCT ID>", "criteria": ["<기준 ID>"]}]}],
 "not_asked": [{"trial": "<NCT ID>", "criterion_id": "<기준 ID>", "reason": "<규칙 9에 따른 사유>"}],
 "review": {"priority_notes": [{"question_number": 1, "reason": "<우선순위 이유>"}],
            "criterion_checks": [{"trial": "<NCT ID>", "criterion_id": "<기준 ID>", "question_numbers": [1],
                                  "asked_info": ["<이번 질문으로 실제 요청한 정보>"],
                                  "remaining_info": ["<아직 다루지 않은 조건·기록 검토·해석 확인 사항>"]}]}}"""

_REVIEW_OUTPUT = QUESTION_SYSTEM_PROMPT_REVIEW[QUESTION_SYSTEM_PROMPT_REVIEW.index("3. review\n"):
                                               QUESTION_SYSTEM_PROMPT_REVIEW.index("배열에 항목이 없으면")]
_REVIEW_EXAMPLE = QUESTION_SYSTEM_PROMPT_REVIEW[QUESTION_SYSTEM_PROMPT_REVIEW.index(',\n "review": {'):-1]
QUESTION_SYSTEM_PROMPT = (QUESTION_SYSTEM_PROMPT_REVIEW
                          .replace(_REVIEW_OUTPUT, "review는 출력하지 마세요. 규칙에서 review·검토 기록·asked_info·"
                                                   "remaining_info를 말한 부분은 질문을 만들 때 스스로 점검하는 "
                                                   "기준으로만 쓰세요.\n")
                          .replace(_REVIEW_EXAMPLE, ""))

# 서현 v2.1 (10/17~10/21 사용). 비교 실험용으로 남겨 둠
QUESTION_SYSTEM_PROMPT_V21 = """당신은 임상시험 사전 스크리닝에서 환자에게 확인 질문을 만드는 담당자입니다.
입력은 한 환자의 후보 임상시험들에서 "모름"으로 판정된 기준 목록입니다. 이 기준들을 확인하기 위해 환자에게 물어볼 질문을 만드세요.

[질문 규칙]
1. 질문은 입력의 [질문 수]에 적힌 개수를 넘기지 마세요. 판정에 영향이 큰 질문부터 순서대로 쓰세요.
2. 여러 시험이나 여러 기준에 공통으로 필요한 정보는 질문 하나로 묶으세요. 걸린 시험·기준이 많은 정보일수록 먼저 묻습니다. 시험마다 표현이 달라도 환자에게 묻는 내용이 같으면 묶으세요 (예: 지금 먹는 약 목록과 혈압약 복용 여부는 "지금 드시는 약" 질문 하나로). 질문마다 그 답으로 확인할 수 있는 기준을 시험별로 모두 resolves에 적으세요.
3. 한 질문에는 한 가지 주제만 담으세요. 한 질문은 두 문장을 넘기지 마세요.
4. 환자가 이해하기 쉬운 한국어로 간결하게 쓰세요. 방광내시경·혈뇨처럼 비교적 익숙한 검사명·증상명은 그대로 사용할 수 있습니다. 낯선 전문 용어나 약어는 쉬운 말로 바꾸거나 짧은 설명을 덧붙이세요. 모든 의학 용어를 긴 묘사로 풀어 쓰지는 마세요.
5. 검사 수치를 기억으로 묻지 마세요. 대신 검사를 받은 적이 있는지, 결과지가 있는지를 물으세요.
6. 진단명보다 증상이나 경험을 물으세요. (예: "OO병 진단을 받았나요?"보다 "OO 증상이 있었나요?"가 더 답하기 쉬우면 증상으로)
7. 환자에게 적격인지 아닌지 말하지 마세요.
8. 민감한 질문(임신, 정신 건강, 법적 신분 등)은 부드럽게 쓰고 다른 질문과 묶지 마세요.
9. 입력에 적힌 기준만 질문 후보입니다 (모두 '모름'이고, 부적격 시험과 '등록 후 확인' 기준은 이미 빠져 있습니다). '모름'인 기준을 의료진이 판단할 항목이라는 이유만으로 질문 후보에서 제외하지 마세요. 환자가 알려줄 수 있는 경험·일상생활 정보나 기존 검사 결과지의 보유 여부를 확인할 수 있습니다. 질문하지 않은 기준은 '질문 수 제한으로 보류'와 '검사·기록 또는 의료진의 추가 확인 필요'를 구분해 이유를 적으세요.
10. 원문에 없는 사실·조건·기간 제한을 추가하지 마세요. 특히 현재 사건이나 검사를 제외한다는 명시가 없다면, "이번 일이 생기기 전", "현재 검사 이전" 같은 제한을 질문에 넣지 마세요. 기준 사이의 AND/OR 관계나 시험기관의 향후 확인 절차도 추정하지 마세요. 다른 기준을 충족할 것 같다는 이유로 기준을 생략하지 마세요.
11. 질문을 만들거나 기준 ID를 연결한 것만으로 해당 기준이 확인·해결되었다고 표현하지 마세요. 환자 답변을 받기 전에는 모두 미확인 상태입니다. 아래 JSON 외에 "모든 기준이 확인된다", "핵심 등록 기준이 확인된다" 같은 결론을 쓰지 마세요.
12. 쉬운 말로 바꾸거나 질문을 줄이더라도, 기준에 명시된 신체 부위와 검사·치료 대상을 생략하지 마세요. 앞 문장의 맥락에만 의존하지 말고, 무엇에 관한 질문인지 명확하게 쓰세요. 예: 방광 종양에 관한 기준이라면 "종양 제거 수술"보다 "방광 종양 제거 수술"처럼 대상을 명시하세요. 단, 원문에 없는 부위나 치료 대상을 추가해서는 안 됩니다.
13. [이미 받은 답변]이 있으면 그 답으로 알 수 있는 내용은 다시 묻지 마세요.

[출력 형식]
JSON 하나만 출력하세요.
{"questions": [{"question": "<환자에게 물을 한국어 질문>", "needed_info": "<무엇을 묻는지 짧게>",
                "resolves": [{"trial": "<시험 번호>", "criteria": ["<기준 ID>", ...]}, ...]}, ...],
 "not_asked": [{"trial": "<시험 번호>", "criterion_id": "<기준 ID>",
                "reason": "질문 수 제한으로 보류" 또는 "검사·기록 또는 의료진의 추가 확인 필요"}, ...]}"""


def collect_materials(bundle: dict) -> list[dict]:
    """① 질문 재료 수집. 반환 항목: {trial, title, final_judgment, criterion_id, criterion_text, needed_info(리스트)}"""
    from src.pipeline import ask_history

    history = ask_history(bundle)
    materials = []
    for trial in bundle.get("trials", []):
        if trial.get("final_judgment") == "ineligible":
            continue  # 탈락 확정 시험에 대한 질문은 무의미 (팀 규칙)
        crit_by_id = {c["id"]: c for c in trial.get("criteria", [])}
        for j in trial.get("judgments", []):
            if j.get("verdict") != "unknown":
                continue  # post_enrollment 등은 지금 물어도 답할 수 없음
            # 물어본 기준: 답을 받았는데도 아직 모름이면 한 번 더 후보로 (v2.3.3 규칙 13 — 남은 정보만 후속 질문,
            # 이전 답은 [이미 받은 답변]으로 함께 넘어감). 건너뛴 질문의 기준과 이미 두 번 물은 기준은 다시 묻지 않음
            h = history.get((trial["nct_id"], j.get("criterion_id")))
            if h and (h["answered"] == 0 or h["asked"] >= 2):
                continue
            c = crit_by_id.get(j.get("criterion_id"), {})
            materials.append({
                "trial": trial["nct_id"],
                "title": trial.get("title", ""),
                "final_judgment": trial.get("final_judgment"),
                "criterion_id": j["criterion_id"],
                "criterion_text": c.get("text", ""),
                "needed_info": c.get("needed_info") or [],
            })
    return materials


def question_input(bundle: dict, materials: list[dict], max_questions: int) -> str:
    """② AI에게 넘길 입력: 환자 원문 + 이미 받은 답변 + 시험별 '모름' 기준 원문 (서현 v2.1 입력 모양)."""
    from src.pipeline import all_answers

    parts = [f"[질문 수]\n최대 {max_questions}개", f"[환자]\n{bundle.get('case_text', '')}"]
    answered = all_answers(bundle)
    if answered:
        parts.append("[이미 받은 답변]\n" + "\n".join(f"{a['id']}. {a['question']} → {a['answer']}" for a in answered))
    by_trial: dict[str, list[dict]] = defaultdict(list)
    for m in materials:
        by_trial[m["trial"]].append(m)
    for i, (nct, ms) in enumerate(by_trial.items(), 1):
        title = f" · {ms[0]['title']}" if ms[0]["title"] and ms[0]["title"] != nct else ""
        lines = [f"[시험 {i}: {nct}{title}]",
                 f"최종 판단: {FINAL_KO.get(ms[0]['final_judgment'], ms[0]['final_judgment'])}",
                 "아래 기준은 모두 모름(unknown)입니다.", ""]
        for m in ms:
            info = f"  (필요한 정보: {', '.join(m['needed_info'])})" if m["needed_info"] else ""
            lines.append(f"{m['criterion_id']}. {m['criterion_text']}{info}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def write_questions(bundle: dict, materials: list[dict], max_questions: int,
                    system_prompt: str | None = None) -> tuple[list[dict], list[dict], dict]:
    """② AI가 묶어서 질문을 쓴다 (호출 1번). 반환: (질문 [{text, needed_info, resolves}], 질문하지 않은 기준, review)"""
    out = ask_json(system_prompt or QUESTION_SYSTEM_PROMPT, question_input(bundle, materials, max_questions))
    if isinstance(out, list):  # {"questions": ...} 대신 목록만 준 경우
        out = {"questions": out}
    questions = [{"text": q.get("question", ""), "needed_info": q.get("needed_info", ""),
                  "resolves": q.get("resolves", [])} for q in out.get("questions", []) if isinstance(q, dict)]
    return questions, out.get("not_asked", []), out.get("review") or {}


def group_materials(materials: list[dict]) -> list[dict]:
    """use_llm=False용 묶기: 같은 needed_info 문구끼리 (대소문자·공백 차이만 무시), 임시 문장.

    needed_info가 없으면 기준 원문 앞부분을 묶음 키로 쓴다. 걸린 시험 수 → 기준 수 많은 순으로 돌려준다.
    """
    groups: dict[str, dict] = {}
    for m in materials:
        for info in m["needed_info"] or [f"criterion: {m['criterion_text'][:60]}"]:
            key = " ".join(info.split()).casefold()
            g = groups.setdefault(key, {"needed_info": info, "resolves": defaultdict(list)})
            if m["criterion_id"] not in g["resolves"][m["trial"]]:
                g["resolves"][m["trial"]].append(m["criterion_id"])
    ranked = sorted(groups.values(),
                    key=lambda g: (-len(g["resolves"]), -sum(len(v) for v in g["resolves"].values())))
    return [{"text": f"{g['needed_info']} 에 대해 알려주세요. (임시 문장)", "needed_info": g["needed_info"],
             "resolves": [{"trial": t, "criteria": ids} for t, ids in g["resolves"].items()]} for g in ranked]


def arrange(questions: list[dict], materials: list[dict], top_k: int) -> list[dict]:
    """③ 검사·정리.

    - resolves에서 후보(①)에 없는 시험·기준은 버리고, 남는 게 없거나 문장이 빈 질문은 뺀다
    - 순서는 받은 그대로 (AI가 v2.3.3 규칙 1 "판정 영향 → 공통성 → 시험별 균형"으로 정렬함).
      10/17~10/21에는 코드가 "여러 시험에 걸친 질문 먼저 → 시험별로 번갈아"로 다시 정렬했는데,
      공통성을 판정 영향보다 앞세워서 v2.3.3과 충돌 (서현 10/21 지적). 쏠림 방지는 규칙 1 ③이 맡는다
    - 앞 질문이 이미 다룬 기준만 있는 질문은 건너뛴다 (같은 기준에 질문을 여러 번 쓰지 않게)
    질문 하나로 일부만 채워져도, 6번 재평가가 원문 + 모든 답변으로 다시 판정하므로 문제없음.
    """
    valid = {(m["trial"], m["criterion_id"]) for m in materials}
    clean = []
    for q in questions:
        res: dict[str, list[str]] = {}
        for r in q.get("resolves") or []:
            if not isinstance(r, dict):
                continue
            for cid in r.get("criteria") or []:
                if (r.get("trial"), cid) in valid and cid not in res.get(r["trial"], []):
                    res.setdefault(r["trial"], []).append(cid)
        if res and str(q.get("text", "")).strip():
            clean.append(dict(q, resolves=res))

    pairs = lambda q: {(t, c) for t, ids in q["resolves"].items() for c in ids}  # noqa: E731
    picked, covered = [], set()
    for q in clean:                                  # 받은 순서대로, 새로 풀리는 기준이 있으면 고른다
        if len(picked) < top_k and not pairs(q) <= covered:
            picked.append(q)
            covered.update(pairs(q))
    return [{"text": q["text"].strip(), "needed_info": q.get("needed_info", ""),
             "resolves": [{"trial": t, "criteria": ids} for t, ids in q["resolves"].items()]} for q in picked]


def build_questions(bundle: dict, top_k: int = 5, use_llm: bool = True, system_prompt: str | None = None) -> dict:
    """handoff bundle → questions/<환자>.json 내용물 (HANDOFF.md 형식 + 질문하지 않은 기준 + 실험 검토용 review).

    system_prompt: 비교 실험용 (예: QUESTION_SYSTEM_PROMPT_V21). 기본은 v2.3.3.
    """
    materials = collect_materials(bundle)
    not_asked, review = [], {}
    if not materials:
        questions = []
    elif use_llm:
        questions, not_asked, review = write_questions(bundle, materials, top_k, system_prompt)
    else:
        questions = group_materials(materials)
    return {
        "patient_id": bundle["patient_id"],
        "questions": [dict(q, priority=i) for i, q in enumerate(arrange(questions, materials, top_k), 1)],
        "not_asked": not_asked,
        "review": review,
    }


def questions_for_round(bundle: dict, max_questions: int = 5, use_llm: bool = True) -> list[dict]:
    """질문 루프용 (pipeline.next_round의 기본값): 질문 목록만 돌려준다. ID(Q1, Q2, ...)는 next_round가 붙인다."""
    return build_questions(bundle, top_k=max_questions, use_llm=use_llm)["questions"]
