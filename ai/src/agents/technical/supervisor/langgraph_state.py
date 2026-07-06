"""Technical Agent LangGraph 실행 state (`feat/technical-langgraph-orchestration`).

`technical_supervisor.run()`이 만든 **주입 의존성**(llm_client·fetcher·cache·trace·deadline)과
파이프라인 **중간 산출물**을 node 간에 넘기는 채널이다. checkpointer 없이 in-memory로만 흐른다.

**저장 금지(trace_logger 정책과 동일):** raw OpenAI prompt/response·API key/token은 state에 담지
않는다(계산 helper가 애초에 만들지 않는다). candles/charts는 참조로만 전달하고 복제하지 않는다.
내부 dataclass(regime_result·signal_result 등)는 계산 helper가 소유하므로 여기선 `Any`로 통과만 한다.
"""

from __future__ import annotations

from typing import Any, TypedDict

from ..observability.trace_logger import TraceLogger
from ..runtime.deadline import Deadline
from ..schemas.contracts import TechnicalAgentInput, TechnicalAgentOutput
from ..services.cache_service import OhlcvCache


class TechnicalGraphState(TypedDict, total=False):
    # ── 주입(무변경 통과) — endpoint/run()이 채운다 ──────────────────────────
    payload: TechnicalAgentInput
    trace_id: str
    llm_client: Any            # nodes._llm_utils.LlmClient (Protocol) — 주입만
    fetcher: Any               # OhlcvFetcher (run() 기본값이 채움)
    cache: OhlcvCache | None
    trace: TraceLogger
    deadline: Deadline | None
    intraday_candles: Any      # Sequence[IntradayCandle] | None
    intraday_fetcher: Any      # MinuteFetcher | None

    # ── 중간 산출(계산 helper 소유 — state는 전달만, 원문/secret 없음) ────────
    focus: Any                 # FocusResult
    ohlcv: dict
    daily: list
    weekly: list
    monthly: list
    used_stale: bool
    source: str
    regime_result: Any         # MultiframeRegimeResult
    bundle: Any                # indicator bundle
    signal_result: Any         # SignalScoreResult
    confidence: Any            # ConfidenceResult
    risk_items: list
    charts: list
    regime: Any                # RegimeResult (계약)
    signal_summary: Any        # SignalSummary (계약)
    interpretation: Any        # _Interpretation (interpretation+details+verification)
    data_status: Any           # DataStatus

    # ── 최종 산출 ─────────────────────────────────────────────────────────────
    output: TechnicalAgentOutput
