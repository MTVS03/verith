"""노드 4 — 지표계산. daily OHLCV → IndicatorBundle(최신 지표 스칼라 묶음).

얇은 어댑터: `indicators/*` 모듈만 호출하고 계산식을 재구현하지 않는다.

역할 한정(implementation_plan.md §3): 이 번들은 후속 노드의 공유 캐시가 아니다. `regime`·
`signal_aggregate`·`chart_generate`는 OHLCV에서 지표를 각자 내부 재계산한다(self-contained).
IndicatorBundle은 **confidence_calculate·risk_detect가 소비하는 최신 지표 스칼라**만 담는다.

IndicatorBundle은 최종 계약 모델이 아니므로 `schemas/`가 아니라 이 노드 안에 둔다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..indicators.moving_average import calculate_moving_averages
from ..indicators.pattern import CandleFeatureRow, calculate_candle_features
from ..indicators.rsi import calculate_rsi
from ..indicators.support_resistance import calculate_support_resistance
from ..indicators.volume import (
    calculate_trading_value_average,
    calculate_volume_average,
    calculate_volume_ratio,
)
from ..schemas.ohlcv import OHLCV


@dataclass(frozen=True)
class IndicatorBundle:
    """일봉 최신 봉 기준 지표 스칼라. confidence(volume_ratio)·risk(전부)가 소비한다.

    계산 불가한 값은 각 indicator 모듈 정책대로 None(창 미충족 등). 노드가 임의 보정하지 않는다.
    """
    close: float
    prev_close: float | None
    ma5: float | None
    ma20: float | None
    ma60: float | None
    rsi: float | None
    volume_ratio: float | None
    support: float | None
    resistance: float | None
    avg_volume: float | None
    avg_trading_value: float | None
    latest_candle: CandleFeatureRow


def run_indicator_calculate(daily: Sequence[OHLCV]) -> IndicatorBundle:
    """daily OHLCV에서 최신 봉 기준 지표 스칼라 번들을 만든다. 빈 입력은 명시적 예외."""
    if not daily:
        raise ValueError("daily OHLCV is required for indicator_calculate")

    mas = calculate_moving_averages(daily)
    rsis = calculate_rsi(daily)
    ratios = calculate_volume_ratio(daily)
    sr = calculate_support_resistance(daily)
    vol_avg = calculate_volume_average(daily)
    tv_avg = calculate_trading_value_average(daily)
    candles = calculate_candle_features(daily)

    return IndicatorBundle(
        close=float(daily[-1].close),
        prev_close=float(daily[-2].close) if len(daily) >= 2 else None,
        ma5=mas[5][-1],
        ma20=mas[20][-1],
        ma60=mas[60][-1],
        rsi=rsis[-1],
        volume_ratio=ratios[-1],
        support=sr[-1]["support"],
        resistance=sr[-1]["resistance"],
        avg_volume=vol_avg[-1],
        avg_trading_value=tv_avg[-1],
        latest_candle=candles[-1],
    )
