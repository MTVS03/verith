"""멀티프레임 trend·alignment 단위테스트 (검증 ②, test_plan.md §4.2).

trend 산출은 compute_trend로, alignment/context는 _alignment_and_context로 직접 검증한다.
final_regime 배선은 analyze_multiframe로 확인한다. KIS/Redis/DB/LLM 미호출.
"""

from __future__ import annotations

from src.agents.technical.config import MIN_MONTHLY_BARS, MIN_WEEKLY_BARS
from src.agents.technical.regime.multiframe import (
    MultiframeRegimeResult,
    _alignment_and_context,
    analyze_multiframe,
    compute_trend,
)
from src.agents.technical.schemas.enums import AlignmentFlag, Regime, Trend
from src.agents.technical.schemas.ohlcv import OHLCV

POSITIVE = Regime.UPTREND_INTACT
NEGATIVE = Regime.DOWNTREND
NEUTRAL_REGIME = Regime.OVERHEATED


def bars_from_closes(closes: list[float]) -> list[OHLCV]:
    return [OHLCV(date="2026-01-01", open=c, high=c, low=c, close=c, volume=1, trading_value=1)
            for c in closes]


def closes_with(n: int, past_close: float, last_close: float) -> list[float]:
    """길이 n, 뒤에서 5번째(-5=TREND_SLOPE_LOOKBACK 기준)와 마지막 종가를 지정."""
    closes = [100.0] * n
    closes[-5] = past_close
    closes[-1] = last_close
    return closes


# ── compute_trend ─────────────────────────────────────────────────────────────
def test_weekly_insufficient_bars_unavailable():
    assert compute_trend(bars_from_closes([100.0] * (MIN_WEEKLY_BARS - 1)), MIN_WEEKLY_BARS) == Trend.UNAVAILABLE


def test_monthly_insufficient_bars_unavailable():
    assert compute_trend(bars_from_closes([100.0] * (MIN_MONTHLY_BARS - 1)), MIN_MONTHLY_BARS) == Trend.UNAVAILABLE


def test_trend_up_when_above_threshold():
    bars = bars_from_closes(closes_with(13, past_close=100.0, last_close=102.0))  # +2% > 1%
    assert compute_trend(bars, MIN_WEEKLY_BARS) == Trend.UP


def test_trend_down_when_below_threshold():
    bars = bars_from_closes(closes_with(13, past_close=100.0, last_close=98.0))  # -2% < -1%
    assert compute_trend(bars, MIN_WEEKLY_BARS) == Trend.DOWN


def test_trend_sideways_within_band():
    bars = bars_from_closes(closes_with(13, past_close=100.0, last_close=100.5))  # +0.5% 이내
    assert compute_trend(bars, MIN_WEEKLY_BARS) == Trend.SIDEWAYS


def test_trend_unavailable_when_past_close_zero():
    bars = bars_from_closes(closes_with(13, past_close=0.0, last_close=100.0))
    assert compute_trend(bars, MIN_WEEKLY_BARS) == Trend.UNAVAILABLE


# ── final_regime ──────────────────────────────────────────────────────────────
def test_final_regime_equals_daily_regime():
    weekly = bars_from_closes([100.0] * 13)
    monthly = bars_from_closes([100.0] * 8)
    result = analyze_multiframe(POSITIVE, weekly, monthly)
    assert isinstance(result, MultiframeRegimeResult)
    assert result.final_regime == result.daily_regime == POSITIVE


# ── alignment_flag ────────────────────────────────────────────────────────────
def test_neutral_regime_is_always_neutral():
    for monthly in (Trend.UP, Trend.DOWN):
        flag, _ = _alignment_and_context(NEUTRAL_REGIME, Trend.UP, monthly)
        assert flag == AlignmentFlag.NEUTRAL


def test_positive_with_up_is_aligned():
    flag, _ = _alignment_and_context(POSITIVE, Trend.SIDEWAYS, Trend.UP)
    assert flag == AlignmentFlag.ALIGNED


def test_positive_with_down_is_counter_trend():
    flag, _ = _alignment_and_context(POSITIVE, Trend.UP, Trend.DOWN)
    assert flag == AlignmentFlag.COUNTER_TREND


def test_negative_with_down_is_aligned():
    flag, _ = _alignment_and_context(NEGATIVE, Trend.UP, Trend.DOWN)
    assert flag == AlignmentFlag.ALIGNED


def test_negative_with_up_is_counter_trend():
    flag, _ = _alignment_and_context(NEGATIVE, Trend.DOWN, Trend.UP)
    assert flag == AlignmentFlag.COUNTER_TREND


def test_monthly_unavailable_uses_weekly():
    flag, context = _alignment_and_context(POSITIVE, Trend.UP, Trend.UNAVAILABLE)
    assert flag == AlignmentFlag.ALIGNED
    assert "주봉" in context


def test_both_unavailable_is_neutral():
    flag, _ = _alignment_and_context(POSITIVE, Trend.UNAVAILABLE, Trend.UNAVAILABLE)
    assert flag == AlignmentFlag.NEUTRAL


def test_reference_sideways_is_neutral():
    flag, _ = _alignment_and_context(POSITIVE, Trend.UP, Trend.SIDEWAYS)
    assert flag == AlignmentFlag.NEUTRAL


def test_monthly_priority_over_weekly_on_conflict():
    # 월봉 down(우선) + 주봉 up → 긍정 regime은 counter_trend, 주봉 엇갈림 맥락 포함
    flag, context = _alignment_and_context(POSITIVE, Trend.UP, Trend.DOWN)
    assert flag == AlignmentFlag.COUNTER_TREND
    assert "주봉" in context and "엇갈" in context


# ── regime_context ────────────────────────────────────────────────────────────
def test_regime_context_not_empty_and_no_buy_sell():
    forbidden = ["매수", "매도", "사라", "팔아", "손절", "목표가"]
    cases = [
        (NEUTRAL_REGIME, Trend.UP, Trend.UP),
        (POSITIVE, Trend.SIDEWAYS, Trend.UP),
        (POSITIVE, Trend.UP, Trend.DOWN),
        (NEGATIVE, Trend.UP, Trend.DOWN),
        (POSITIVE, Trend.UP, Trend.UNAVAILABLE),
        (POSITIVE, Trend.UNAVAILABLE, Trend.UNAVAILABLE),
        (POSITIVE, Trend.UP, Trend.SIDEWAYS),
    ]
    for daily, weekly, monthly in cases:
        _, context = _alignment_and_context(daily, weekly, monthly)
        assert context.strip(), f"빈 context: {(daily, weekly, monthly)}"
        assert not [w for w in forbidden if w in context], f"금지 표현: {context}"
