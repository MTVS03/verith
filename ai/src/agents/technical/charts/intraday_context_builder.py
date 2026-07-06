"""IntradayContext 생성 helper — 순수 계산(chart_annotation_spec §3.1, Beta).

입력은 **이미 정규화된** `list[IntradayCandle]`(+`previous_close`·`as_of`)이다. KIS 호출·재조회 없음.
`intraday_chart_builder.py`와 같은 성격(candles → intraday 파생, 순수 함수)이라 charts/에 co-locate한다.

이번 커밋 범위(계산): status·latest·return_pct·day_high/low·range_position·short_ma(+trend)·
cumulative_volume·volume_spike·vwap. 다음은 **의도적으로 미계산**(후속 Phase):
  - intraday_regime_hint / regime_alignment → None (판단 힌트는 다음 커밋)
  - confidence_adjustment / signal_score_adjustment → 0.0 (실제 보정 없음)
  - risk_notes → 빈 리스트 (본격 risk 문구는 후속)
  - rsi → 빈 리스트 (v1 미계산)
final_regime·signal_score·confidence 는 이 함수와 무관하다(보조 컨텍스트만 생성).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from ..schemas.intraday import (
    IntradayCandle,
    IntradayContext,
    IntradayPoint,
    IntradayStatus,
)
from .intraday_chart_builder import DEFAULT_INTRADAY_SHORT_MA_WINDOW

# 분봉 거래량 급증 판정 배수(직전 봉 평균 × 배수). 정식 config화는 후속(config.md).
DEFAULT_INTRADAY_VOLUME_SPIKE_MULTIPLIER = 2.0


def build_intraday_context(
    candles: Sequence[IntradayCandle],
    *,
    previous_close: float | None = None,
    as_of: datetime,
    interval: str = "1min",
    status: IntradayStatus | None = None,
    short_ma_window: int = DEFAULT_INTRADAY_SHORT_MA_WINDOW,
    volume_spike_multiplier: float = DEFAULT_INTRADAY_VOLUME_SPIKE_MULTIPLIER,
    latest_price: float | None = None,
    cumulative_volume: int | None = None,
    cumulative_trading_value: int | None = None,
) -> IntradayContext:
    """`list[IntradayCandle]` → IntradayContext(관측 컨테이너). KIS 호출·재계산 없음.

    latest_price·cumulative_volume·cumulative_trading_value는 KIS output1 정본값(fetcher metadata)을
    **우선**하고, 없으면 candle 기반 fallback(마지막 close·분봉 volume 합)으로 채운다(kis_mapping §12.5).
    day_high/low·range_position·short_ma·vwap·latest_timestamp는 candle 기준을 유지한다.
    candles가 비면 status=(인자 status 또는 "unavailable")로 latest 값 없이 안전 생성한다.
    값을 만들 수 없으면 0으로 강제하지 않고 None으로 둔다(honest scoping).
    """
    candles = list(candles)
    if not candles:
        return IntradayContext(
            status=status or "unavailable",
            as_of=as_of,
            previous_close=previous_close,
            latest_price=latest_price,
            cumulative_volume=cumulative_volume,
            cumulative_trading_value=cumulative_trading_value,
        )

    latest = candles[-1]
    day_high = max(c.high for c in candles)
    day_low = min(c.low for c in candles)
    short_ma = _sma_points(candles, short_ma_window)
    # output1 정본 우선, 없으면 candle fallback.
    eff_latest = latest_price if latest_price is not None else latest.close
    eff_cum_vol = cumulative_volume if cumulative_volume is not None else sum(c.volume for c in candles)

    return IntradayContext(
        status=status or "normal",
        as_of=as_of,
        interval=interval,
        latest_timestamp=latest.timestamp,  # 시각은 candle 기준
        latest_price=eff_latest,
        previous_close=previous_close,
        intraday_return_pct=_return_pct(eff_latest, previous_close),  # latest_price와 동일 기준
        day_high=day_high,
        day_low=day_low,
        day_range_position=_range_position(latest.close, day_high, day_low),  # candle 기준 유지
        short_ma=short_ma,
        short_ma_trend=_ma_trend(short_ma),
        cumulative_volume=eff_cum_vol,
        cumulative_trading_value=cumulative_trading_value,  # candle 합산 불가 — metadata만(없으면 None)
        volume_spike=_volume_spike(candles, volume_spike_multiplier),
        vwap=_vwap_points(candles),
        # 아래는 이번 커밋 미계산(후속 Phase) — 스키마 기본값 유지.
        rsi=[],
        intraday_regime_hint=None,
        regime_alignment=None,
        confidence_adjustment=0.0,
        signal_score_adjustment=0.0,
        risk_notes=[],
    )


def _return_pct(latest_close: float, previous_close: float | None) -> float | None:
    """전일 종가 대비 등락률(%). previous_close 없거나 0이면 None."""
    if previous_close is None or previous_close == 0:
        return None
    return (latest_close - previous_close) / previous_close * 100


def _range_position(latest_close: float, day_high: float, day_low: float) -> float | None:
    """당일 레인지 내 현재가 위치(0=저가, 1=고가). 레인지가 0이면 판정 불가 → None."""
    span = day_high - day_low
    if span <= 0:
        return None
    pos = (latest_close - day_low) / span
    return min(1.0, max(0.0, pos))  # 안전 clamp (0~1)


def _sma_points(candles: list[IntradayCandle], window: int) -> list[IntradayPoint]:
    """close 단순이동평균(window 봉). 확보분부터 각 시각에 1점."""
    if window <= 0 or len(candles) < window:
        return []
    points: list[IntradayPoint] = []
    for i in range(window - 1, len(candles)):
        avg = sum(c.close for c in candles[i - window + 1 : i + 1]) / window
        points.append(IntradayPoint(timestamp=candles[i].timestamp, value=avg))
    return points


def _ma_trend(short_ma: list[IntradayPoint]) -> str | None:
    """마지막 두 MA 점의 방향(up/down/flat). 2점 미만이면 None."""
    if len(short_ma) < 2:
        return None
    last, prev = short_ma[-1].value, short_ma[-2].value
    if last > prev:
        return "up"
    if last < prev:
        return "down"
    return "flat"


def _volume_spike(candles: list[IntradayCandle], multiplier: float) -> bool | None:
    """최신 봉 거래량이 직전 봉 평균 × 배수 이상인가. 직전 봉이 없으면 None."""
    if len(candles) < 2:
        return None
    prior = candles[:-1]
    avg_prior = sum(c.volume for c in prior) / len(prior)
    if avg_prior <= 0:
        return None
    return candles[-1].volume >= multiplier * avg_prior


def _vwap_points(candles: list[IntradayCandle]) -> list[IntradayPoint]:
    """누적 VWAP 시리즈. typical=(H+L+C)/3, 누적(Σtp·vol)/(Σvol). 누적 거래량 0 구간은 건너뜀."""
    points: list[IntradayPoint] = []
    cum_pv = 0.0
    cum_v = 0
    for c in candles:
        typical = (c.high + c.low + c.close) / 3
        cum_pv += typical * c.volume
        cum_v += c.volume
        if cum_v > 0:
            points.append(IntradayPoint(timestamp=c.timestamp, value=cum_pv / cum_v))
    return points
