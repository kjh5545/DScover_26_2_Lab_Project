"""LLM 호출 공통 모듈.

모든 에이전트가 이 모듈을 통해 Claude API를 호출한다.
모델을 바꾸고 싶으면 MODEL 상수만 수정하면 된다.

사용 전 API 키 설정 필요:
    export ANTHROPIC_API_KEY="sk-ant-..."
또는 프로젝트 루트의 .env 파일에 넣어도 된다 (자동 로드).
"""

import json
import os
import re
from pathlib import Path

import anthropic

# 기본 모델: 회의 결정(2026-10-09)으로 판정 모델은 Sonnet 5.5. Opus 5보다 약 2.5배 저렴 (입력 $2 / 출력 $10, 100만 토큰당).
# 공용 키라 모델을 바꿀 때는 비용 영향을 팀에 먼저 공유할 것.
MODEL = "claude-sonnet-5-5"

_client: anthropic.Anthropic | None = None


def _load_dotenv() -> None:
    """프로젝트 루트의 .env 파일에서 환경변수를 읽는다 (이미 설정돼 있으면 건너뜀)."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _load_dotenv()
        _client = anthropic.Anthropic()
    return _client


def ask(system: str, user: str, max_tokens: int = 16000) -> str:
    """시스템 프롬프트 + 사용자 메시지로 Claude를 호출해 텍스트 응답을 반환한다."""
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return next((b.text for b in response.content if b.type == "text"), "")


def ask_json(system: str, user: str, max_tokens: int = 16000):
    """JSON 응답을 기대하는 호출. 응답에서 JSON을 추출해 파싱한 값을 반환한다."""
    text = ask(system, user, max_tokens=max_tokens)
    # 모델이 ```json ... ``` 코드블록으로 감싸는 경우 대비
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text)
