"""AI Technical Supervisor — `run()` 진입점.

정본: architecture.md·pipeline.md·sequence.md·contracts.md §4.

책임(entrypoint만):
  - allowlist 선검증(MVP 범위 밖 ticker는 OpenAI/cache/KIS 이전에 거절).
  - trace lifecycle(`trace_start`/`trace_end`).
  - LangGraph graph.invoke(state)로 노드 1~10 파이프라인 위임.
  - top-level 예외 처리(trace_end failed 기록 후 전파).

의존 방향(단방향): `technical_supervisor → technical_graph → pipeline_steps`. 노드별 계산/조립
helper는 `pipeline_steps`가 소유하고, LangGraph node/edge 구성은 `technical_graph`가 담당한다.
run()은 이 둘을 조립만 한다. checkpointer/persistent memory는 state 정화 전까지 도입하지 않는다
(langgraph_state.py 보안 경계).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from .langgraph_state import TechnicalGraphState
from .pipeline_steps import MinuteFetcher, OhlcvFetcher
from .technical_graph import build_technical_graph
from ..config import is_supported_ticker
from ..nodes._llm_utils import LlmClient
from ..observability.trace_logger import TraceLogger, TraceSink, hash_query
from ..runtime.deadline import Deadline
from ..schemas.contracts import TechnicalAgentInput, TechnicalAgentOutput
from ..schemas.intraday import IntradayCandle
from ..services.cache_service import OhlcvCache
from ..services.kis_client import OutOfScopeTickerError, fetch_multi_timeframe_ohlcv


def run(
    agent_input: TechnicalAgentInput,
    *,
    llm_client: LlmClient,
    fetcher: OhlcvFetcher = fetch_multi_timeframe_ohlcv,
    trace_id: str | None = None,
    trace_sink: TraceSink | None = None,
    cache: OhlcvCache | None = None,
    intraday_candles: Sequence[IntradayCandle] | None = None,
    intraday_fetcher: MinuteFetcher | None = None,
    deadline: Deadline | None = None,
) -> TechnicalAgentOutput:
    """TechnicalAgentInput → 1~10 노드 조율(LangGraph) → TechnicalAgentOutput.

    1D intraday(선택·best-effort): `intraday_candles`를 직접 주면 그대로 쓰고, 아니면 `intraday_fetcher`가
    주어졌을 때만 `intraday_fetcher(ticker, as_of=as_of)`로 당일 분봉 snapshot을 1회 조회한다(KIS REST).
    둘 다 없거나 fetch 실패·빈 응답이면 intraday를 붙이지 않고 **기존 D/W/M 출력과 동일**하게 동작한다.

    `trace_sink`(선택): 주입 시 실행 trace를 emit한다. 미주입이면 Noop — 기존 동작·출력 불변.
    `deadline`(선택): 주요 stage 시작 전 예산 초과를 감지(cooperative). 초과 시 `DeadlineExceeded` 전파.
    **지원 정책(단일 경계)**: `config.is_supported_ticker` 밖 ticker는 OpenAI/cache/KIS **이전에** 즉시
    `OutOfScopeTickerError`로 거절한다 — fake/custom fetcher·fresh cache를 주입해도 우회되지 않는다.
    기본 정책은 형식상 유효한 ticker 전체 허용이므로(BATTERY_TICKERS membership 아님), resolver 가 식별한
    종목은 기본적으로 여기를 통과한다. 종목 지원 여부는 이후 데이터/결과 상태(data_status)로 표현한다.
    """
    if not is_supported_ticker(agent_input.ticker):  # 지원 정책 선검증(전 진입 경로 보호, OpenAI 호출 전)
        raise OutOfScopeTickerError(f"지원 정책 밖 종목입니다: {agent_input.ticker!r}")
    trace_id = trace_id or uuid.uuid4().hex
    # 관측 계층(trace_schema.md). sink 미주입이면 Noop — 기존 동작·성능 불변. trace 실패는 흡수(계산 무영향).
    trace = TraceLogger(trace_sink, trace_id=trace_id)
    run_started = trace.now_iso()
    trace.emit("trace_start", started_at=run_started, input_summary={
        "ticker": agent_input.ticker,
        "as_of": str(agent_input.as_of),
        "original_query_hash": hash_query(agent_input.query),  # 원문 평문 미기록(§10)
    })
    # 파이프라인(노드 1~10)은 LangGraph StateGraph가 조율한다(technical_graph → pipeline_steps).
    initial_state: TechnicalGraphState = {
        "payload": agent_input, "trace_id": trace_id, "llm_client": llm_client,
        "fetcher": fetcher, "cache": cache, "trace": trace, "deadline": deadline,
        "intraday_candles": intraday_candles, "intraday_fetcher": intraday_fetcher,
    }
    try:
        final_state = build_technical_graph().invoke(initial_state)
        output = final_state["output"]
    except Exception as exc:
        trace.emit("trace_end", "failed", started_at=run_started, ended_at=trace.now_iso(),
                   error=exc, output_summary={"status": "failed"})
        raise
    trace.emit("trace_end", "success", started_at=run_started, ended_at=trace.now_iso(),
               output_summary=_trace_end_summary(output))
    return output


def _trace_end_summary(output: TechnicalAgentOutput) -> dict[str, object]:
    """trace_end 요약: 완료 상태·data_status·final_regime·검증 결과(원문/시세 미포함)."""
    return {
        "status": "completed",
        "data_status": output.data_status.value,
        "final_regime": output.regime.final_regime.value if output.regime else None,
        "outcome": output.verification.outcome.value if output.verification else None,
        "regen_count": output.verification.regen_count if output.verification else None,
    }
