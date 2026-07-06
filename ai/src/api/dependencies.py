"""AI 내부 API runtime dependency factory.

endpoint가 주입할 runtime 의존성(OpenAI client·KIS fetcher·Redis cache·trace sink)을 만든다.
FastAPI `Depends`로 연결하며, 테스트는 `app.dependency_overrides`로 fake를 주입해 **네트워크 없이**
검증한다. import 시점에 client를 만들지 않는다(요청 처리 시 lazy 생성).
"""

from __future__ import annotations

from src.agents.technical.nodes._llm_utils import LlmClient
from src.agents.technical.observability.trace_logger import TraceSink
from src.agents.technical.services.cache_service import OhlcvCache, default_cache
from src.agents.technical.services.openai_llm_client import default_openai_client
from src.agents.technical.supervisor.technical_supervisor import OhlcvFetcher
from src.api.errors import ai_unavailable


def get_llm_client() -> LlmClient:
    """OpenAI client(요청당 lazy 생성). config 오류(OPENAI_API_KEY/MODEL 누락)는 502로 변환.

    `default_openai_client()`가 `.env`에서 key/model을 읽고 누락 시 RuntimeError(config error)를 낸다.
    이를 `AI_UNAVAILABLE(502)`로 바꾸되 **원문 메시지는 노출하지 않는다**(`from None`으로 chain 차단)."""
    try:
        return default_openai_client()
    except RuntimeError:
        raise ai_unavailable() from None


def get_fetcher() -> OhlcvFetcher | None:
    """KIS OHLCV fetcher. 기본 None = supervisor 기본 KIS fetcher 사용.

    테스트는 이 의존성을 override해 fake fetcher를 주입한다(실 KIS 호출 방지)."""
    return None


def get_cache() -> OhlcvCache | None:
    """Redis OHLCV 캐시. `REDIS_URL` 미설정/연결 실패면 None(캐시 비활성) — endpoint 실패 아님."""
    return default_cache()


def get_trace_sink() -> TraceSink | None:
    """trace sink. 운영 JSONL 경로 정본이 없으므로 이번 브랜치는 None(=supervisor가 Noop 처리).

    테스트는 InMemoryTraceSink로 override해 이벤트를 검증한다."""
    return None
