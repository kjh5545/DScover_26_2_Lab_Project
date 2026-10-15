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
    """프로젝트 루트의 .env (없으면 eval/.env)에서 환경변수를 읽는다 (이미 설정돼 있으면 건너뜀)."""
    root = Path(__file__).resolve().parent.parent
    for env_path in (root / ".env", root / "eval" / ".env"):
        if not env_path.exists():
            continue
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


def _params(system: str, user: str, max_tokens: int) -> dict:
    """ask()와 배치 실행이 똑같은 요청을 보내도록 요청 내용을 한 곳에서 만든다."""
    return {
        "model": MODEL,
        "max_tokens": max_tokens,
        "thinking": {"type": "adaptive"},
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }


def ask(system: str, user: str, max_tokens: int = 16000) -> str:
    """시스템 프롬프트 + 사용자 메시지로 Claude를 호출해 텍스트 응답을 반환한다."""
    response = get_client().messages.create(**_params(system, user, max_tokens))
    return next((b.text for b in response.content if b.type == "text"), "")


def parse_json(text: str):
    """응답 텍스트에서 JSON을 추출해 파싱한다."""
    # 모델이 ```json ... ``` 코드블록으로 감싸는 경우 대비
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text)


def ask_json(system: str, user: str, max_tokens: int = 16000):
    """JSON 응답을 기대하는 호출. 응답에서 JSON을 추출해 파싱한 값을 반환한다."""
    return parse_json(ask(system, user, max_tokens=max_tokens))


# 배치 할인 단가 (100만 토큰당, 일반 가격의 50%). 모델을 바꾸면 같이 고칠 것.
BATCH_PRICE = {"claude-sonnet-5-5": (1.0, 5.0), "claude-opus-5": (2.5, 12.5)}


def batch_ask_json(requests: dict[str, tuple[str, str]], max_tokens: int = 16000,
                   poll_seconds: int = 30) -> tuple[dict, float]:
    """여러 호출을 Message Batches API로 한 번에 보낸다 (비용 50% 할인, 보통 몇 분~1시간).

    requests: {custom_id: (system, user)}. 평가처럼 기다려도 되는 대량 실행에만 쓴다.
    반환: ({custom_id: 파싱된 JSON 또는 None(실패)}, 실제 비용 달러)
    """
    import time

    client = get_client()
    batch = client.messages.batches.create(requests=[
        {"custom_id": cid, "params": _params(system, user, max_tokens)}
        for cid, (system, user) in requests.items()
    ])
    print(f"  배치 제출: {batch.id} ({len(requests)}건). 결과를 기다리는 중...")
    while batch.processing_status != "ended":
        time.sleep(poll_seconds)
        batch = client.messages.batches.retrieve(batch.id)
        c = batch.request_counts
        print(f"  진행: 처리 중 {c.processing}, 완료 {c.succeeded}, 실패 {c.errored}")

    in_price, out_price = BATCH_PRICE.get(MODEL, (0.0, 0.0))
    results, cost = {}, 0.0
    for r in client.messages.batches.results(batch.id):
        if r.result.type != "succeeded":
            print(f"  [{r.custom_id}] {r.result.type}")
            results[r.custom_id] = None
            continue
        msg = r.result.message
        cost += (msg.usage.input_tokens * in_price + msg.usage.output_tokens * out_price) / 1e6
        text = next((b.text for b in msg.content if b.type == "text"), "")
        try:
            results[r.custom_id] = parse_json(text)
        except json.JSONDecodeError:
            print(f"  [{r.custom_id}] JSON 파싱 실패 (stop_reason={msg.stop_reason})")
            results[r.custom_id] = None
    return results, cost
