"""Claude API 호출 공통 부분. 모든 에이전트가 이 함수를 통해 LLM을 부른다."""

import os
from pathlib import Path
from typing import TypeVar

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
# 키는 eval/.env 또는 프로젝트 루트 .env에 둔다 (둘 다 git 제외)
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "eval" / ".env")

MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-5-5")  # 회의 결정: 판정 모델 Sonnet 5.5
T = TypeVar("T", bound=BaseModel)

_client = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def structured(output_type: type[T], system: str, user: str, effort: str = "medium", model: str = MODEL) -> tuple[T, dict]:
    """지정한 Pydantic 형식으로 답을 받는다. (결과, 토큰 사용량) 반환."""
    resp = client().messages.parse(
        model=model,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=output_type,
        output_config={"effort": effort},
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"모델이 응답을 거절함: {resp.stop_details}")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("출력 한도에 걸려 응답이 잘림")
    usage = {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}
    return resp.parsed_output, usage
