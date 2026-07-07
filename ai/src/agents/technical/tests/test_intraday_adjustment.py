"""intraday_adjustment 테스트 — fixture 기반(KIS 호출 없음).

compute_intraday_confidence_adjustment / build_intraday_risk_notes / apply_intraday_adjustments 의
cap·부호·volatile 억제·최대 개수·중립 표현을 확인한다. top-level output은 이 파일 범위가 아니다.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.agents.technical.config import (
    INTRADAY_CONFIDENCE_ADJUSTMENT_CAP as CAP,
)
from src.agents.technical.config import (
    INTRADAY_RISK_NOTE_MAX_COUNT,
)
from src.agents.technical.schemas.intraday import IntradayContext
from src.agents.technical.synthesis.intraday_adjustment import (
    apply_intraday_adjustments,
    build_intraday_risk_notes,
    compute_intraday_confidence_adjustment,
)

AS_OF = datetime(2026, 7, 6, 14, 30, 0)
_FORBIDDEN = ["매수", "매도", "추천", "급등", "급락", "목표주가", "손절"]


def _ctx(**kw) -> IntradayContext:
    base = {"status": "normal", "as_of": AS_OF}
    base.update(kw)
    return IntradayContext(**base)


# ── confidence_adjustment: 부호·cap ───────────────────────────────────────────
def test_aligned_positive_max_cap():
    adj = compute_intraday_confidence_adjustment(
        _ctx(regime_alignment="aligned", intraday_regime_hint="upward_intraday"))
    assert adj == pytest.approx(CAP)
    assert adj > 0


def test_counter_negative_max_cap():
    adj = compute_intraday_confidence_adjustment(
        _ctx(regime_alignment="counter", intraday_regime_hint="downward_intraday"))
    assert adj == pytest.approx(-CAP)
    assert adj < 0


@pytest.mark.parametrize("alignment", ["neutral", "unavailable", None])
def test_neutral_or_unavailable_zero(alignment):
    assert compute_intraday_confidence_adjustment(_ctx(regime_alignment=alignment)) == 0.0


def test_volatile_blocks_positive_adjustment():
    # 손으로 aligned + volatile을 구성해도 양수 보정 금지 → 0.0
    adj = compute_intraday_confidence_adjustment(
        _ctx(regime_alignment="aligned", intraday_regime_hint="volatile_intraday"))
    assert adj == 0.0


def test_status_not_normal_zero():
    adj = compute_intraday_confidence_adjustment(
        _ctx(status="data_limited", regime_alignment="aligned", intraday_regime_hint="upward_intraday"))
    assert adj == 0.0


def test_adjustment_within_cap_bounds():
    for alignment in ("aligned", "counter", "neutral", "unavailable"):
        adj = compute_intraday_confidence_adjustment(_ctx(regime_alignment=alignment))
        assert -CAP <= adj <= CAP


# ── risk_notes ────────────────────────────────────────────────────────────────
def test_volume_spike_generates_note():
    notes = build_intraday_risk_notes(_ctx(volume_spike=True))
    assert notes  # 비어있지 않음
    assert any("거래량" in n for n in notes)


def test_counter_generates_note():
    notes = build_intraday_risk_notes(_ctx(regime_alignment="counter"))
    assert notes
    assert any("충돌" in n for n in notes)


def test_status_not_normal_no_notes():
    assert build_intraday_risk_notes(_ctx(status="unavailable", volume_spike=True)) == []


def test_notes_capped_at_max():
    # counter + volatile + spike + 고가근접 → 4개 후보지만 최대 3개로 제한
    notes = build_intraday_risk_notes(_ctx(
        regime_alignment="counter", intraday_regime_hint="volatile_intraday",
        volume_spike=True, day_range_position=0.95,
    ))
    assert len(notes) <= INTRADAY_RISK_NOTE_MAX_COUNT


def test_notes_use_neutral_wording():
    notes = build_intraday_risk_notes(_ctx(
        regime_alignment="counter", intraday_regime_hint="volatile_intraday", volume_spike=True))
    joined = " ".join(notes)
    assert not [w for w in _FORBIDDEN if w in joined], f"금지 표현: {joined}"


# ── apply_intraday_adjustments ────────────────────────────────────────────────
def test_apply_fills_context_and_keeps_signal_score_zero():
    ctx = _ctx(regime_alignment="aligned", intraday_regime_hint="upward_intraday",
               latest_price=101.0, volume_spike=True)
    out = apply_intraday_adjustments(ctx)
    assert out.confidence_adjustment == pytest.approx(CAP)
    assert out.signal_score_adjustment == 0.0  # v1 미조정
    assert any("거래량" in n for n in out.risk_notes)
    # 다른 관측값·hint/alignment는 그대로(final_regime과 무관)
    assert out.latest_price == 101.0
    assert out.intraday_regime_hint == "upward_intraday"
    assert out.regime_alignment == "aligned"


def test_apply_signal_score_adjustment_always_zero():
    for alignment in ("aligned", "counter", "neutral"):
        out = apply_intraday_adjustments(_ctx(regime_alignment=alignment))
        assert out.signal_score_adjustment == 0.0
