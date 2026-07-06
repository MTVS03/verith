"""intraday_chart_builder 테스트 — fixture 기반(KIS 호출 없음).

build_intraday_chart_payload가 list[IntradayCandle]에서 1d ChartPayload를 만들고,
day_high/low·short_ma·previous_close를 계약대로 채우는지 확인한다. real KIS·네트워크 없음.
"""

from __future__ import annotations

from src.agents.technical.charts.intraday_chart_builder import (
    DEFAULT_INTRADAY_SHORT_MA_WINDOW,
    build_intraday_chart_payload,
)
from src.agents.technical.schemas.enums import ChartPeriod
from src.agents.technical.schemas.intraday import IntradayCandle, IntradayChartData


def _candle(minute: int, close: float, *, high: float | None = None, low: float | None = None) -> IntradayCandle:
    return IntradayCandle(
        timestamp=f"2026-07-06T09:{minute:02d}:00",
        open=close, high=high if high is not None else close + 1,
        low=low if low is not None else close - 1, close=close,
        volume=100 + minute, interval="1min",
    )


def _candles(closes: list[float]) -> list[IntradayCandle]:
    return [_candle(i + 1, c) for i, c in enumerate(closes)]


# ── payload 기본 형태 ─────────────────────────────────────────────────────────
def test_payload_period_and_candle_unit():
    payload = build_intraday_chart_payload(_candles([100, 101, 102]), previous_close=99.0)
    assert payload.period is ChartPeriod.ONE_DAY
    assert isinstance(payload.chart_data, IntradayChartData)
    assert payload.chart_data.candle_unit == "1min"
    assert payload.chart_data.previous_close == 99.0


def test_candles_pass_through_not_recalculated():
    src = _candles([100, 101, 102])
    payload = build_intraday_chart_payload(src)
    assert [c.timestamp for c in payload.chart_data.candles] == [c.timestamp for c in src]
    assert [c.close for c in payload.chart_data.candles] == [100, 101, 102]
    assert all(c.interval == "1min" for c in payload.chart_data.candles)


# ── day_high / day_low ────────────────────────────────────────────────────────
def test_day_high_low_from_candles():
    candles = [
        _candle(1, 100, high=105, low=98),
        _candle(2, 101, high=110, low=99),
        _candle(3, 102, high=108, low=95),
    ]
    cd = build_intraday_chart_payload(candles).chart_data
    assert cd.day_high == 110
    assert cd.day_low == 95


# ── short_ma ──────────────────────────────────────────────────────────────────
def test_short_ma_simple_moving_average():
    # window=5 기본. close 1..6 → 마지막 두 점만(5봉 확보) 생성.
    payload = build_intraday_chart_payload(_candles([1, 2, 3, 4, 5, 6]))
    ma = payload.chart_data.short_ma
    assert len(ma) == 2  # index 4(1..5), index 5(2..6)
    assert ma[0].value == 3.0   # (1+2+3+4+5)/5
    assert ma[1].value == 4.0   # (2+3+4+5+6)/5
    assert ma[0].timestamp == payload.chart_data.candles[4].timestamp


def test_short_ma_empty_when_not_enough_candles():
    payload = build_intraday_chart_payload(_candles([100, 101]))  # 2봉 < window 5
    assert payload.chart_data.short_ma == []


def test_custom_short_ma_window():
    payload = build_intraday_chart_payload(_candles([10, 20, 30]), short_ma_window=3)
    assert len(payload.chart_data.short_ma) == 1
    assert payload.chart_data.short_ma[0].value == 20.0  # (10+20+30)/3


# ── 빈 candles 안전 처리 ──────────────────────────────────────────────────────
def test_empty_candles_safe():
    payload = build_intraday_chart_payload([], previous_close=99.0)
    cd = payload.chart_data
    assert cd.candles == []
    assert cd.day_high is None
    assert cd.day_low is None
    assert cd.short_ma == []
    assert cd.previous_close == 99.0


# ── VWAP/RSI 는 이번 범위 미계산(빈 배열) ─────────────────────────────────────
def test_vwap_rsi_not_populated():
    payload = build_intraday_chart_payload(_candles([100, 101, 102, 103, 104, 105]))
    assert payload.chart_data.vwap == []
    assert payload.chart_data.rsi == []


def test_default_window_constant():
    assert DEFAULT_INTRADAY_SHORT_MA_WINDOW == 5
