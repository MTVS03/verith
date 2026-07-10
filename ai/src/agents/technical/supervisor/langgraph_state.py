"""Technical Agent LangGraph 실행 state + 주입 의존성 (`feat/technical-langgraph-orchestration`).

**정화된 state 경계(sanitized boundary).** runtime 의존성(원본 query가 담긴 `payload`·runtime client
`llm_client`/`fetcher`/`cache`/`trace`)은 **`TechnicalDeps`로 묶어 graph `config['configurable']['deps']`
로 주입**한다. LangGraph **state(`TechnicalGraphState`)에는 계산 결과만** 담긴다 — 그래서 state는
secret-safe다: checkpointer·LangSmith state tracing이 state를 직렬화해도 PII(원본 query)·secret(client)이
새지 않는다. `config`는 traced state가 아니므로 deps는 관측/저장 경로에 노출되지 않는다.

`total=False`는 LangGraph state가 노드별로 **점진적으로** 채워지기 때문이다(전 필드 required 불가).
순환 import 없이 좁힐 수 있는 타입만 정확히 두고, 순환이 생기는 내부 타입(`_Interpretation`·
`OhlcvFetcher`/`MinuteFetcher` alias)은 `Any`로 둔다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig

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


@dataclass(frozen=True)
class TechnicalDeps:
    """graph invoke 시 `config['configurable']['deps']`로 주입되는 **runtime 의존성**.

    원본 query(`payload`)·runtime client(`llm_client`/`fetcher`/`cache`/`trace`)를 담는다 —
    **traced state에 넣지 않는다.** state는 계산 결과만 담아 secret-safe가 되므로 checkpointer·
    LangSmith tracing을 켜도 PII·secret이 직렬화되지 않는다(이 분리가 '정화된 state 경계').
    """
    payload: TechnicalAgentInput          # 원본 query 포함(PII) — config로만 흐른다(state 아님)
    trace_id: str
    trace: TraceLogger                    # runtime 객체
    llm_client: LlmClient                 # runtime client
    fetcher: Any                          # OhlcvFetcher(supervisor alias → 순환 회피 위해 Any)
    cache: OhlcvCache | None              # runtime client
    deadline: Deadline | None
    intraday_candles: Sequence[IntradayCandle] | None  # run()이 Sequence로 받음
    intraday_fetcher: Any                 # MinuteFetcher(supervisor alias → Any)
    name_resolver: Callable[[str], str | None] | None = None  # (ticker)→KIS 종목명. None이면 조회 안 함(테스트/미배선)


def deps_of(config: RunnableConfig) -> TechnicalDeps:
    """graph node가 `config`에서 주입 의존성을 꺼낸다. state가 아니라 config로 흐르므로
    traced state·checkpointer에 PII·client가 남지 않는다."""
    return config["configurable"]["deps"]


class TechnicalGraphState(TypedDict, total=False):
    # ── 계산 결과만 담는다(secret-safe). 주입 deps(payload·client 등)는 TechnicalDeps(config)로 분리됨 ──
    normalized: NormalizeResult          # 노드 1 결과(정규화 질문). focus_analysis 노드가 입력으로 사용
    focus: FocusResult
    ohlcv: dict[str, Sequence[OHLCV]]     # _collect_ohlcv 반환 타입과 일치
    daily: Sequence[OHLCV]
    weekly: Sequence[OHLCV]
    monthly: Sequence[OHLCV]
    used_stale: bool
    source: str
    resolved_stock_name: str | None       # KIS output1 종목명(best-effort, 표시용). data_collect에서 채움
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
