"""AI Technical Supervisor — 1~10 노드 조율 + contracts.* 최종 조립.

정본: architecture.md·pipeline.md·sequence.md·contracts.md §4. 이 파일에서 처음으로
`TechnicalAgentOutput`을 조립한다(그전 노드들은 로컬 dataclass만 반환).

책임:
  - 노드 1~10을 순서대로 실행하고 결과를 계약 모델로 조립한다.
  - interpret_report 재생성 루프(1회)와 template fallback을 소유한다.
  - LLM 호출 자체 예외(client.complete)는 잡아 template fallback으로 진행(사용자 응답 생성).
  - fetcher/KIS 실패·envelope 불량·계약 조립 불가·예상 못한 계산 오류는 전파(조용히 삼키지 않음).

경계(이번 브랜치 범위 밖): trace_logger·cache·DB·FastAPI·agent.py·LangGraph·E-하네스
(KIS 재시도/stale_cache, source="KIS (stale)"). 전역 state 스키마도 만들지 않는다.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from ..config import BATTERY_TICKERS, INTRADAY_FETCH_ENABLED, REGEN_MAX_COUNT
from ..charts.intraday_chart_builder import build_intraday_chart_payload
from ..charts.intraday_context_builder import build_intraday_context
from ..nodes import interpret_report as interp
from ..nodes._llm_utils import LlmCallError, call_llm
from ..nodes.chart_generate import run_chart_generate
from ..nodes.confidence_calculate import run_confidence_calculate
from ..nodes.data_collect import run_data_collect
from ..nodes.focus_analysis import FocusResult, run_focus_analysis
from ..nodes.indicator_calculate import run_indicator_calculate
from ..nodes.normalize_question import NormalizeResult, run_normalize_question
from ..nodes.regime_classify import run_regime_classify
from ..nodes.risk_detect import run_risk_detect
from ..nodes.signal_aggregate import run_signal_aggregate
from ..observability import trajectory_eval
from ..regime.multiframe import MultiframeRegimeResult
from ..schemas.contracts import (
    ChartPayload,
    InterpretationResult,
    RegimeResult,
    RiskItem,
    RiskSummary,
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
from ..services.kis_client import (
    IntradayFetchResult,
    fetch_minute_ohlcv,
    fetch_multi_timeframe_ohlcv,
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
    intraday_candles: Sequence[IntradayCandle] | None = None,
    intraday_fetcher: MinuteFetcher | None = None,
) -> TechnicalAgentOutput:
    """TechnicalAgentInput → 1~10 노드 조율 → TechnicalAgentOutput.

    1D intraday(선택·best-effort): `intraday_candles`를 직접 주면 그대로 쓰고, 아니면 `intraday_fetcher`가
    주어졌을 때만 `intraday_fetcher(ticker, as_of=as_of)`로 당일 분봉 snapshot을 1회 조회한다(KIS REST).
    둘 다 없거나 fetch 실패·빈 응답이면 intraday를 붙이지 않고 **기존 D/W/M 출력과 동일**하게 동작한다.
    intraday fetch 실패는 D/W/M 흐름과 분리해 흡수하며 전체 실패로 전파하지 않는다.
    """
    trace_id = trace_id or uuid.uuid4().hex

    # 노드 1·2 (LLM 전처리). 최종 output엔 싣지 않지만, focus는 노드 10 설명 강조 힌트로 쓴다(H1).
    _normalized, focus = _preprocess(llm_client, agent_input)

    # 노드 3 데이터수집. as_of를 KIS 조회 종료일로 스레딩(kis_mapping §8.2). 실패는 전파.
    ohlcv = run_data_collect(agent_input.ticker, as_of=agent_input.as_of, fetcher=fetcher)
    daily, weekly, monthly = ohlcv["D"], ohlcv["W"], ohlcv["M"]

    # 일봉 빈 데이터 → 안전 착지(data_limited-B).
    if not daily:
        return _unavailable_output(
            agent_input, trace_id, DataStatus.DATA_LIMITED,
            regime=_empty_regime("시세 데이터를 확보하지 못해 국면을 판정하지 않습니다."),
            charts=[],
        )

    # 노드 5 국면분류. 일봉 부족 시 final_regime=unavailable.
    regime_result = run_regime_classify(daily, weekly, monthly)
    if regime_result.final_regime == Regime.UNAVAILABLE:
        return _unavailable_output(
            agent_input, trace_id, DataStatus.REGIME_UNAVAILABLE,
            regime=_to_regime_result(regime_result),
            charts=run_chart_generate(daily, weekly, monthly),
        )

    # 노드 4·6·7·8 (코드 확정 계산).
    bundle = run_indicator_calculate(daily)
    signal_result = run_signal_aggregate(daily)
    confidence = run_confidence_calculate(signal_result, bundle, regime_result)
    risk_items = run_risk_detect(signal_result, bundle, regime_result)

    # 노드 9 차트.
    charts = run_chart_generate(daily, weekly, monthly)

    # 계약 조립 (interpret 호출 전에 RegimeResult·SignalSummary 완성).
    regime = _to_regime_result(regime_result)
    signal_summary = _to_signal_summary(signal_result, confidence)

    # 노드 10 국면해석 + 재생성 루프 + granular fallback.
    result = _interpret(
        llm_client, regime=regime, signal=signal_summary,
        signals=signal_result.technical_signals, risks=risk_items, focus=focus,
    )

    technical_signals = _to_technical_signals(signal_result.technical_signals, result.details)
    data_status = _data_status(regime_result)

    # 선택적 1D intraday: 직접 주입 candles 우선, 없으면 intraday_fetcher로 snapshot 조회(best-effort).
    # C안 gate: fetcher 미주입 + INTRADAY_FETCH_ENABLED=True 일 때만 기본 KIS 분봉 fetcher를 쓴다.
    # 우선순위: intraday_candles > 명시 intraday_fetcher > (flag ON) fetch_minute_ohlcv > off.
    if intraday_fetcher is None and INTRADAY_FETCH_ENABLED:
        intraday_fetcher = fetch_minute_ohlcv
    resolved_intraday = _resolve_intraday(
        intraday_candles, intraday_fetcher, agent_input.ticker, agent_input.as_of,
    )
    intraday_charts, intraday_context = _assemble_intraday(
        resolved_intraday, daily=daily, as_of=agent_input.as_of, final_regime=regime.final_regime,
    )

    return TechnicalAgentOutput(
        request_id=agent_input.request_id,
        ticker=agent_input.ticker,
        as_of=agent_input.as_of,
        source="KIS",
        trace_id=trace_id,
        data_status=data_status,
        regime=regime,
        signal=signal_summary,
        technical_signals=technical_signals,
        risk=RiskSummary(items=list(risk_items)),
        charts=list(charts) + intraday_charts,  # D/W/M 3종 유지 + 1d 조건부 추가
        interpretation=result.interpretation,
        verification=result.verification,
        intraday_context=intraday_context,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 노드 1·2 전처리 (LLM 호출 예외는 fallback으로 흡수, 산출물은 내부 전용)
# ─────────────────────────────────────────────────────────────────────────────
def _preprocess(client: interp.LlmClient, agent_input: TechnicalAgentInput) -> tuple[NormalizeResult, FocusResult]:
    # LlmCallError(LLM 호출 실패)만 흡수 → fallback. 파일 로딩·타입·프로그래밍 오류는 전파(M2).
    try:
        normalized = run_normalize_question(
            client, ticker=agent_input.ticker, query=agent_input.query, as_of=agent_input.as_of)
    except LlmCallError:
        name = BATTERY_TICKERS.get(agent_input.ticker, agent_input.ticker)
        normalized = NormalizeResult(
            f"{name}의 최근 시세와 기술적 신호를 중심으로 현재 차트 국면과 리스크 관찰점을 분석합니다.",
            GenerationSource.TEMPLATE_FALLBACK,
        )
    try:
        focus = run_focus_analysis(
            client, ticker=agent_input.ticker, normalized_question=normalized.normalized_question)
    except LlmCallError:
        focus = FocusResult(list(_DEFAULT_FOCUS), _DEFAULT_FOCUS_SUMMARY, GenerationSource.TEMPLATE_FALLBACK)
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
) -> _Interpretation:
    payload = interp.build_payload(
        regime=regime, signal=signal, signals=signals, risks=risks,
        analysis_focus=focus.analysis_focus, focus_summary=focus.focus_summary,
    )
    # 1차(interpret) + REGEN_MAX_COUNT회 재생성(config.md §9).
    prompt_seq = [interp.INTERPRET_PROMPT] + [interp.REGENERATE_PROMPT] * REGEN_MAX_COUNT
    last: _Attempt | None = None
    for i, name in enumerate(prompt_seq):
        attempt = _attempt(client, name, payload,
                           regime=regime, signal=signal, signals=signals, risks=risks)
        if attempt.call_failed:  # 호출 예외 → 재생성 없이 template fallback(정책 §6-9)
            return _full_fallback(regime, signal, signals, risks, regen_count=i)
        last = attempt
        if attempt.passed:
            source = GenerationSource.LLM if i == 0 else GenerationSource.LLM_REGENERATED
            return _success(attempt, source, signals, regen_count=i)
    # 재생성까지 소진 → 마지막 출력 기준 granular(부분) fallback (H2/REGEN-04).
    return _granular_fallback(last, regime, signal, signals, risks, regen_count=REGEN_MAX_COUNT)


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


def _unavailable_output(
    agent_input: TechnicalAgentInput, trace_id: str, data_status: DataStatus,
    *, regime: RegimeResult, charts: Sequence[ChartPayload],
) -> TechnicalAgentOutput:
    """regime 판단 불가 → signal·risk null, technical_signals=[], interpretation=template fallback."""
    return TechnicalAgentOutput(
        request_id=agent_input.request_id,
        ticker=agent_input.ticker,
        as_of=agent_input.as_of,
        source="KIS",
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
