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


# ── ChartData 계약 검증 (chart_payload contract) ──────────────────────────────
from src.agents.technical.schemas.chart import ChartData, SupportResistanceOverlay  # noqa: E402
from src.agents.technical.schemas.contracts import ChartPayload  # noqa: E402

VALID_CHART_DATA = {
    "candle_unit": "D",
    "candles": [{"date": "2026-07-03", "open": 100, "high": 110, "low": 95,
                 "close": 105, "volume": 12345, "trading_value": 9876543210}],
    "overlays": {
        "moving_average": [{"window": 5, "points": [{"date": "2026-07-03", "value": 103.5}]}],
        "support_resistance": [{"type": "support", "price": 95.0, "from": "2026-06-01",
                                "to": "2026-07-03", "touch_count": 3}],
    },
    "subcharts": {
        "rsi": {"period": 14, "overbought": 70, "oversold": 35,
                "points": [{"date": "2026-07-03", "value": 58.2}]},
        "volume": {"avg_window": 20, "bars": [{"date": "2026-07-03", "volume": 12345,
                                               "avg_volume": 10000.0, "is_spike": False}]},
    },
    "annotations": [{"id": "ann_001", "kind": "golden_cross", "date": "2026-05-14",
                     "price": 83200.0, "label": "골든크로스", "importance": "medium",
                     "source": "code", "meta": {}}],
}


def test_valid_chart_data_validates():
    ChartData.model_validate(VALID_CHART_DATA)


def test_chart_payload_parses_dict_into_chartdata():
    p = ChartPayload(period="1y", chart_data=VALID_CHART_DATA)
    assert isinstance(p.chart_data, ChartData)


def test_wrong_chart_data_rejected():
    with pytest.raises(ValidationError):
        ChartPayload(period="1y", chart_data={"hello": "wrong"})


def test_chart_data_top_level_extra_rejected():
    with pytest.raises(ValidationError):
        ChartData.model_validate({**VALID_CHART_DATA, "unexpected": 1})


def test_chart_data_nested_extra_rejected():
    bad = {**VALID_CHART_DATA,
           "annotations": [{**VALID_CHART_DATA["annotations"][0], "bogus": 1}]}
    with pytest.raises(ValidationError):
        ChartData.model_validate(bad)


@pytest.mark.parametrize("unit", ["Y", "d", "1d", ""])
def test_candle_unit_literal_rejected(unit):
    with pytest.raises(ValidationError):
        ChartData.model_validate({**VALID_CHART_DATA, "candle_unit": unit})


def test_sr_type_literal_rejected():
    bad = {**VALID_CHART_DATA, "overlays": {**VALID_CHART_DATA["overlays"],
           "support_resistance": [{"type": "floor", "price": 1.0, "from": "2026-01-01",
                                   "to": "2026-01-02", "touch_count": 2}]}}
    with pytest.raises(ValidationError):
        ChartData.model_validate(bad)


def _with_annotation(**over):
    ann = {**VALID_CHART_DATA["annotations"][0], **over}
    return {**VALID_CHART_DATA, "annotations": [ann]}


def test_annotation_source_literal_rejected():
    with pytest.raises(ValidationError):
        ChartData.model_validate(_with_annotation(source="llm"))


def test_annotation_importance_literal_rejected():
    with pytest.raises(ValidationError):
        ChartData.model_validate(_with_annotation(importance="urgent"))


@pytest.mark.parametrize("kind", [
    "golden_cross", "dead_cross", "volume_spike", "support_touch", "resistance_touch",
    "rsi_overbought", "rsi_oversold", "box_range_candidate",
    "box_breakout_candidate", "cup_handle_candidate",   # 후속 kind도 계약상 허용
])
def test_all_ten_kinds_allowed(kind):
    ChartData.model_validate(_with_annotation(kind=kind))


def test_unknown_kind_rejected():
    with pytest.raises(ValidationError):
        ChartData.model_validate(_with_annotation(kind="macd_cross"))


# 숫자 범위
def test_negative_price_rejected():
    bad = {**VALID_CHART_DATA, "candles": [{**VALID_CHART_DATA["candles"][0], "open": -1}]}
    with pytest.raises(ValidationError):
        ChartData.model_validate(bad)


def test_negative_volume_rejected():
    bad = {**VALID_CHART_DATA, "candles": [{**VALID_CHART_DATA["candles"][0], "volume": -5}]}
    with pytest.raises(ValidationError):
        ChartData.model_validate(bad)


def test_negative_touch_count_rejected():
    bad = {**VALID_CHART_DATA, "overlays": {**VALID_CHART_DATA["overlays"],
           "support_resistance": [{"type": "support", "price": 1.0, "from": "2026-01-01",
                                   "to": "2026-01-02", "touch_count": -1}]}}
    with pytest.raises(ValidationError):
        ChartData.model_validate(bad)


@pytest.mark.parametrize("rsi_value", [-1, 150])
def test_rsi_value_out_of_range_rejected(rsi_value):
    bad = {**VALID_CHART_DATA, "subcharts": {**VALID_CHART_DATA["subcharts"],
           "rsi": {"period": 14, "overbought": 70, "oversold": 35,
                   "points": [{"date": "2026-07-03", "value": rsi_value}]}}}
    with pytest.raises(ValidationError):
        ChartData.model_validate(bad)


@pytest.mark.parametrize("field,bad", [("window", 0), ("window", -5)])
def test_ma_window_must_be_positive(field, bad):
    b = {**VALID_CHART_DATA, "overlays": {**VALID_CHART_DATA["overlays"],
         "moving_average": [{"window": bad, "points": []}]}}
    with pytest.raises(ValidationError):
        ChartData.model_validate(b)


def test_rsi_period_and_avg_window_must_be_positive():
    b1 = {**VALID_CHART_DATA, "subcharts": {**VALID_CHART_DATA["subcharts"],
          "rsi": {"period": 0, "overbought": 70, "oversold": 35, "points": []}}}
    b2 = {**VALID_CHART_DATA, "subcharts": {**VALID_CHART_DATA["subcharts"],
          "volume": {"avg_window": 0, "bars": []}}}
    with pytest.raises(ValidationError):
        ChartData.model_validate(b1)
    with pytest.raises(ValidationError):
        ChartData.model_validate(b2)


# from alias: 입력·출력 모두 "from" 유지, "from_" 미노출
def test_sr_from_alias_default_dump():
    o = SupportResistanceOverlay.model_validate(
        {"type": "support", "price": 1.0, "from": "2026-01-01", "to": "2026-01-02", "touch_count": 2})
    d = o.model_dump(mode="json")               # by_alias 없이도
    assert "from" in d and "from_" not in d


def test_sr_from_alias_by_alias_dump():
    o = SupportResistanceOverlay.model_validate(
        {"type": "support", "price": 1.0, "from": "2026-01-01", "to": "2026-01-02", "touch_count": 2})
    d = o.model_dump(mode="json", by_alias=True)
    assert "from" in d and "from_" not in d


def test_sr_from_name_input_rejected():
    # populate_by_name 미적용 → 필드명 'from_' 입력은 거부(계약상 "from"만 허용)
    with pytest.raises(ValidationError):
        SupportResistanceOverlay.model_validate(
            {"type": "support", "price": 1.0, "from_": "2026-01-01", "to": "2026-01-02", "touch_count": 2})


def test_nested_from_preserved_in_full_dump():
    p = ChartPayload(period="1y", chart_data=VALID_CHART_DATA)
    dumped = p.model_dump(mode="json")          # by_alias 없이 중첩까지
    assert "from" in dumped["chart_data"]["overlays"]["support_resistance"][0]
    assert "from_" not in dumped["chart_data"]["overlays"]["support_resistance"][0]


def test_chart_data_json_roundtrip_matches():
    p = ChartPayload(period="1y", chart_data=VALID_CHART_DATA)
    assert p.chart_data.model_dump(mode="json", by_alias=True) == VALID_CHART_DATA


# ── 계약 강화 (inf/nan · ISO date · source 필수 · 관계 검증) ──────────────────
from math import inf, nan  # noqa: E402

from src.agents.technical.schemas.chart import (  # noqa: E402
    ChartAnnotation,
    MaPoint,
    RsiPoint,
    RsiSubchart,
    VolumeBar,
)
from src.agents.technical.schemas.ohlcv import OHLCV  # noqa: E402


# inf/nan 거부 (chart/OHLCV float 필드)
def test_ohlcv_rejects_infinity():
    with pytest.raises(ValidationError):
        OHLCV(date="2026-07-03", open=inf, high=inf, low=1, close=1, volume=1, trading_value=1)


def test_mapoint_rejects_infinity():
    with pytest.raises(ValidationError):
        MaPoint(date="2026-07-03", value=inf)


def test_rsipoint_rejects_nan():
    with pytest.raises(ValidationError):
        RsiPoint(date="2026-07-03", value=nan)


def test_sr_price_rejects_infinity():
    with pytest.raises(ValidationError):
        SupportResistanceOverlay.model_validate(
            {"type": "support", "price": inf, "from": "2026-01-01", "to": "2026-01-02", "touch_count": 2})


def test_annotation_price_rejects_infinity():
    with pytest.raises(ValidationError):
        ChartAnnotation.model_validate(
            {"id": "a", "kind": "golden_cross", "date": "2026-07-03", "price": inf,
             "label": "x", "importance": "low", "source": "code"})


def test_volumebar_avg_volume_rejects_infinity():
    with pytest.raises(ValidationError):
        VolumeBar(date="2026-07-03", volume=1, avg_volume=inf, is_spike=False)


def test_infinity_not_silently_dumped_as_null():
    # inf가 검증을 통과해 model_dump_json에서 null로 둔갑하는 일이 없어야 함
    with pytest.raises(ValidationError):
        ChartData.model_validate({**VALID_CHART_DATA,
                                  "candles": [{**VALID_CHART_DATA["candles"][0], "high": inf}]})


# ISO date 검증
@pytest.mark.parametrize("bad", ["not-a-date", "2026-13-01", "2026-02-31", "20260704", "2026/07/04"])
def test_annotation_date_must_be_iso(bad):
    with pytest.raises(ValidationError):
        ChartAnnotation.model_validate(
            {"id": "a", "kind": "golden_cross", "date": bad, "label": "x",
             "importance": "low", "source": "code"})


def test_ohlcv_date_must_be_iso():
    with pytest.raises(ValidationError):
        OHLCV(date="20260704", open=1, high=1, low=1, close=1, volume=1, trading_value=1)


def test_sr_from_to_must_be_iso():
    with pytest.raises(ValidationError):
        SupportResistanceOverlay.model_validate(
            {"type": "support", "price": 1.0, "from": "2026/01/01", "to": "2026-01-02", "touch_count": 2})


# source 필수화
def test_annotation_source_required():
    with pytest.raises(ValidationError):
        ChartAnnotation.model_validate(
            {"id": "a", "kind": "golden_cross", "date": "2026-07-03", "label": "x", "importance": "low"})


def test_annotation_source_code_ok():
    a = ChartAnnotation.model_validate(
        {"id": "a", "kind": "golden_cross", "date": "2026-07-03", "label": "x",
         "importance": "low", "source": "code"})
    assert a.source == "code"


# OHLCV high >= low
def test_ohlcv_high_ge_low_ok():
    OHLCV(date="2026-07-03", open=100, high=110, low=95, close=105, volume=1, trading_value=1)


def test_ohlcv_high_lt_low_rejected():
    with pytest.raises(ValidationError):
        OHLCV(date="2026-07-03", open=100, high=90, low=95, close=92, volume=1, trading_value=1)


# RSI oversold < overbought
def test_rsi_oversold_lt_overbought_ok():
    RsiSubchart(period=14, overbought=70, oversold=35, points=[])


@pytest.mark.parametrize("oversold,overbought", [(70, 35), (50, 50)])
def test_rsi_oversold_ge_overbought_rejected(oversold, overbought):
    with pytest.raises(ValidationError):
        RsiSubchart(period=14, overbought=overbought, oversold=oversold, points=[])


# ChartPayload period ↔ candle_unit 정합
@pytest.mark.parametrize("period,unit", [("3m", "D"), ("1y", "D"), ("5y", "W")])
def test_period_candle_unit_consistent_ok(period, unit):
    ChartPayload(period=period, chart_data={**VALID_CHART_DATA, "candle_unit": unit})


@pytest.mark.parametrize("period,unit", [("5y", "D"), ("3m", "W"), ("1y", "M")])
def test_period_candle_unit_mismatch_rejected(period, unit):
    with pytest.raises(ValidationError):
        ChartPayload(period=period, chart_data={**VALID_CHART_DATA, "candle_unit": unit})
