"""contracts 검증 강화 테스트 (Phase A). source Literal·수치 범위 검증."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agents.technical.schemas.contracts import (
    SignalSummary,
    TechnicalAgentOutput,
    TechnicalSignal,
)

BASE_OUTPUT = {
    "request_id": "req_1", "ticker": "373220", "as_of": "2026-06-30T14:30:00+09:00",
    "source": "KIS", "trace_id": "trace_1", "data_status": "normal",
    "regime": {"daily_regime": "sideways", "final_regime": "sideways", "weekly_trend": "up",
               "monthly_trend": "up", "alignment_flag": "neutral", "regime_context": "x"},
    "signal": None, "technical_signals": [], "risk": None, "charts": [],
    "interpretation": {"text": "x", "source": "template_fallback"},
    "verification": {"calc_passed": True, "regime_passed": True, "label_matched": True,
                     "outcome": "passed", "regen_count": 0},
}


# ── 최상위 source Literal ─────────────────────────────────────────────────────
@pytest.mark.parametrize("source", ["KIS", "KIS (stale)"])
def test_source_allows_market_data_labels(source):
    out = TechnicalAgentOutput.model_validate({**BASE_OUTPUT, "source": source})
    assert out.source == source


@pytest.mark.parametrize("bad_source", ["llm", "kis", "OpenAI", ""])
def test_source_rejects_non_market_data(bad_source):
    with pytest.raises(ValidationError):
        TechnicalAgentOutput.model_validate({**BASE_OUTPUT, "source": bad_source})


# ── signal_score / confidence 범위 ────────────────────────────────────────────
def _signal(**over):
    base = {"consensus": "neutral", "signal_score": 0.0, "confidence": 0.5,
            "confidence_level": "medium", "confidence_basis": "x"}
    return {**base, **over}


@pytest.mark.parametrize("score", [-1.0, 0.0, 1.0])
def test_signal_score_in_range_ok(score):
    assert SignalSummary.model_validate(_signal(signal_score=score)).signal_score == score


@pytest.mark.parametrize("score", [-1.01, 1.5])
def test_signal_score_out_of_range_rejected(score):
    with pytest.raises(ValidationError):
        SignalSummary.model_validate(_signal(signal_score=score))


@pytest.mark.parametrize("conf", [-0.1, 1.1])
def test_confidence_out_of_range_rejected(conf):
    with pytest.raises(ValidationError):
        SignalSummary.model_validate(_signal(confidence=conf))


# ── weight 범위 ───────────────────────────────────────────────────────────────
def _tsignal(weight):
    return {"indicator": "rsi", "signal": "neutral", "value": 58.2, "metrics": [],
            "detail": "", "detail_source": "llm", "weight": weight}


def test_weight_in_range_ok():
    assert TechnicalSignal.model_validate(_tsignal(0.3)).weight == 0.3


@pytest.mark.parametrize("weight", [-0.1, 1.5])
def test_weight_out_of_range_rejected(weight):
    with pytest.raises(ValidationError):
        TechnicalSignal.model_validate(_tsignal(weight))


def test_value_not_range_limited():
    # value는 지표별 값이라 범위 제한이 없어야 한다 (큰 값 허용)
    assert TechnicalSignal.model_validate(_tsignal(0.3) | {"value": 141122636250.0}).value == 141122636250.0
