"""일봉 국면(daily regime) 결정론 분류.

`regime_rules.md §1`(우선순위 규칙)·§3(보조 판정)의 코드 구현이다. LLM·KIS·DB·Redis를 쓰지 않는다.
입력 일봉 OHLCV로 6단계 indicators를 계산하고, 최신 봉 기준으로 우선순위 if-elif 판정한다.

경계 규칙(regime_rules.md·config.md §2):
  - 극단 국면(overheated / oversold_rebound_watch)을 추세보다 먼저 검사한다.
  - RSI ≤ RSI_OVERSOLD / RSI ≥ RSI_OVERBOUGHT(포함), 상승 계열은 RSI < RSI_OVERBOUGHT(strict).
  - 볼밴 상단 근처는 close ≥ upper × NEAR_BAND_THRESHOLD(포함).

데이터 부족 정책:
  - 일봉 수 < MIN_DAILY_BARS → Regime.UNAVAILABLE.
  - 개별 지표(예: 60MA 5일 기울기)가 계산 불가면 전체를 죽이지 않고 그 조건만 False 처리하며,
    어디에도 안 걸리면 Regime.SIDEWAYS로 착지한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..config import (
    MA_LONG_WINDOW,
    MA_MID_WINDOW,
    MA_SHORT_WINDOW,
    MIN_DAILY_BARS,
    NEAR_BAND_THRESHOLD,
    NEAR_SUPPORT_THRESHOLD_PCT,
    REBOUND_WICK_RATIO,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    SLOPE_LOOKBACK_DAYS,
    SLOPE_MIN,
)
from ..indicators.moving_average import calculate_bollinger_bands, calculate_moving_averages
from ..indicators.pattern import CandleFeatureRow, calculate_candle_features
from ..indicators.rsi import calculate_rsi
from ..indicators.support_resistance import calculate_support_resistance
from ..schemas.enums import Regime
from ..schemas.ohlcv import OHLCV

# 단기/중기/장기 이동평균 창 (config 역할 상수). 규칙의 "20MA" 등은 기본값 기준 표기이며
# 이 역할 창을 가리킨다. mas 접근은 하드코딩 숫자가 아니라 이 상수로만 한다.
_SHORT_MA, _MID_MA, _LONG_MA = MA_SHORT_WINDOW, MA_MID_WINDOW, MA_LONG_WINDOW


def _slope(series: Sequence[float | None], lookback: int) -> float | None:
    """series[-1] − series[-1-lookback] (절대 가격차). 계산 불가면 None."""
    if lookback <= 0 or len(series) <= lookback:
        return None
    latest = series[-1]
    past = series[-1 - lookback]
    if latest is None or past is None:
        return None
    return latest - past


def _is_near_support(close: float, support: float | None) -> bool:
    """지지 근처: |close − support| / support ≤ NEAR_SUPPORT_THRESHOLD_PCT. support None/0이면 False."""
    if support is None or support == 0:
        return False
    return abs(close - support) / support <= NEAR_SUPPORT_THRESHOLD_PCT


def _is_rebound_candle(candle: CandleFeatureRow) -> bool:
    """반등 캔들: 양봉 또는 아랫꼬리 > 몸통 × REBOUND_WICK_RATIO."""
    return candle["is_bullish"] or candle["lower_wick"] > candle["body"] * REBOUND_WICK_RATIO


def _is_near_upper_band(close: float, upper: float | None) -> bool:
    """볼밴 상단 근처: close ≥ upper × NEAR_BAND_THRESHOLD. upper None이면 False."""
    if upper is None:
        return False
    return close >= upper * NEAR_BAND_THRESHOLD


def _rising(slope: float | None) -> bool:
    """우상향: slope > SLOPE_MIN. None이면 False."""
    return slope is not None and slope > SLOPE_MIN


def _falling(slope: float | None) -> bool:
    """하락: slope < 0. None이면 False."""
    return slope is not None and slope < 0


def classify_daily_regime(ohlcv: Sequence[OHLCV]) -> Regime:
    """일봉 OHLCV → daily regime(Regime enum). 우선순위 if-elif로 확정한다."""
    if len(ohlcv) < MIN_DAILY_BARS:
        return Regime.UNAVAILABLE

    mas = calculate_moving_averages(ohlcv)
    bands = calculate_bollinger_bands(ohlcv)
    rsis = calculate_rsi(ohlcv)
    supports = calculate_support_resistance(ohlcv)
    candles = calculate_candle_features(ohlcv)

    close = float(ohlcv[-1].close)
    rsi = rsis[-1]
    ma5, ma20, ma60 = mas[_SHORT_MA][-1], mas[_MID_MA][-1], mas[_LONG_MA][-1]
    upper = bands[-1]["upper"]
    support = supports[-1]["support"]
    candle = candles[-1]

    slope20 = _slope(mas[_MID_MA], SLOPE_LOOKBACK_DAYS)
    slope60 = _slope(mas[_LONG_MA], SLOPE_LOOKBACK_DAYS)
    prev_slope20 = _slope(mas[_MID_MA][:-1], SLOPE_LOOKBACK_DAYS)  # 한 봉 전 중기MA 기울기

    # 파생 조건 (None-safe)
    perfect_order = None not in (ma5, ma20, ma60) and ma5 > ma20 > ma60      # 정배열
    inverse_order = None not in (ma5, ma20, ma60) and ma5 < ma20 < ma60      # 역배열
    above_ma20 = ma20 is not None and close > ma20
    below_ma20 = ma20 is not None and close < ma20
    ma5_above_ma20 = None not in (ma5, ma20) and ma5 > ma20
    turned_up = _rising(slope20) and (prev_slope20 is not None and prev_slope20 <= SLOPE_MIN)
    rsi_below_overbought = rsi is not None and rsi < RSI_OVERBOUGHT

    # 1. oversold_rebound_watch (극단 우선)
    if rsi is not None and rsi <= RSI_OVERSOLD and _is_near_support(close, support) \
            and _is_rebound_candle(candle):
        return Regime.OVERSOLD_REBOUND_WATCH

    # 2. 과열 (극단 우선)
    if rsi is not None and rsi >= RSI_OVERBOUGHT and _is_near_upper_band(close, upper):
        return Regime.OVERHEATED

    # 3. 상승 전환 관찰 (정배열 완성 전, 기울기 음→양 전환)
    if above_ma20 and ma5_above_ma20 and turned_up and rsi_below_overbought:
        return Regime.BULLISH_REVERSAL_WATCH

    # 4. 상승 추세 유지 (정배열 완성 + 20·60MA 우상향)
    if above_ma20 and perfect_order and _rising(slope20) and _rising(slope60) \
            and rsi_below_overbought:
        return Regime.UPTREND_INTACT

    # 5. 하락 추세
    if below_ma20 and inverse_order and _falling(slope20):
        return Regime.DOWNTREND

    # 6. 기본값
    return Regime.SIDEWAYS
