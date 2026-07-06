"""intraday_alignment 테스트 — fixture 기반(KIS 호출 없음).

infer_intraday_regime_hint / classify_regime_alignment / apply_intraday_hint_to_context 의
보수적 판정과, 방향 매핑이 정본(regime/multiframe)과 동기화됨을 확인한다.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.agents.technical import config
from src.agents.technical.regime.multiframe import (
    _NEGATIVE_REGIMES,
    _POSITIVE_REGIMES,
)
from src.agents.technical.schemas.enums import Regime
from src.agents.technical.schemas.intraday import IntradayContext
from src.agents.technical.synthesis import intraday_alignment
from src.agents.technical.synthesis.intraday_alignment import (
    _BEARISH_REGIMES,
    _BULLISH_REGIMES,
    apply_intraday_hint_to_context,
    classify_regime_alignment,
    infer_intraday_regime_hint,
)


def test_alignment_thresholds_come_from_config():
    # 판정 임계값 정본은 config.py §14 — alignment 모듈이 그 값을 그대로 참조해야 한다(중앙화 회귀).
    assert intraday_alignment.INTRADAY_VOLATILITY_RETURN_THRESHOLD is config.INTRADAY_VOLATILITY_RETURN_THRESHOLD
    assert intraday_alignment.INTRADAY_VOLATILITY_RANGE_THRESHOLD is config.INTRADAY_VOLATILITY_RANGE_THRESHOLD
    assert intraday_alignment.INTRADAY_DIRECTION_RETURN_THRESHOLD is config.INTRADAY_DIRECTION_RETURN_THRESHOLD
    assert intraday_alignment.INTRADAY_HIGH_RANGE_POSITION_THRESHOLD is config.INTRADAY_HIGH_RANGE_POSITION_THRESHOLD
    assert intraday_alignment.INTRADAY_LOW_RANGE_POSITION_THRESHOLD is config.INTRADAY_LOW_RANGE_POSITION_THRESHOLD
    assert intraday_alignment.INTRADAY_DIRECTION_MIN_AGREEMENT == config.INTRADAY_DIRECTION_MIN_AGREEMENT

AS_OF = datetime(2026, 7, 6, 14, 30, 0)


def _ctx(**kw) -> IntradayContext:
    """방향 판정에 필요한 값을 기본 채운 normal 컨텍스트(개별 필드만 override)."""
    base = {
        "status": "normal", "as_of": AS_OF,
        "previous_close": 100.0, "day_high": 102.0, "day_low": 99.0,
        "intraday_return_pct": 0.0, "short_ma_trend": "flat", "day_range_position": 0.5,
    }
    base.update(kw)
    return IntradayContext(**base)


# ── hint: unavailable ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("status", ["unavailable", "data_limited", "market_closed", "api_error"])
def test_hint_unavailable_when_status_not_normal(status):
    assert infer_intraday_regime_hint(_ctx(status=status)) == "unavailable"


@pytest.mark.parametrize("missing", ["intraday_return_pct", "short_ma_trend", "day_range_position"])
def test_hint_unavailable_when_key_value_missing(missing):
    assert infer_intraday_regime_hint(_ctx(**{missing: None})) == "unavailable"


# ── hint: 방향 ────────────────────────────────────────────────────────────────
def test_hint_upward_when_multiple_agree():
    # return +1.0%, trend up, pos 0.8 → 3표 상방
    ctx = _ctx(intraday_return_pct=1.0, short_ma_trend="up", day_range_position=0.8)
    assert infer_intraday_regime_hint(ctx) == "upward_intraday"


def test_hint_downward_when_multiple_agree():
    ctx = _ctx(intraday_return_pct=-1.0, short_ma_trend="down", day_range_position=0.2)
    assert infer_intraday_regime_hint(ctx) == "downward_intraday"


def test_hint_sideways_when_single_signal_only():
    # trend up 하나뿐(ret 0.0, pos 0.5 중립) → 1표 < 2 합의 → sideways
    ctx = _ctx(intraday_return_pct=0.0, short_ma_trend="up", day_range_position=0.5)
    assert infer_intraday_regime_hint(ctx) == "sideways_intraday"


def test_hint_sideways_when_conflicting():
    # ret + / trend down → 상쇄 → sideways
    ctx = _ctx(intraday_return_pct=1.0, short_ma_trend="down", day_range_position=0.5)
    assert infer_intraday_regime_hint(ctx) == "sideways_intraday"


# ── hint: volatile ────────────────────────────────────────────────────────────
def test_hint_volatile_by_strong_return():
    ctx = _ctx(intraday_return_pct=4.0, short_ma_trend="up", day_range_position=0.9)
    assert infer_intraday_regime_hint(ctx) == "volatile_intraday"


def test_hint_volatile_by_wide_range():
    # 레인지 (108-100)/100 = 8% ≥ 5% → volatile (등락률은 작게)
    ctx = _ctx(intraday_return_pct=0.2, day_high=108.0, day_low=100.0,
               previous_close=100.0, short_ma_trend="flat", day_range_position=0.5)
    assert infer_intraday_regime_hint(ctx) == "volatile_intraday"


# ── alignment ─────────────────────────────────────────────────────────────────
def test_alignment_upward_bullish_regime_aligned():
    assert classify_regime_alignment(Regime.UPTREND_INTACT, "upward_intraday") == "aligned"


def test_alignment_upward_bearish_regime_counter():
    assert classify_regime_alignment(Regime.DOWNTREND, "upward_intraday") == "counter"


def test_alignment_downward_bearish_regime_aligned():
    assert classify_regime_alignment(Regime.DOWNTREND, "downward_intraday") == "aligned"


def test_alignment_downward_bullish_regime_counter():
    assert classify_regime_alignment(Regime.UPTREND_INTACT, "downward_intraday") == "counter"


@pytest.mark.parametrize("hint", ["sideways_intraday", "volatile_intraday"])
def test_alignment_neutral_for_sideways_or_volatile(hint):
    assert classify_regime_alignment(Regime.UPTREND_INTACT, hint) == "neutral"


@pytest.mark.parametrize("regime", [Regime.OVERHEATED, Regime.OVERSOLD_REBOUND_WATCH, Regime.SIDEWAYS])
def test_alignment_neutral_for_ambiguous_regime(regime):
    assert classify_regime_alignment(regime, "upward_intraday") == "neutral"


def test_alignment_unavailable_when_regime_unavailable():
    assert classify_regime_alignment(Regime.UNAVAILABLE, "upward_intraday") == "unavailable"


def test_alignment_unavailable_when_hint_unavailable():
    assert classify_regime_alignment(Regime.UPTREND_INTACT, "unavailable") == "unavailable"


# ── apply: 조립 + final_regime 불변 ───────────────────────────────────────────
def test_apply_sets_hint_and_alignment_without_touching_regime():
    ctx = _ctx(intraday_return_pct=1.0, short_ma_trend="up", day_range_position=0.8)
    final_regime = Regime.UPTREND_INTACT
    out = apply_intraday_hint_to_context(ctx, final_regime)
    assert out.intraday_regime_hint == "upward_intraday"
    assert out.regime_alignment == "aligned"
    # final_regime 인자는 그대로(불변), 보정값도 손대지 않음
    assert final_regime is Regime.UPTREND_INTACT
    assert out.confidence_adjustment == 0.0
    assert out.signal_score_adjustment == 0.0
    # 원본 관측값은 유지
    assert out.latest_price == ctx.latest_price
    assert out.day_high == ctx.day_high


# ── 정본 동기화 가드(drift 방지) ──────────────────────────────────────────────
def test_direction_sets_match_canonical_multiframe():
    assert _BULLISH_REGIMES == _POSITIVE_REGIMES
    assert _BEARISH_REGIMES == _NEGATIVE_REGIMES
