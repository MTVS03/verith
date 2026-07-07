"""Technical Agent LangGraph 실행 state (`feat/technical-langgraph-orchestration`).

`technical_supervisor.run()`이 만든 **주입 의존성**(llm_client·fetcher·cache·trace·deadline)과
파이프라인 **중간 산출물**을 node 간에 넘기는 채널이다.

**보안 경계(중요) — 이 state는 "저장 안전(secret-safe)" 객체가 아니다.**
현재 LangGraph state는 **실행용(runtime-only)** 이며 외부 저장을 전제로 하지 않는다. checkpointer가
없기 때문에 저장되지 않을 뿐이며, state에는 **원본 query가 포함된 `payload`와 runtime client
(`llm_client`·`cache`·`fetcher`·`trace`)·대용량 OHLCV/charts**가 그대로 들어간다.

> Do not enable LangGraph checkpointer, LangSmith state tracing, or persistent callbacks until a
> **sanitized state boundary** is introduced. Otherwise the original query (PII) and runtime clients
> could be observed/persisted.

`total=False`는 LangGraph state가 노드별로 **점진적으로** 채워지기 때문이다(전 필드 required 불가).
순환 import 없이 좁힐 수 있는 타입만 정확히 두고, 순환이 생기는 내부 타입(`_Interpretation`·
`OhlcvFetcher`/`MinuteFetcher` alias)은 `Any`로 둔다.
"""

from __future__ import annotations

from typing import Any, TypedDict

from ..nodes._llm_utils import LlmClient
from ..nodes.focus_analysis import FocusResult
from ..nodes.indicator_calculate import IndicatorBundle
from ..nodes.normalize_question import NormalizeResult
from ..observability.trace_logger import TraceLogger
from ..regime.multiframe import MultiframeRegimeResult
from ..runtime.deadline import Deadline
from ..schemas.contracts import (
    ChartPayload,
    RegimeResult,
    RiskItem,
    SignalSummary,
    TechnicalAgentInput,
    TechnicalAgentOutput,
)
from ..schemas.enums import DataStatus
from ..schemas.intraday import IntradayCandle
from ..schemas.ohlcv import OHLCV
from ..services.cache_service import OhlcvCache
from ..synthesis.confidence import ConfidenceResult
from ..synthesis.signal_score import SignalScoreResult


class TechnicalGraphState(TypedDict, total=False):
    # ── 주입(무변경 통과) — endpoint/run()이 채운다. **원본 query·runtime client 포함(저장 금지)** ──
    payload: TechnicalAgentInput          # 원본 query 포함(PII) — 저장 전 정화 필요
    trace_id: str
    llm_client: LlmClient                 # runtime client — 저장 금지
    fetcher: Any                          # OhlcvFetcher(supervisor alias → 순환 회피 위해 Any)
    cache: OhlcvCache | None              # runtime client — 저장 금지
    trace: TraceLogger                    # runtime 객체 — 저장 금지
    deadline: Deadline | None
    intraday_candles: list[IntradayCandle] | None
    intraday_fetcher: Any                 # MinuteFetcher(supervisor alias → Any)

    # ── 중간 산출(계산 helper 소유 — state는 전달만, raw prompt/response 없음) ────────────────────
    normalized: NormalizeResult          # 노드 1 결과(정규화 질문). focus_analysis 노드가 입력으로 사용
    focus: FocusResult
    ohlcv: dict[str, list[OHLCV]]
    daily: list[OHLCV]
    weekly: list[OHLCV]
    monthly: list[OHLCV]
    used_stale: bool
    source: str
    regime_result: MultiframeRegimeResult
    bundle: IndicatorBundle
    signal_result: SignalScoreResult
    confidence: ConfidenceResult
    risk_items: list[RiskItem]
    charts: list[ChartPayload]
    regime: RegimeResult
    signal_summary: SignalSummary
    interpretation: Any                   # _Interpretation(supervisor 정의 → 순환 회피 위해 Any)
    data_status: DataStatus

    # ── 최종 산출 ─────────────────────────────────────────────────────────────
    output: TechnicalAgentOutput
