"""Technical Agent 내부 HTTP endpoint (`api_spec.md §7`).

**내부 전용** — `/internal` prefix. api_spec §7.1: "내부망 또는 내부 토큰으로만 호출한다. 프론트엔드는
직접 호출하지 않는다." 이번 브랜치는 인증을 구현하지 않는다(내부망/후속 gateway 전제). 실제 internal
auth·gateway token 검증은 backend/gateway 연동 단계에서 결정한다.

endpoint는 runtime 의존성(OpenAI client·KIS fetcher·Redis cache·trace sink)을 주입받아
`run_technical_agent`에 넘기고, 예외를 `api_spec §9` error envelope로 매핑한다. sync agent는
`run_in_threadpool`로 실행해 event loop를 막지 않는다. 전체 60초 deadline 강제(asyncio.wait_for)는
이 브랜치 범위 밖(정본 §10: 60초는 Backend 클라이언트 timeout, AI 내부가 KIS/LLM 폴백 처리).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from src.agents.technical.agent import run_technical_agent
from src.agents.technical.nodes._llm_utils import LlmCallError, LlmClient
from src.agents.technical.observability.trace_logger import TraceSink
from src.agents.technical.schemas.contracts import TechnicalAgentInput, TechnicalAgentOutput
from src.agents.technical.services.cache_service import OhlcvCache
from src.agents.technical.services.kis_client import KisApiError, OutOfScopeTickerError
from src.agents.technical.supervisor.technical_supervisor import OhlcvFetcher
from src.api.dependencies import get_cache, get_fetcher, get_llm_client, get_trace_sink
from src.api.errors import AppError, ai_unavailable, internal_error, out_of_scope_ticker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/technical", tags=["technical-internal"])


@router.get("/health")
def health() -> dict[str, str]:
    """router liveness — 실 연결(OpenAI/KIS/Redis) 검사 없음, 네트워크 호출 없음(api_spec §7.2)."""
    return {"status": "ok", "service": "technical-agent"}


@router.post("/analyze", response_model=TechnicalAgentOutput)
async def analyze(
    body: TechnicalAgentInput,
    llm_client: LlmClient = Depends(get_llm_client),
    fetcher: OhlcvFetcher | None = Depends(get_fetcher),
    cache: OhlcvCache | None = Depends(get_cache),
    trace_sink: TraceSink | None = Depends(get_trace_sink),
) -> TechnicalAgentOutput:
    """분석 실행(api_spec §7.1). 요청은 `TechnicalAgentInput`(request_id 필수)으로 검증된다.

    KIS 개별 실패·재생성·폴백은 agent 내부에서 흡수돼 200(stale_cache/data_limited)으로 나간다.
    endpoint까지 전파되는 예외만 §9 error envelope로 매핑한다.
    """
    try:
        return await run_in_threadpool(
            run_technical_agent,
            body,
            llm_client=llm_client,
            fetcher=fetcher,
            cache=cache,
            trace_sink=trace_sink,
        )
    except OutOfScopeTickerError:
        raise out_of_scope_ticker(body.request_id) from None      # 422 OUT_OF_SCOPE_TICKER
    except (LlmCallError, KisApiError):
        raise ai_unavailable(body.request_id) from None           # 502 AI_UNAVAILABLE
    except AppError:
        raise                                                     # 의존성/하위 계층이 낸 매핑 그대로
    except Exception:
        # 예상 못한 내부 오류 → 500. type 이름만 로깅(raw prompt/response/secret 미기록).
        logger.warning("technical_analyze_failed", extra={"request_id": body.request_id})
        raise internal_error(body.request_id) from None           # 500 INTERNAL_ERROR
