"""intraday_context_builder 테스트 — fixture 기반(KIS 호출 없음).

build_intraday_context가 list[IntradayCandle]에서 IntradayContext를 순수 계산으로 채우는지 확인한다.
계산 대상(latest·return_pct·day range·short_ma·volume_spike·vwap)과 미계산(hint/alignment·보정)을 함께 본다.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.agents.technical.charts.intraday_context_builder import build_intraday_context
from src.agents.technical.schemas.intraday import IntradayCandle

AS_OF = datetime(2026, 7, 6, 14, 30, 0)


def _candle(minute: int, close: float, *, high: float | None = None,
            low: float | None = None, volume: int = 100) -> IntradayCandle:
    return IntradayCandle(
        timestamp=f"2026-07-06T09:{minute:02d}:00",
        open=close, high=high if high is not None else close + 1,
        low=low if low is not None else close - 1, close=close,
        volume=volume, interval="1min",
    )


def _candles(closes: list[float]) -> list[IntradayCandle]:
    return [_candle(i + 1, c) for i, c in enumerate(closes)]


# ── 빈 candles ────────────────────────────────────────────────────────────────
def test_empty_candles_unavailable_default():
    ctx = build_intraday_context([], previous_close=99.0, as_of=AS_OF)
    assert ctx.status == "unavailable"
    assert ctx.latest_timestamp is None
    assert ctx.latest_price is None
    assert ctx.previous_close == 99.0
    assert ctx.day_high is None and ctx.day_low is None
    assert ctx.short_ma == [] and ctx.vwap == []


def test_empty_candles_explicit_status():
    ctx = build_intraday_context([], previous_close=None, as_of=AS_OF, status="market_closed")
    assert ctx.status == "market_closed"


# ── latest ────────────────────────────────────────────────────────────────────
def test_latest_from_last_candle():
    ctx = build_intraday_context(_candles([100, 101, 102]), previous_close=99.0, as_of=AS_OF)
    assert ctx.status == "normal"
    assert ctx.latest_price == 102
    assert ctx.latest_timestamp == "2026-07-06T09:03:00"
    assert ctx.interval == "1min"


# ── intraday_return_pct ───────────────────────────────────────────────────────
def test_return_pct_from_previous_close():
    ctx = build_intraday_context(_candles([100, 105]), previous_close=100.0, as_of=AS_OF)
    assert ctx.intraday_return_pct == pytest.approx(5.0)


def test_return_pct_negative():
    ctx = build_intraday_context(_candles([100, 95]), previous_close=100.0, as_of=AS_OF)
    assert ctx.intraday_return_pct == pytest.approx(-5.0)


def test_return_pct_none_without_previous_close():
    ctx = build_intraday_context(_candles([100, 105]), previous_close=None, as_of=AS_OF)
    assert ctx.intraday_return_pct is None


# ── day_high / day_low / range_position ───────────────────────────────────────
def test_day_high_low_and_range_position():
    candles = [
        _candle(1, 100, high=102, low=95),
        _candle(2, 101, high=105, low=99),
        _candle(3, 100, high=104, low=98),  # latest close=100
    ]
    ctx = build_intraday_context(candles, previous_close=99.0, as_of=AS_OF)
    assert ctx.day_high == 105
    assert ctx.day_low == 95
    # (100 - 95) / (105 - 95) = 0.5
    assert ctx.day_range_position == pytest.approx(0.5)


def test_range_position_none_when_flat():
    candles = [_candle(1, 100, high=100, low=100), _candle(2, 100, high=100, low=100)]
    ctx = build_intraday_context(candles, previous_close=100.0, as_of=AS_OF)
    assert ctx.day_range_position is None


# ── cumulative_volume ─────────────────────────────────────────────────────────
def test_cumulative_volume():
    candles = [_candle(1, 100, volume=100), _candle(2, 101, volume=250), _candle(3, 102, volume=50)]
    ctx = build_intraday_context(candles, previous_close=99.0, as_of=AS_OF)
    assert ctx.cumulative_volume == 400


# ── short_ma + trend ──────────────────────────────────────────────────────────
def test_short_ma_and_trend_up():
    ctx = build_intraday_context(_candles([1, 2, 3, 4, 5, 6]), previous_close=1.0, as_of=AS_OF)
    ma = ctx.short_ma
    assert [p.value for p in ma] == [3.0, 4.0]  # window=5
    assert ctx.short_ma_trend == "up"


def test_short_ma_trend_none_when_single_point():
    ctx = build_intraday_context(_candles([1, 2, 3, 4, 5]), previous_close=1.0, as_of=AS_OF)
    assert len(ctx.short_ma) == 1
    assert ctx.short_ma_trend is None


# ── volume_spike ──────────────────────────────────────────────────────────────
def test_volume_spike_true():
    candles = [_candle(1, 100, volume=100), _candle(2, 101, volume=100),
               _candle(3, 102, volume=100), _candle(4, 103, volume=500)]
    ctx = build_intraday_context(candles, previous_close=99.0, as_of=AS_OF)
    assert ctx.volume_spike is True  # 500 >= 2.0 * 100


def test_volume_spike_false():
    candles = [_candle(1, 100, volume=100), _candle(2, 101, volume=100),
               _candle(3, 102, volume=120)]
    ctx = build_intraday_context(candles, previous_close=99.0, as_of=AS_OF)
    assert ctx.volume_spike is False  # 120 < 2.0 * 100


def test_volume_spike_none_single_candle():
    ctx = build_intraday_context(_candles([100]), previous_close=99.0, as_of=AS_OF)
    assert ctx.volume_spike is None


# ── vwap ──────────────────────────────────────────────────────────────────────
def test_vwap_computed():
    ctx = build_intraday_context(_candles([100, 101, 102]), previous_close=99.0, as_of=AS_OF)
    assert len(ctx.vwap) == 3
    assert all(p.value > 0 for p in ctx.vwap)
    assert ctx.vwap[0].timestamp == "2026-07-06T09:01:00"


# ── 미계산 항목(이번 커밋) ────────────────────────────────────────────────────
def test_hint_alignment_adjustments_defaults():
    ctx = build_intraday_context(_candles([100, 101, 102]), previous_close=99.0, as_of=AS_OF)
    assert ctx.intraday_regime_hint is None
    assert ctx.regime_alignment is None
    assert ctx.confidence_adjustment == 0.0
    assert ctx.signal_score_adjustment == 0.0
    assert ctx.risk_notes == []
    assert ctx.rsi == []


# ── 순수 함수(결정론) ─────────────────────────────────────────────────────────
def test_deterministic_pure_helper():
    candles = _candles([100, 101, 102])
    a = build_intraday_context(candles, previous_close=99.0, as_of=AS_OF)
    b = build_intraday_context(candles, previous_close=99.0, as_of=AS_OF)
    assert a.model_dump() == b.model_dump()  # final_regime 등 외부 상태와 무관
