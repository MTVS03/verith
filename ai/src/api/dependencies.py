"""AI 내부 API runtime dependency factory.

endpoint가 주입할 runtime 의존성(OpenAI client·KIS fetcher·Redis cache·trace sink)을 만든다.
FastAPI `Depends`로 연결하며, 테스트는 `app.dependency_overrides`로 fake를 주입해 **네트워크 없이**
검증한다. import 시점에 client를 만들지 않는다(요청 처리 시 lazy 생성).
"""

from __future__ import annotations

from typing import Callable

from src.agents.technical.nodes._llm_utils import LlmClient
from src.agents.technical.observability.trace_logger import TraceSink
from src.agents.technical.runtime.deadline import Deadline
from src.agents.technical.services.cache_service import OhlcvCache, default_cache
from src.agents.technical.services.openai_llm_client import default_openai_client
from src.agents.technical.supervisor.technical_supervisor import OhlcvFetcher
from src.api.errors import ai_unavailable
from src.supervisor.agent_adapters import AgentAdapter, default_adapters
from src.supervisor.resolve_client import ResolverProtocol, StockResolverClient

# endpoint가 deadline을 만든 뒤 client를 생성해야 하므로(요청 timeout을 client에 주입) client를 바로
# 반환하지 않고 **팩토리**를 반환한다. 테스트는 이 팩토리를 override해 fake LLM을 주입한다.
LlmClientFactory = Callable[[Deadline | None], LlmClient]


def get_llm_client() -> LlmClientFactory:
    """`(deadline) -> LlmClient` 팩토리(요청당 lazy 생성). config 오류(OPENAI_API_KEY/MODEL 누락)는 502.

    `default_openai_client(deadline=…)`가 `.env`에서 key/model을 읽고 누락 시 RuntimeError를 낸다.
    이를 `AI_UNAVAILABLE(502)`로 바꾸되 **원문 메시지는 노출하지 않는다**(`from None`으로 chain 차단).
    deadline을 client에 넘겨 per-call timeout을 남은 예산 이하로 줄인다."""
    def make(deadline: Deadline | None = None) -> LlmClient:
        try:
            return default_openai_client(deadline=deadline)
        except RuntimeError:
            raise ai_unavailable() from None
    return make


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


def get_resolver() -> ResolverProtocol:
    """상위 supervisor 종목 정본 경계 client(backend HTTP). import 시점에 네트워크 없음.

    테스트는 이 의존성을 override해 fake resolver를 주입한다(실 backend 호출 방지)."""
    return StockResolverClient()


def get_adapters() -> dict[str, AgentAdapter]:
    """상위 supervisor execution 계층의 agent adapter 레지스트리(실사용 5개).

    테스트는 이 의존성을 override해 fake adapter를 주입한다(실 agent/네트워크 방지)."""
    return default_adapters()
