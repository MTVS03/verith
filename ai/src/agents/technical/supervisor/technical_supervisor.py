"""AI Technical Supervisor — `run()` 진입점(allowlist·trace lifecycle·예외 분기) + 노드 계산 helper.

정본: architecture.md·pipeline.md·sequence.md·contracts.md §4. `TechnicalAgentOutput` 최종 조립은
`build_output` 노드(technical_graph)에서 하며, 그 helper(`_to_*`·`_unavailable_output` 등)를 이 파일이 소유한다.

책임:
  - `run()`: allowlist 선검증 → trace_start → LangGraph graph.invoke(state) → trace_end → output.
  - **노드 1~10 실행 순서 조율은 `technical_graph`(LangGraph StateGraph)가 담당**하고, 이 파일은 각
    노드가 호출하는 계산 helper(_preprocess·_collect_ohlcv·regime/indicator/signal/risk 조립·_interpret)를 소유한다.
  - interpret_report 재생성 루프(1회)와 template fallback을 소유한다(`_interpret`).
  - LLM 호출 자체 예외(client.complete)는 잡아 template fallback으로 진행(사용자 응답 생성).
  - fetcher/KIS 실패·envelope 불량·계약 조립 불가·예상 못한 계산 오류는 전파(조용히 삼키지 않음).

known debt(후속 리팩토링): graph가 이 파일의 private helper를 `_sup.`로 호출하고 이 파일은 graph를
lazy import하는 **양방향 결합**이 남아 있다 — 계산 helper를 별도 `pipeline_steps` 모듈로 옮겨
`supervisor → graph → steps` 단방향으로 정리하는 것은 다음 브랜치 범위다. checkpointer/persistent
memory는 state 정화 전까지 도입하지 않는다(langgraph_state.py 보안 경계).
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone

# INTRADAY_FETCH_ENABLED·fetch_minute_ohlcv는 supervisor 코드가 직접 쓰진 않지만, technical_graph가
# `_sup.<name>`으로 런타임 조회하고 테스트가 sup에 monkeypatch하므로 여기 import를 유지한다(noqa F401).
from ..config import BATTERY_TICKERS, REGEN_MAX_COUNT
from ..config import INTRADAY_FETCH_ENABLED  # noqa: F401 - technical_graph가 _sup로 참조·테스트 monkeypatch
from ..charts.intraday_chart_builder import build_intraday_chart_payload
from ..charts.intraday_context_builder import build_intraday_context
from ..nodes import interpret_report as interp
from ..nodes._llm_utils import LlmCallError, call_llm
from ..nodes.data_collect import run_data_collect
from ..nodes.focus_analysis import FocusResult, run_focus_analysis
from ..nodes.normalize_question import NormalizeResult, run_normalize_question
from ..observability import trajectory_eval
from ..regime.multiframe import MultiframeRegimeResult
from ..schemas.contracts import (
    ChartPayload,
    InterpretationResult,
    RegimeResult,
    RiskItem,
    SignalSummary,
    TechnicalAgentInput,
    TechnicalAgentOutput,
    TechnicalSignal,
    VerificationResult,
)
from ..schemas.enums import (
    AlignmentFlag,
    DataStatus,
    GenerationSource,
    Regime,
    Trend,
    VerificationOutcome,
)
from ..schemas.intraday import IntradayCandle, IntradayContext
from ..schemas.ohlcv import OHLCV
from ..services.cache_service import OhlcvCache, as_of_identity
from ..observability.trace_logger import TraceLogger, TraceSink, hash_query
from ..runtime.deadline import Deadline, check_deadline
from ..services.kis_client import (  # noqa: F401 - fetch_minute_ohlcv는 technical_graph가 _sup로 참조
    IntradayFetchResult,
    KisApiError,
    OutOfScopeTickerError,
    fetch_minute_ohlcv,
    fetch_multi_timeframe_ohlcv,
    normalize_end_date,
)
from ..synthesis.confidence import ConfidenceResult
from ..synthesis.intraday_adjustment import apply_intraday_adjustments
from ..synthesis.intraday_alignment import apply_intraday_hint_to_context
from ..synthesis.signal_score import IndicatorSignalResult, SignalScoreResult

logger = logging.getLogger(__name__)

OhlcvFetcher = Callable[[str], dict[str, Sequence[OHLCV]]]
# 1D 분봉 fetcher(선택 주입). (ticker, *, as_of) → IntradayFetchResult. 기본 None(주입 시에만 호출).
MinuteFetcher = Callable[..., IntradayFetchResult]

# 노드 1·2 LLM 호출 실패 시 내부 대체값(출력에 실리지 않는 orchestration 정보).
_DEFAULT_FOCUS = ["trend", "momentum", "volume", "support_resistance", "risk"]
_DEFAULT_FOCUS_SUMMARY = "추세·모멘텀·거래량·지지저항·리스크 관찰점을 함께 확인합니다."


@dataclass(frozen=True)
class _Interpretation:
    """interpret 루프 결과 묶음(내부 전용)."""
    interpretation: InterpretationResult
    details: list[interp.DetailResult]
    verification: VerificationResult


def run(
    agent_input: TechnicalAgentInput,
    *,
    llm_client: interp.LlmClient,
    fetcher: OhlcvFetcher = fetch_multi_timeframe_ohlcv,
    trace_id: str | None = None,
    trace_sink: TraceSink | None = None,
    cache: OhlcvCache | None = None,
    intraday_candles: Sequence[IntradayCandle] | None = None,
    intraday_fetcher: MinuteFetcher | None = None,
    deadline: Deadline | None = None,
) -> TechnicalAgentOutput:
    """TechnicalAgentInput → 1~10 노드 조율 → TechnicalAgentOutput.

    1D intraday(선택·best-effort): `intraday_candles`를 직접 주면 그대로 쓰고, 아니면 `intraday_fetcher`가
    주어졌을 때만 `intraday_fetcher(ticker, as_of=as_of)`로 당일 분봉 snapshot을 1회 조회한다(KIS REST).
    둘 다 없거나 fetch 실패·빈 응답이면 intraday를 붙이지 않고 **기존 D/W/M 출력과 동일**하게 동작한다.
    intraday fetch 실패는 D/W/M 흐름과 분리해 흡수하며 전체 실패로 전파하지 않는다.

    `trace_sink`(선택): 주입 시 실행 trace를 emit한다(trace_schema.md). 미주입이면 Noop —
    기존 동작·출력·성능이 불변이다. trace emit 실패는 흡수하며 계산/판단 로직에 영향을 주지 않는다.

    `deadline`(선택): 주요 stage 시작 전 `check()`로 예산 초과를 조기 감지한다(cooperative). 초과 시
    `DeadlineExceeded`를 그대로 전파(endpoint가 504 AI_TIMEOUT으로 변환). 미주입이면 시간 제한 없음.

    **allowlist**: MVP 조사 범위(BATTERY_TICKERS) 밖 ticker는 OpenAI/cache/KIS **이전에** 즉시
    `OutOfScopeTickerError`로 거절한다 — fake/custom fetcher·fresh cache를 주입해도 우회되지 않는다.
    """
    if agent_input.ticker not in BATTERY_TICKERS:  # allowlist 선검증(전 진입 경로 보호, OpenAI 호출 전)
        raise OutOfScopeTickerError(f"MVP 조사 범위 밖 종목입니다: {agent_input.ticker!r}")
    trace_id = trace_id or uuid.uuid4().hex
    # 관측 계층(trace_schema.md). sink 미주입이면 Noop — 기존 동작·성능 불변. trace 실패는 흡수(계산 무영향).
    trace = TraceLogger(trace_sink, trace_id=trace_id)
    run_started = trace.now_iso()
    trace.emit("trace_start", started_at=run_started, input_summary={
        "ticker": agent_input.ticker,
        "as_of": str(agent_input.as_of),
        "original_query_hash": hash_query(agent_input.query),  # 원문 평문 미기록(§10)
    })
    # 파이프라인(노드 1~10)은 LangGraph StateGraph가 조율한다(technical_graph). 흐름 표현만 바뀌고
    # 계산·output schema는 그대로다. lazy import로 순환(graph→supervisor helper)을 끊는다.
    from .technical_graph import build_technical_graph
    initial_state = {
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


# ─────────────────────────────────────────────────────────────────────────────
# trace 요약 헬퍼 (secret·원문 미포함 — count/enum/hash만)
# ─────────────────────────────────────────────────────────────────────────────
def _ohlcv_counts(data: dict[str, Sequence[OHLCV]]) -> dict[str, dict[str, int]]:
    """OHLCV 배열은 저장 금지 — 기간별 캔들 개수만 요약."""
    return {"candle_counts": {tf: len(data.get(tf, [])) for tf in _DWM}}


def _chart_summary(charts: Sequence[ChartPayload]) -> dict[str, object]:
    """차트 배열/annotation 원본은 저장 금지 — 기간·annotation 개수만 요약(chart_annotation_spec §18)."""
    return {
        "periods": [c.period.value for c in charts],
        "annotation_counts_by_period": {
            c.period.value: len(getattr(c.chart_data, "annotations", []) or []) for c in charts
        },
    }


def _trace_end_summary(output: TechnicalAgentOutput) -> dict[str, object]:
    """trace_end 요약: 완료 상태·data_status·final_regime·검증 결과(원문/시세 미포함)."""
    return {
        "status": "completed",
        "data_status": output.data_status.value,
        "final_regime": output.regime.final_regime.value if output.regime else None,
        "outcome": output.verification.outcome.value if output.verification else None,
        "regen_count": output.verification.regen_count if output.verification else None,
    }


def _emit_regime_unavailable_skips(trace: TraceLogger) -> None:
    """regime_unavailable → 노드 4·6·7·8 skipped 기록(trace_schema.md §9.1).

    국면분류(노드 5·gate)를 지표계산(노드 4·신호용 bundle)보다 먼저 실행하므로, unavailable이면
    지표계산부터 스킵된다 — indicator_calculate까지 skipped로 기록해 trace 정직성을 지킨다(§10노드).
    """
    reason = {"reason": "regime_unavailable"}
    input_summary = {"final_regime": "unavailable", "data_status": "regime_unavailable"}
    for node_code in ("indicator_calculate", "signal_aggregate", "confidence_calculate", "risk_detect"):
        trace.emit("node_end", "skipped", node=node_code,
                   input_summary=input_summary, output_summary=reason)


# ─────────────────────────────────────────────────────────────────────────────
# 노드 1·2 전처리 (LLM 호출 예외는 fallback으로 흡수, 산출물은 내부 전용)
# ─────────────────────────────────────────────────────────────────────────────
def _preprocess(
    client: interp.LlmClient, agent_input: TechnicalAgentInput, trace: TraceLogger,
    deadline: Deadline | None = None,
) -> tuple[NormalizeResult, FocusResult]:
    # LlmCallError(LLM 호출 실패)만 흡수 → fallback. 파일 로딩·타입·프로그래밍 오류는 전파(M2).
    # 원문 query는 hash만 기록(§10). LLM prompt/response 원문은 절대 남기지 않는다.
    with trace.node("normalize_question",
                    input_summary={"original_query_hash": hash_query(agent_input.query)}) as span:
        try:
            normalized = run_normalize_question(
                client, ticker=agent_input.ticker, query=agent_input.query, as_of=agent_input.as_of)
        except LlmCallError:
            name = BATTERY_TICKERS.get(agent_input.ticker, agent_input.ticker)
            normalized = NormalizeResult(
                f"{name}의 최근 시세와 기술적 신호를 중심으로 현재 차트 국면과 리스크 관찰점을 분석합니다.",
                GenerationSource.TEMPLATE_FALLBACK,
            )
            trace.emit("fallback", node="normalize_question",
                       output_summary={"fallback_type": "template_fallback", "reason": "llm_call_failed"})
        span.output_summary = {"source": normalized.source.value}
    check_deadline(deadline, "focus_analysis")  # 노드 2 LLM 호출 전 예산 확인
    with trace.node("focus_analysis") as span:
        try:
            focus = run_focus_analysis(
                client, ticker=agent_input.ticker, normalized_question=normalized.normalized_question)
        except LlmCallError:
            focus = FocusResult(list(_DEFAULT_FOCUS), _DEFAULT_FOCUS_SUMMARY, GenerationSource.TEMPLATE_FALLBACK)
            trace.emit("fallback", node="focus_analysis",
                       output_summary={"fallback_type": "template_fallback", "reason": "llm_call_failed"})
        span.output_summary = {"analysis_focus": list(focus.analysis_focus), "source": focus.source.value}
    return normalized, focus


# ─────────────────────────────────────────────────────────────────────────────
# 로컬 dataclass → contracts.* 조립
# ─────────────────────────────────────────────────────────────────────────────
def _to_regime_result(m: MultiframeRegimeResult) -> RegimeResult:
    """MultiframeRegimeResult → RegimeResult (필드 1:1)."""
    return RegimeResult(
        daily_regime=m.daily_regime,
        final_regime=m.final_regime,
        weekly_trend=m.weekly_trend,
        monthly_trend=m.monthly_trend,
        alignment_flag=m.alignment_flag,
        regime_context=m.regime_context,
    )


def _to_signal_summary(score: SignalScoreResult, conf: ConfidenceResult) -> SignalSummary:
    """SignalScoreResult(신호) + ConfidenceResult(신뢰도) → SignalSummary."""
    return SignalSummary(
        consensus=score.consensus,
        signal_score=score.signal_score,
        confidence=conf.confidence,
        confidence_level=conf.confidence_level,
        confidence_basis=conf.confidence_basis,
    )


def _to_technical_signals(
    signals: Sequence[IndicatorSignalResult],
    details: Sequence[interp.DetailResult],
) -> list[TechnicalSignal]:
    """IndicatorSignalResult(코드 확정) + DetailResult(LLM 서술) → TechnicalSignal.

    value=None은 그대로 보존한다(계약 float|None). signal·value·weight는 코드 확정값 불변.
    """
    detail_by_indicator = {d.indicator: d for d in details}
    result: list[TechnicalSignal] = []
    for s in signals:
        detail = detail_by_indicator[s.indicator.value]
        result.append(TechnicalSignal(
            indicator=s.indicator,
            signal=s.signal,
            value=s.value,
            metrics=list(s.metrics),
            detail=detail.detail,
            detail_source=detail.detail_source,
            weight=s.weight,
        ))
    return result


def _data_status(m: MultiframeRegimeResult) -> DataStatus:
    """정상 vs data_limited(W/M 추세 unavailable). regime_unavailable은 상위 분기에서 처리."""
    if m.weekly_trend == Trend.UNAVAILABLE or m.monthly_trend == Trend.UNAVAILABLE:
        return DataStatus.DATA_LIMITED
    return DataStatus.NORMAL


@dataclass(frozen=True)
class _ResolvedIntraday:
    """intraday 입력 해석 결과 — candles + KIS output1 metadata(fetcher만 채움, 직접 주입은 None)."""
    candles: Sequence[IntradayCandle]
    previous_close: float | None
    latest_price: float | None
    cumulative_volume: int | None
    cumulative_trading_value: int | None


def _intraday_matches_as_of(
    candles: Sequence[IntradayCandle], as_of: date | datetime | None,
) -> bool:
    """모든 intraday candle 의 날짜가 as_of.date() 와 같은지 (날짜 정합성 가드).

    KIS 주식당일분봉조회는 **당일 데이터만** 제공하므로, 과거 `as_of` 리포트에 오늘 분봉이 결합되는 것을
    막는다. `as_of` 가 None이면 True(기존 동작 유지), 빈 candles도 True(상위에서 intraday off 처리).
    일부 candle만 날짜가 달라도 False(fail-safe로 intraday off).
    """
    if as_of is None or not candles:
        return True
    expected = (as_of.date() if isinstance(as_of, datetime) else as_of).isoformat()
    return all(c.timestamp[:10] == expected for c in candles)


def _resolve_intraday(
    intraday_candles: Sequence[IntradayCandle] | None,
    intraday_fetcher: MinuteFetcher | None,
    ticker: str,
    as_of: datetime,
) -> _ResolvedIntraday | None:
    """intraday 입력 해석. `_ResolvedIntraday`(candles + output1 metadata) 또는 None 반환.

    직접 주입 candles가 있으면 fetch하지 않고 그대로 쓴다(output1 metadata 없음 → candle fallback).
    없고 intraday_fetcher가 주어졌을 때만 `intraday_fetcher(ticker, as_of=as_of)`로 조회하며,
    IntradayFetchResult의 previous_close·latest_price·cumulative_volume·cumulative_trading_value를 보존한다.
    fetch 실패는 D/W/M와 **분리**해 흡수 → `None`(intraday off).
    **날짜 정합성 가드**: candle 날짜가 as_of.date()와 다르면(당일분봉 today-only) intraday를 생략한다
    — 직접 주입·fetcher 두 경로 모두에 적용된다.
    """
    if intraday_candles is not None:
        resolved = _ResolvedIntraday(intraday_candles, None, None, None, None)  # 직접 주입: metadata 없음
    elif intraday_fetcher is None:
        return None
    else:
        try:
            result = intraday_fetcher(ticker, as_of=as_of)  # KIS REST 1회+제한 반복(fetcher 내부 정책)
        except Exception:  # noqa: BLE001 - intraday fetch 실패는 D/W/M와 분리·흡수(전체 실패 아님)
            # best-effort: 1d 없이 계속하되 원인은 기록(secret 미포함 — ticker/as_of/stage만).
            logger.warning(
                "intraday_fetch_failed",
                extra={"ticker": ticker, "as_of": str(as_of), "stage": "resolve_intraday"},
                exc_info=True,
            )
            return None
        resolved = _ResolvedIntraday(
            result.candles, result.previous_close, result.latest_price,
            result.cumulative_volume, result.cumulative_trading_value,
        )

    if resolved.candles and not _intraday_matches_as_of(resolved.candles, as_of):
        return None  # 과거 as_of 리포트에 오늘 분봉이 결합되는 것 방지
    return resolved


def _assemble_intraday(
    resolved: _ResolvedIntraday | None,
    *,
    daily: Sequence[OHLCV],
    as_of: datetime,
    final_regime: Regime,
) -> tuple[list[ChartPayload], IntradayContext | None]:
    """선택적 1D intraday 조립. 이미 만든 builder/helper만 호출한다.

    candles가 없으면 `([], None)` — D/W/M 출력과 완전히 동일하게 동작한다.
    previous_close는 **fetcher가 준 값(전일 종가)을 우선**하고, 없으면 최근 일봉 종가로 fallback한다.
    latest_price·cumulative_volume·cumulative_trading_value는 output1 metadata(있으면)를 context에 전달한다.
    intraday 조립 중 어떤 예외든 흡수해 D/W/M 출력이 통째로 실패하지 않게 한다.
    final_regime은 읽기만 하며 절대 바꾸지 않는다(보정도 하지 않음).
    """
    if resolved is None or not resolved.candles:
        return [], None
    try:
        prev_close = (resolved.previous_close if resolved.previous_close is not None
                      else (daily[-1].close if daily else None))
        payload = build_intraday_chart_payload(resolved.candles, previous_close=prev_close)
        context = build_intraday_context(
            resolved.candles, previous_close=prev_close, as_of=as_of,
            latest_price=resolved.latest_price,
            cumulative_volume=resolved.cumulative_volume,
            cumulative_trading_value=resolved.cumulative_trading_value,
        )
        context = apply_intraday_hint_to_context(context, final_regime)
        context = apply_intraday_adjustments(context)  # confidence_adjustment·risk_notes(context 내부만)
        return [payload], context
    except Exception:  # noqa: BLE001 - intraday 실패가 D/W/M 전체를 깨지 않도록 흡수
        # best-effort: 1d 없이 계속하되 원인은 기록(secret 미포함 — as_of/stage만).
        logger.warning(
            "intraday_assemble_failed",
            extra={"as_of": str(as_of), "stage": "assemble_intraday"},
            exc_info=True,
        )
        return [], None


# ─────────────────────────────────────────────────────────────────────────────
# 노드 10 interpret 루프: 1차 + REGEN_MAX_COUNT 재생성 → granular(부분) fallback
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _Attempt:
    call_failed: bool
    parsed: dict | None
    result: trajectory_eval.EvalResult | None

    @property
    def passed(self) -> bool:
        return self.result is not None and self.result.passed


def _attempt(
    client: interp.LlmClient, prompt_name: str, payload: dict,
    *, regime: RegimeResult, signal: SignalSummary,
    signals: Sequence[IndicatorSignalResult], risks: Sequence[RiskItem],
) -> _Attempt:
    """1회 LLM 호출 + 검증. 호출 예외(LlmCallError)/파싱 실패/검증 결과를 구분해 담는다."""
    prompt = interp.render_prompt(interp.load_prompt(prompt_name), payload)
    try:
        raw = call_llm(client, prompt)
    except LlmCallError:
        return _Attempt(True, None, None)
    try:
        parsed = interp.parse_llm_output(raw)
    except interp.LlmOutputParseError:
        return _Attempt(False, None, None)
    ev = interp.verify(parsed, regime=regime, signal=signal, signals=signals, risks=risks)
    return _Attempt(False, parsed, ev)


def _interpret(
    client: interp.LlmClient, *,
    regime: RegimeResult, signal: SignalSummary,
    signals: Sequence[IndicatorSignalResult], risks: Sequence[RiskItem], focus: FocusResult,
    trace: TraceLogger, deadline: Deadline | None = None,
) -> _Interpretation:
    # LLM prompt/response 원문은 trace에 남기지 않는다 — 재생성/폴백은 retry/fallback 이벤트로만 관측(§12).
    with trace.node("interpret_report") as span:
        payload = interp.build_payload(
            regime=regime, signal=signal, signals=signals, risks=risks,
            analysis_focus=focus.analysis_focus, focus_summary=focus.focus_summary,
        )
        # 1차(interpret) + REGEN_MAX_COUNT회 재생성(config.md §9).
        prompt_seq = [interp.INTERPRET_PROMPT] + [interp.REGENERATE_PROMPT] * REGEN_MAX_COUNT
        last: _Attempt | None = None
        result: _Interpretation | None = None
        for i, name in enumerate(prompt_seq):
            if i > 0:  # 직전 검증 실패로 재생성 시도 → retry 이벤트(§12)
                check_deadline(deadline, "interpret_regeneration")  # 재생성 시도 전 예산 확인
                trace.emit("retry", node="interpret_report",
                           output_summary={"attempt": i, "reason": "verification_failed"})
            attempt = _attempt(client, name, payload,
                               regime=regime, signal=signal, signals=signals, risks=risks)
            if attempt.call_failed:  # 호출 예외 → 재생성 없이 template fallback(정책 §6-9)
                trace.emit("fallback", node="interpret_report", output_summary={
                    "fallback_type": "template_fallback", "reason": "llm_call_failed"})
                result = _full_fallback(regime, signal, signals, risks, regen_count=i)
                break
            _emit_validation(trace, attempt, i)  # 검증③ 결과 요약(원문 미포함)
            last = attempt
            if attempt.passed:
                source = GenerationSource.LLM if i == 0 else GenerationSource.LLM_REGENERATED
                result = _success(attempt, source, signals, regen_count=i)
                break
        else:
            # 재생성까지 소진 → 마지막 출력 기준 granular(부분) fallback (H2/REGEN-04).
            trace.emit("fallback", node="interpret_report", output_summary={
                "fallback_type": "template_fallback", "reason": "regen_exhausted"})
            result = _granular_fallback(last, regime, signal, signals, risks, regen_count=REGEN_MAX_COUNT)
        span.output_summary = _interpret_summary(result)
        return result


def _emit_validation(trace: TraceLogger, attempt: _Attempt, attempt_idx: int) -> None:
    """검증③(LLM 라벨 왜곡) 결과를 validation 이벤트로 남긴다 — raw LLM 응답이 아닌 요약만(§9·§12)."""
    ev = attempt.result
    if ev is None:  # 파싱 실패 → 검증 자체 불가
        trace.emit("validation", "failed", node="interpret_report",
                   output_summary={"attempt": attempt_idx, "validation_result": "parse_failed"})
        return
    trace.emit(
        "validation", "success" if ev.passed else "failed", node="interpret_report",
        output_summary={
            "attempt": attempt_idx,
            "validation_result": "passed" if ev.passed else "failed",
            "label_matched": not ev.interpretation_failed,
            "interpretation_failed": ev.interpretation_failed,
            "details_structure_failed": ev.details_structure_failed,
            "failed_indicators": sorted(ev.failed_indicators),  # 지표명만(원문 없음)
        },
    )


def _interpret_summary(result: _Interpretation) -> dict[str, object]:
    """interpret_report node_end 요약 — 최종 source·detail source 분포·재생성/폴백 여부(원문 없음)."""
    detail_source_count = Counter(d.detail_source.value for d in result.details)
    return {
        "interpretation_source": result.interpretation.source.value,
        "detail_source_count": dict(detail_source_count),
        "regen_count": result.verification.regen_count,
        "template_fallback_used": result.verification.outcome == VerificationOutcome.TEMPLATE_FALLBACK,
        "outcome": result.verification.outcome.value,
    }


def _success(
    attempt: _Attempt, source: GenerationSource,
    signals: Sequence[IndicatorSignalResult], *, regen_count: int,
) -> _Interpretation:
    assert attempt.parsed is not None and attempt.result is not None
    interpretation = interp.interpretation_from_llm(attempt.parsed, source=source)
    details = interp.details_from_llm(
        attempt.parsed, signals=signals, source=source,
        failed_indicators=attempt.result.failed_indicators)
    verification = VerificationResult(
        calc_passed=True, regime_passed=True, label_matched=True,
        outcome=VerificationOutcome.PASSED, regen_count=regen_count,
    )
    return _Interpretation(interpretation, details, verification)


def _granular_fallback(
    last: _Attempt | None, regime: RegimeResult, signal: SignalSummary,
    signals: Sequence[IndicatorSignalResult], risks: Sequence[RiskItem], *, regen_count: int,
) -> _Interpretation:
    """interpretation·detail을 **독립적으로** 폴백: 실패한 부분만 template, 통과한 부분은 LLM 유지.

    구조 자체를 신뢰할 수 없으면(파싱 실패·details 개수/코드값 불일치·확정값 재생성 필드) 전체 폴백.
    """
    if (last is None or last.parsed is None or last.result is None
            or last.result.details_structure_failed
            or any(f.reason == "forbidden_output_field" for f in last.result.failures)):
        return _full_fallback(regime, signal, signals, risks, regen_count=regen_count)

    ev = last.result
    kept_source = GenerationSource.LLM if regen_count == 0 else GenerationSource.LLM_REGENERATED
    if ev.interpretation_failed:
        interpretation = interp.fallback_interpretation(regime=regime, signal=signal, risks=risks)
    else:
        interpretation = interp.interpretation_from_llm(last.parsed, source=kept_source)
    # 실패한 indicator의 detail만 template_fallback, 나머지는 LLM 유지(REGEN-04).
    details = interp.details_from_llm(
        last.parsed, signals=signals, source=kept_source,
        failed_indicators=ev.failed_indicators)
    verification = VerificationResult(
        calc_passed=True, regime_passed=True,
        label_matched=not ev.interpretation_failed,
        outcome=VerificationOutcome.TEMPLATE_FALLBACK, regen_count=regen_count,
    )
    return _Interpretation(interpretation, details, verification)


def _full_fallback(
    regime: RegimeResult, signal: SignalSummary,
    signals: Sequence[IndicatorSignalResult], risks: Sequence[RiskItem], *, regen_count: int,
) -> _Interpretation:
    interpretation = interp.fallback_interpretation(regime=regime, signal=signal, risks=risks)
    details = [interp.fallback_detail(s.indicator, s.signal, s.metrics) for s in signals]
    verification = VerificationResult(
        calc_passed=True, regime_passed=True, label_matched=False,
        outcome=VerificationOutcome.TEMPLATE_FALLBACK, regen_count=regen_count,
    )
    return _Interpretation(interpretation, details, verification)


# ─────────────────────────────────────────────────────────────────────────────
# unavailable 안전 착지 (contracts.md §4)
# ─────────────────────────────────────────────────────────────────────────────
def _empty_regime(context: str) -> RegimeResult:
    return RegimeResult(
        daily_regime=Regime.UNAVAILABLE,
        final_regime=Regime.UNAVAILABLE,
        weekly_trend=Trend.UNAVAILABLE,
        monthly_trend=Trend.UNAVAILABLE,
        alignment_flag=AlignmentFlag.NEUTRAL,
        regime_context=context,
    )


_DWM = ("D", "W", "M")


def _collect_ohlcv(
    ticker: str, as_of: object, fetcher: OhlcvFetcher, cache: OhlcvCache | None,
    trace: TraceLogger,
) -> tuple[dict[str, Sequence[OHLCV]], bool]:
    """cache-aware D/W/M 수집 → (dict, used_stale). config.md §7·§8 폴백 분기.

    cache=None이면 캐시 없이 `run_data_collect` 그대로(기존 동작). 캐시가 있으면:
      1. D/W/M **모두 fresh** → KIS 없이 캐시 사용(used_stale=False)
      2. 아니면 KIS(`run_data_collect`) → 성공 시 3종 write 후 사용(source="KIS")
      3. KIS 통신 실패(**`KisApiError`만**) → **per-timeframe stale 재구성**:
         D는 fresh/stale 중 있어야 하고(없으면 예외 전파), W/M은 있으면 쓰고 없으면 `[]`
         (downstream이 unavailable/data_limited로 처리). 하나라도 stale이면 used_stale=True.
    **envelope 오류·잘못된 as_of·OHLCV/타입/프로그래밍 오류는 stale로 덮지 않고 전파한다(fail-fast).**
    Redis 장애는 cache_service가 miss/no-op으로 흡수하므로 여기서 전파되지 않는다.
    """
    with trace.node("data_collect", input_summary={"ticker": ticker, "as_of": str(as_of)}) as span:
        if cache is None:
            data = run_data_collect(ticker, as_of=as_of, fetcher=fetcher)
            span.output_summary = {**_ohlcv_counts(data), "source": "kis"}
            return data, False
        now = datetime.now(timezone.utc)
        as_of_id = as_of_identity(normalize_end_date(as_of))

        fresh = _cache_collect_all_fresh(cache, ticker, as_of_id, now)
        if fresh is not None:
            span.output_summary = {
                **_ohlcv_counts(fresh), "source": "cache",
                "cache_hit_by_period": {tf: True for tf in _DWM},
            }
            return fresh, False
        try:
            data = run_data_collect(ticker, as_of=as_of, fetcher=fetcher)
        except KisApiError:  # 복구 가능한 KIS 통신/조회 실패만 stale 폴백 허용
            recon = _stale_reconstruct(cache, ticker, as_of_id, now)
            if recon is not None:
                recon_data, used_stale = recon
                trace.emit("fallback", node="data_collect", output_summary={
                    "fallback_type": "stale_cache", **_ohlcv_counts(recon_data),
                })
                span.output_summary = {
                    **_ohlcv_counts(recon_data), "source": "cache_stale", "used_stale": used_stale,
                }
                return recon  # (dict, used_stale)
            raise  # D stale/fresh 없음 → 재구성 불가 → 기존 KIS 실패 전파(node_end failed로 기록)
        for tf in _DWM:
            cache.set(ticker, tf, as_of_id, list(data[tf]), now=now)
        result = {tf: list(data[tf]) for tf in _DWM}
        span.output_summary = {**_ohlcv_counts(result), "source": "kis", "cache_written": True}
        return result, False


def _cache_collect_all_fresh(
    cache: OhlcvCache, ticker: str, as_of_id: str, now: datetime,
) -> dict[str, Sequence[OHLCV]] | None:
    """D/W/M **모두** fresh면 dict, 하나라도 아니면 None(→ KIS 조회)."""
    out: dict[str, Sequence[OHLCV]] = {}
    for tf in _DWM:
        look = cache.get(ticker, tf, as_of_id, now=now)
        if look.status == "fresh" and look.candles is not None:
            out[tf] = look.candles
        else:
            return None
    return out


def _stale_reconstruct(
    cache: OhlcvCache, ticker: str, as_of_id: str, now: datetime,
) -> tuple[dict[str, Sequence[OHLCV]], bool] | None:
    """KIS 실패 후 per-timeframe 재구성. **D 필수**(fresh/stale 없으면 None→전파), W/M은 없으면 `[]`.

    tf별로 fresh 우선, 없으면 stale 사용. stale을 하나라도 쓰면 used_stale=True.
    """
    out: dict[str, Sequence[OHLCV]] = {}
    used_stale = False
    for tf in _DWM:
        look = cache.get(ticker, tf, as_of_id, now=now)
        if look.status in ("fresh", "stale") and look.candles is not None:
            out[tf] = look.candles
            if look.status == "stale":
                used_stale = True
        elif tf == "D":
            return None      # 일봉이 없으면 분석 불가 → 원 KIS 예외 전파
        else:
            out[tf] = []     # W/M 없음 → 빈 리스트(regime unavailable·chart 빈 5y로 안전 처리)
    return out, used_stale


def _unavailable_output(
    agent_input: TechnicalAgentInput, trace_id: str, data_status: DataStatus,
    *, regime: RegimeResult, charts: Sequence[ChartPayload], source: str = "KIS",
) -> TechnicalAgentOutput:
    """regime 판단 불가 → signal·risk null, technical_signals=[], interpretation=template fallback."""
    return TechnicalAgentOutput(
        request_id=agent_input.request_id,
        ticker=agent_input.ticker,
        as_of=agent_input.as_of,
        source=source,
        trace_id=trace_id,
        data_status=data_status,
        regime=regime,
        signal=None,
        technical_signals=[],
        risk=None,
        charts=list(charts),
        interpretation=interp.unavailable_interpretation(),
        verification=VerificationResult(
            calc_passed=False, regime_passed=False, label_matched=True,
            outcome=VerificationOutcome.TEMPLATE_FALLBACK, regen_count=0,
        ),
    )
