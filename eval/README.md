# 스크리닝 프롬프트 자동 평가

사전 실험(시험 A–D, 재평가 세트 1·2)을 Claude API로 반복 실행하고 정답과 비교합니다.

## 준비
1. `pip install -r requirements.txt`
2. `.env.example`을 복사해 `.env`로 이름을 바꾸고 API 키를 넣습니다. (`.env`는 git에 올라가지 않습니다)

## 실행
```bash
python run_eval.py --smoke                                   # 연결 확인 (케이스 1개, 1회)
python run_eval.py --models claude-opus-4-8 --repeats 3      # 웹 실험 재현 + 흔들림 측정
python run_eval.py --models claude-opus-4-8 claude-opus-5-5 claude-sonnet-5-5 claude-haiku-4-5 --repeats 3
python run_eval.py --goldset --rules rules_prompt_v3.md --models claude-sonnet-5-5 --repeats 3   # 팀원 레이블 평가 세트
```
결과는 `runs/<날짜_시간>/`에 `report.md`(요약), `results.csv`(기준별 판정), `raw/`(모델 원본 출력)로 저장됩니다.

## 파일
- `rules_prompt.md`: 판정·질문 규칙 (웹 실험의 프롬프트 2와 동일, 출력 형식만 JSON으로 바꿈)
- `cases.json`: 사전 실험 케이스 6개 (환자 S005, 정답은 본인 수작업과 Claude 예상)
- `../goldset/goldset_v1.json`: 팀원 레이블 평가 세트 15개 (환자 9명). `--goldset`으로 사용. 평가 입력과 원본 기록이 한 파일에 있음
- `run_eval.py`: 실행·채점·리포트

## 웹 실험과 다른 점
- 출력을 표 대신 JSON(구조화된 출력)으로 받습니다. 채점을 자동화하기 위해서입니다.
- 프롬프트 규칙과 시험 기준 문장은 웹 실험과 같습니다.
