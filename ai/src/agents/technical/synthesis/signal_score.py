"""지표별 signal 산출 + signal_score 가중집계 + consensus 라벨링.

정본: `config.md §4.1`(지표별 signal 규칙)·§4.2(집계·consensus). LLM·KIS·DB·Redis 미사용.
투자 권유 표현을 쓰지 않는다.

경계(technical_coding_guidelines): 판정(signal)·수치(value·metrics)·가중치(weight)는 코드가 확정한다.
설명 문장(detail)은 LLM(노드10) 몫이므로 여기서 만들지 않는다 — `contracts.TechnicalSignal`을
직접 조립하지 않고 중간 dataclass(IndicatorSignalResult)를 반환한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..config import (
    INDICATOR_WEIGHTS,
    MA_LONG_WINDOW,
    MA_MID_WINDOW,
    MA_SHORT_WINDOW,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    RSI_PERIOD,
    SIGNAL_STRONG,
    SIGNAL_WEAK,
    NEAR_RESISTANCE_THRESHOLD_PCT,
    NEAR_SUPPORT_THRESHOLD_PCT,
)
from ..indicators.moving_average import calculate_moving_averages
from ..indicators.pattern import CandleFeatureRow, calculate_candle_features
from ..indicators.rsi import calculate_rsi
from ..indicators.support_resistance import calculate_support_resistance
from ..indicators.volume import calculate_volume_ratio
from ..schemas.enums import Consensus, IndicatorType, Signal
from ..schemas.ohlcv import OHLCV

_SIGNAL_ENCODING = {Signal.POSITIVE: 1, Signal.NEUTRAL: 0, Signal.NEGATIVE: -1}


@dataclass(frozen=True)
class IndicatorSignalResult:
    """지표 하나의 코드 확정 결과. detail·detail_source는 LLM 단계 몫이라 포함하지 않는다."""
    indicator: IndicatorType
    signal: Signal
    value: float | None
    metrics: list[str]
    weight: float


@dataclass(frozen=True)
class SignalScoreResult:
    technical_signals: list[IndicatorSignalResult]  # active(제외되지 않은) 지표만
    signal_score: float
    consensus: Consensus


# ─────────────────────────────────────────────────────────────────────────────
# 지표별 signal 산출 (config.md §4.1). None = 계산 불가로 제외(excluded).
# ─────────────────────────────────────────────────────────────────────────────
def moving_average_signal(close: float, ma5: float | None, ma20: float | None) -> Signal | None:
    if ma5 is None or ma20 is None:
        return None  # 핵심 입력 없음 → 제외
    if close > ma20 and ma5 > ma20:
        return Signal.POSITIVE
    if close < ma20 and ma5 < ma20:
        return Signal.NEGATIVE
    return Signal.NEUTRAL


def rsi_signal(rsi: float | None) -> Signal | None:
    if rsi is None:
        return None  # 제외
    if rsi >= RSI_OVERBOUGHT or rsi <= RSI_OVERSOLD or rsi == 50:
        return Signal.NEUTRAL  # 극단/중앙은 방향 불명확 → neutral (regime/risk가 다룸)
    if 50 < rsi < RSI_OVERBOUGHT:
        return Signal.POSITIVE
    return Signal.NEGATIVE  # RSI_OVERSOLD < rsi < 50


def volume_signal(prev_close: float | None, latest_close: float, volume_ratio: float | None) -> Signal:
    """거래량은 독립 방향이 아니라 가격 방향을 확인. 확인 약하면(ratio<1/불가) neutral."""
    if volume_ratio is None or volume_ratio < 1 or prev_close is None:
        return Signal.NEUTRAL
    if latest_close > prev_close:
        return Signal.POSITIVE
    if latest_close < prev_close:
        return Signal.NEGATIVE
    return Signal.NEUTRAL


def support_resistance_signal(close: float, support: float | None, resistance: float | None) -> Signal | None:
    if support is None and resistance is None:
        return None  # 제외
    if support is not None and support != 0 and abs(close - support) / support <= NEAR_SUPPORT_THRESHOLD_PCT:
        return Signal.POSITIVE  # 지지 근처
    if resistance is not None and resistance != 0 and abs(close - resistance) / resistance <= NEAR_RESISTANCE_THRESHOLD_PCT:
        return Signal.NEGATIVE  # 저항 근처
    return Signal.NEUTRAL


def pattern_signal(candle: CandleFeatureRow) -> Signal:
    if candle["is_bullish"]:
        return Signal.POSITIVE
    if candle["is_bearish"]:
        return Signal.NEGATIVE
    return Signal.NEUTRAL  # 도지


# ─────────────────────────────────────────────────────────────────────────────
# 집계
# ─────────────────────────────────────────────────────────────────────────────
def classify_consensus(signal_score: float) -> Consensus:
    """signal_score → consensus (경계값 포함, config.md §4.2)."""
    if signal_score >= SIGNAL_STRONG:
        return Consensus.STRONG_POSITIVE
    if signal_score >= SIGNAL_WEAK:
        return Consensus.WEAK_POSITIVE
    if signal_score <= -SIGNAL_STRONG:
        return Consensus.STRONG_NEGATIVE
    if signal_score <= -SIGNAL_WEAK:
        return Consensus.WEAK_NEGATIVE
    return Consensus.NEUTRAL


def aggregate_signal_score(results: Sequence[IndicatorSignalResult]) -> tuple[float, Consensus]:
    """active 지표들의 가중합/재정규화 → (signal_score, consensus). active 없으면 (0.0, neutral)."""
    total_weight = sum(r.weight for r in results)
    if total_weight == 0:
        return 0.0, Consensus.NEUTRAL
    score = sum(r.weight * _SIGNAL_ENCODING[r.signal] for r in results) / total_weight
    return score, classify_consensus(score)


def compute_signal_score(daily_ohlcv: Sequence[OHLCV]) -> SignalScoreResult:
    """일봉 OHLCV → 지표별 signal + signal_score + consensus. 제외 지표는 재정규화로 처리."""
    if not daily_ohlcv:
        return SignalScoreResult([], 0.0, Consensus.NEUTRAL)

    mas = calculate_moving_averages(daily_ohlcv)
    rsis = calculate_rsi(daily_ohlcv)
    ratios = calculate_volume_ratio(daily_ohlcv)
    supports = calculate_support_resistance(daily_ohlcv)
    candles = calculate_candle_features(daily_ohlcv)

    close = float(daily_ohlcv[-1].close)
    prev_close = float(daily_ohlcv[-2].close) if len(daily_ohlcv) >= 2 else None
    ma_short, ma_mid, ma_long = mas[MA_SHORT_WINDOW][-1], mas[MA_MID_WINDOW][-1], mas[MA_LONG_WINDOW][-1]
    rsi = rsis[-1]
    ratio = ratios[-1]
    support, resistance = supports[-1]["support"], supports[-1]["resistance"]
    candle = candles[-1]

    results: list[IndicatorSignalResult] = []

    ma_sig = moving_average_signal(close, ma_short, ma_mid)
    if ma_sig is not None:
        metrics = [f"{MA_SHORT_WINDOW}MA {ma_short:.1f}", f"{MA_MID_WINDOW}MA {ma_mid:.1f}"]
        if ma_long is not None:
            metrics.append(f"{MA_LONG_WINDOW}MA {ma_long:.1f}")
        results.append(_row(IndicatorType.MOVING_AVERAGE, ma_sig, close, metrics))

    rsi_sig = rsi_signal(rsi)
    if rsi_sig is not None:
        results.append(_row(IndicatorType.RSI, rsi_sig, rsi,
                            [f"RSI({RSI_PERIOD}) {rsi:.1f}", f"기준 {RSI_OVERSOLD}/{RSI_OVERBOUGHT}"]))

    vol_sig = volume_signal(prev_close, close, ratio)
    vol_metrics = [f"거래량비 {ratio:.2f}"] if ratio is not None else []
    results.append(_row(IndicatorType.VOLUME, vol_sig, ratio, vol_metrics))

    sr_sig = support_resistance_signal(close, support, resistance)
    if sr_sig is not None:
        sr_metrics = []
        if support is not None:
            sr_metrics.append(f"지지 {support:.1f}")
        if resistance is not None:
            sr_metrics.append(f"저항 {resistance:.1f}")
        results.append(_row(IndicatorType.SUPPORT_RESISTANCE, sr_sig, close, sr_metrics))

    pat_sig = pattern_signal(candle)
    results.append(_row(IndicatorType.PATTERN, pat_sig, candle["body"],
                        [f"몸통 {candle['body']:.1f}", f"아랫꼬리 {candle['lower_wick']:.1f}"]))

    score, consensus = aggregate_signal_score(results)
    return SignalScoreResult(results, score, consensus)


def _row(indicator: IndicatorType, signal: Signal, value: float | None,
         metrics: list[str]) -> IndicatorSignalResult:
    return IndicatorSignalResult(
        indicator=indicator, signal=signal, value=value, metrics=metrics,
        weight=INDICATOR_WEIGHTS[indicator.value],
    )
