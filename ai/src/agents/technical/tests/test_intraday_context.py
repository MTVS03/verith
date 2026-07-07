"""IntradayContext 계약 + TechnicalAgentOutput.intraday_context(optional) 테스트.

계산 로직이 아니라 **계약(필드·기본값·검증)** 만 확인한다. real KIS·네트워크 없음.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agents.technical.config import (
    INTRADAY_CONFIDENCE_ADJUSTMENT_CAP as CAP,
)
from src.agents.technical.config import (
    INTRADAY_RISK_NOTE_MAX_COUNT,
)
from src.agents.technical.schemas.contracts import TechnicalAgentOutput
from src.agents.technical.schemas.enums import (
    AlignmentFlag,
    ConfidenceLevel,
    Consensus,
    DataStatus,
    GenerationSource,
    Regime,
    Trend,
    VerificationOutcome,
)
from src.agents.technical.schemas.intraday import IntradayContext

AS_OF = "2026-07-06T14:30:00"

# 최소 유효 D/W/M output(intraday_context 없이도 통과해야 함) — 필수 필드만.
_BASE_OUTPUT = {
    "request_id": "req_1",
    "ticker": "373220",
    "as_of": "2026-07-06T14:30:00+09:00",
    "source": "KIS",
    "trace_id": "trace_1",
    "data_status": DataStatus.NORMAL.value,
    "regime": {
        "daily_regime": Regime.UPTREND_INTACT.value,
        "final_regime": Regime.UPTREND_INTACT.value,
        "weekly_trend": Trend.UP.value,
        "monthly_trend": Trend.UP.value,
        "alignment_flag": AlignmentFlag.ALIGNED.value,
        "regime_context": "상위 추세와 정합.",
    },
    "signal": {
        "consensus": Consensus.WEAK_POSITIVE.value,
        "signal_score": 0.3,
        "confidence": 0.5,
        "confidence_level": ConfidenceLevel.MEDIUM.value,
        "confidence_basis": "지표 다수 정합.",
    },
    "technical_signals": [],
    "risk": None,
    "charts": [],
    "interpretation": {"text": "참고 정보.", "source": GenerationSource.LLM.value},
    "verification": {
        "calc_passed": True, "regime_passed": True, "label_matched": True,
        "outcome": VerificationOutcome.PASSED.value, "regen_count": 0,
    },
}


# ── output backward-compat ────────────────────────────────────────────────────
def test_output_without_intraday_context_defaults_none():
    out = TechnicalAgentOutput.model_validate(_BASE_OUTPUT)
    assert out.intraday_context is None
    assert "intraday_context" in out.model_dump()  # 직렬화에 키 존재(값 null)


def test_output_with_intraday_context():
    payload = {**_BASE_OUTPUT, "intraday_context": {"status": "normal", "as_of": AS_OF}}
    out = TechnicalAgentOutput.model_validate(payload)
    assert isinstance(out.intraday_context, IntradayContext)
    assert out.intraday_context.status == "normal"
    out.model_dump_json()  # 직렬화 가능


# ── IntradayContext 최소/기본값 ───────────────────────────────────────────────
def test_minimal_context_defaults():
    ctx = IntradayContext(status="unavailable", as_of=AS_OF)
    assert ctx.source == "KIS"
    assert ctx.latest_price is None
    assert ctx.short_ma == [] and ctx.vwap == [] and ctx.rsi == []
    assert ctx.risk_notes == []
    assert ctx.confidence_adjustment == 0.0
    assert ctx.signal_score_adjustment == 0.0
    assert ctx.intraday_regime_hint is None
    assert ctx.regime_alignment is None


def test_status_required():
    with pytest.raises(ValidationError):
        IntradayContext(as_of=AS_OF)  # status 누락


@pytest.mark.parametrize("status", ["bogus", "", "NORMAL"])
def test_status_literal_rejected(status):
    with pytest.raises(ValidationError):
        IntradayContext(status=status, as_of=AS_OF)


@pytest.mark.parametrize(
    "status",
    ["normal", "data_limited", "unavailable", "market_closed", "not_trading_day", "api_error"],
)
def test_all_statuses_accepted(status):
    assert IntradayContext(status=status, as_of=AS_OF).status == status


# ── 수치 검증 ─────────────────────────────────────────────────────────────────
def test_negative_return_pct_allowed_but_negative_price_rejected():
    ctx = IntradayContext(status="normal", as_of=AS_OF, intraday_return_pct=-1.5)
    assert ctx.intraday_return_pct == -1.5
    with pytest.raises(ValidationError):
        IntradayContext(status="normal", as_of=AS_OF, latest_price=-1.0)


@pytest.mark.parametrize("pos", [-0.1, 1.1])
def test_day_range_position_bounds(pos):
    with pytest.raises(ValidationError):
        IntradayContext(status="normal", as_of=AS_OF, day_range_position=pos)


def test_risk_notes_are_strings():
    ctx = IntradayContext(status="normal", as_of=AS_OF, risk_notes=["장중 급등", "거래량 급증"])
    assert ctx.risk_notes == ["장중 급등", "거래량 급증"]


# ── schema bound: confidence/signal_score ±cap, risk_notes ≤ max (config §14 정본) ──
def test_confidence_adjustment_within_cap_ok():
    for v in (CAP, -CAP, 0.0):
        ctx = IntradayContext(status="normal", as_of=AS_OF, confidence_adjustment=v)
        assert ctx.confidence_adjustment == v


@pytest.mark.parametrize("v", [CAP + 0.001, -CAP - 0.001, 99.0, -99.0])
def test_confidence_adjustment_out_of_cap_rejected(v):
    with pytest.raises(ValidationError):
        IntradayContext(status="normal", as_of=AS_OF, confidence_adjustment=v)


def test_signal_score_adjustment_within_cap_ok():
    # B안: v1 구현은 0.0만 생성하지만 계약은 ±cap을 연다(Phase 2 대비).
    for v in (0.0, CAP, -CAP):
        ctx = IntradayContext(status="normal", as_of=AS_OF, signal_score_adjustment=v)
        assert ctx.signal_score_adjustment == v


@pytest.mark.parametrize("v", [CAP + 0.001, -CAP - 0.001, 0.7])
def test_signal_score_adjustment_out_of_cap_rejected(v):
    with pytest.raises(ValidationError):
        IntradayContext(status="normal", as_of=AS_OF, signal_score_adjustment=v)


def test_risk_notes_max_count_ok():
    notes = [f"관찰 {i}" for i in range(INTRADAY_RISK_NOTE_MAX_COUNT)]
    ctx = IntradayContext(status="normal", as_of=AS_OF, risk_notes=notes)
    assert len(ctx.risk_notes) == INTRADAY_RISK_NOTE_MAX_COUNT


def test_risk_notes_over_max_count_rejected():
    notes = [f"관찰 {i}" for i in range(INTRADAY_RISK_NOTE_MAX_COUNT + 1)]
    with pytest.raises(ValidationError):
        IntradayContext(status="normal", as_of=AS_OF, risk_notes=notes)


def test_hint_and_alignment_literals():
    ctx = IntradayContext(
        status="normal", as_of=AS_OF,
        intraday_regime_hint="upward_intraday", regime_alignment="aligned",
        short_ma_trend="up",
    )
    assert ctx.intraday_regime_hint == "upward_intraday"
    assert ctx.regime_alignment == "aligned"
    assert ctx.short_ma_trend == "up"
    with pytest.raises(ValidationError):
        IntradayContext(status="normal", as_of=AS_OF, regime_alignment="sideways")


def test_extra_field_forbidden():
    with pytest.raises(ValidationError):
        IntradayContext(status="normal", as_of=AS_OF, bogus=1)
