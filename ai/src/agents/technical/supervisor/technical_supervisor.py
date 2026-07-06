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

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from ..config import BATTERY_TICKERS, REGEN_MAX_COUNT
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
from ..services.kis_client import fetch_multi_timeframe_ohlcv
from ..synthesis.confidence import ConfidenceResult
from ..synthesis.intraday_alignment import apply_intraday_hint_to_context
from ..synthesis.signal_score import IndicatorSignalResult, SignalScoreResult

OhlcvFetcher = Callable[[str], dict[str, Sequence[OHLCV]]]

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
) -> TechnicalAgentOutput:
    """TechnicalAgentInput → 1~10 노드 조율 → TechnicalAgentOutput.

    intraday_candles(선택)가 주어지면 1d 장중 차트·intraday_context를 조건부로 붙인다(KIS 호출 아님 —
    이미 주어진 분봉만 사용). 없으면 기존 D/W/M 출력과 완전히 동일하다.
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

    # 선택적 1D intraday 조립(입력 있을 때만). 실패는 흡수 — D/W/M 출력은 그대로 유지.
    intraday_charts, intraday_context = _assemble_intraday(
        intraday_candles, daily=daily, as_of=agent_input.as_of, final_regime=regime.final_regime,
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


def _assemble_intraday(
    intraday_candles: Sequence[IntradayCandle] | None,
    *,
    daily: Sequence[OHLCV],
    as_of: datetime,
    final_regime: Regime,
) -> tuple[list[ChartPayload], IntradayContext | None]:
    """선택적 1D intraday 조립. 이미 만든 builder/helper만 호출하고 KIS는 부르지 않는다.

    candles가 없으면 `([], None)` — D/W/M 출력과 완전히 동일하게 동작한다.
    previous_close는 최근 일봉 종가에서 파생한다(정식 전일 종가 판정은 fetcher 도입 시 정교화).
    intraday 조립 중 어떤 예외든 흡수해 D/W/M 출력이 통째로 실패하지 않게 한다.
    final_regime은 읽기만 하며 절대 바꾸지 않는다(보정도 하지 않음).
    """
    if not intraday_candles:
        return [], None
    try:
        previous_close = daily[-1].close if daily else None
        payload = build_intraday_chart_payload(intraday_candles, previous_close=previous_close)
        context = build_intraday_context(
            intraday_candles, previous_close=previous_close, as_of=as_of,
        )
        context = apply_intraday_hint_to_context(context, final_regime)
        return [payload], context
    except Exception:  # noqa: BLE001 - intraday 실패가 D/W/M 전체를 깨지 않도록 흡수
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
