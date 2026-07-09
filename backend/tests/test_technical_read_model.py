"""technical read model projection 단위 테스트 (순수 — DB 없음).

build_read_model 이 raw output_payload + canonical stock 를 프론트 친화 shape 로 정리하는지,
구조화 섹션/역호환(구버전 payload)/canonical 우선/verification·chart·signal 블록을 검증한다.
"""

from __future__ import annotations

from uuid import uuid4

from db.models.common.stock import Stock
from src.api.schemas.ai_technical_output import MirrorInterpretation
from src.api.services.technical_report_service import build_read_model

_RID = uuid4()


def _raw(**over) -> dict:
    base = {
        "request_id": "req-1", "ticker": "373220", "as_of": "2026-07-09T00:00:00+00:00",
        "source": "KIS", "trace_id": "trace-1", "data_status": "normal",
        "regime": {
            "final_regime": "uptrend_intact", "daily_regime": "uptrend_intact",
            "weekly_trend": "up", "monthly_trend": "up", "alignment_flag": "aligned",
            "regime_context": "상승 추세.",
        },
        "signal": {"consensus": "weak_positive", "signal_score": 0.3, "confidence": 0.42,
                   "confidence_basis": "엇갈림"},
        "technical_signals": [
            {"indicator": "moving_average", "signal": "positive", "value": 82900.0,
             "metrics": ["5MA 82900"], "detail": "이동평균 긍정", "detail_source": "llm"},
        ],
        "risk": {"items": [{"flag": "volume_not_confirmed", "note": "거래량 약함", "ref_price": None}]},
        "charts": [
            {"period": "3m", "chart_data": {"candle_unit": "D", "annotations": [{"kind": "x"}]}},
            {"period": "1y", "chart_data": {"candle_unit": "D", "annotations": []}},
        ],
        "interpretation": {
            "text": "종합 해석.", "source": "llm",
            "one_line_summary": "과열·약한 긍정", "directional_bias": "bullish",
            "trend_interpretation": "추세 해석", "signal_interpretation": "신호 해석",
            "risk_interpretation": "리스크 해석", "timeframe_alignment": "정합",
            "key_drivers": ["이동평균 긍정"], "warning_points": ["거래량 약함"],
            "what_to_watch_next": "거래량", "invalidation_or_caution": "추세 전환 시 무효",
        },
        "verification": {"calc_passed": True, "regime_passed": True, "label_matched": True,
                         "outcome": "passed", "regen_count": 0},
    }
    base.update(over)
    return base


def test_projection_full_sections():
    rm = build_read_model(report_id=_RID, raw=_raw(), stock=None)
    assert rm.summary.one_line_summary == "과열·약한 긍정"
    assert rm.summary.directional_bias == "bullish"
    assert rm.summary.final_regime == "uptrend_intact" and rm.summary.timeframe_alignment == "정합"
    assert rm.interpretation.trend_interpretation == "추세 해석"
    assert rm.interpretation.invalidation_or_caution == "추세 전환 시 무효"
    assert rm.drivers.key_drivers == ["이동평균 긍정"] and rm.drivers.warning_points == ["거래량 약함"]
    assert rm.signals.items[0].indicator == "moving_average" and rm.signals.items[0].value == 82900.0
    assert rm.risks.items[0].flag == "volume_not_confirmed"
    assert rm.charts.available_periods == ["3m", "1y"]
    assert rm.charts.items[0].candle_unit == "D" and rm.charts.items[0].annotation_count == 1
    assert rm.charts.items[0].has_chart_data is True
    assert rm.verification.outcome == "passed" and rm.verification.regen_count == 0
    assert rm.meta.source == "KIS" and rm.meta.trace_id == "trace-1"


def test_projection_canonical_stock_priority():
    # canonical stocks 값이 payload 보다 우선한다.
    stock = Stock(stock_code="373220", stock_name="LG에너지솔루션", market="KOSPI")
    rm = build_read_model(report_id=_RID, raw=_raw(stock_name="구舊이름"), stock=stock)
    assert rm.stock.stock_code == "373220"
    assert rm.stock.stock_name == "LG에너지솔루션" and rm.stock.market == "KOSPI"


def test_projection_backward_compat_no_sections():
    # 구버전 payload(구조화 섹션 없음)에서도 shape 안정 — 섹션 필드는 None/빈 배열.
    raw = _raw(interpretation={"text": "옛 해석.", "source": "llm"})
    rm = build_read_model(report_id=_RID, raw=raw, stock=None)
    assert rm.interpretation.text == "옛 해석."
    assert rm.summary.one_line_summary is None and rm.summary.directional_bias is None
    assert rm.drivers.key_drivers == [] and rm.drivers.warning_points == []
    # 계산/저장 기반 필드는 여전히 채워진다.
    assert rm.summary.final_regime == "uptrend_intact"
    assert rm.verification.outcome == "passed"


def test_projection_tolerates_partial_payload():
    # 부분/이종 payload(빈 dict)에서도 예외 없이 안정 shape.
    rm = build_read_model(report_id=_RID, raw={}, stock=None)
    assert rm.signals.items == [] and rm.risks.items == [] and rm.charts.items == []
    assert rm.summary.final_regime is None and rm.verification.outcome is None


def test_mirror_sections_dict_none_when_empty():
    empty = MirrorInterpretation(text="t", source="llm")
    assert empty.sections_dict() is None                       # 구버전 → None(sections 컬럼 NULL)
    full = MirrorInterpretation(text="t", source="llm", one_line_summary="s",
                                key_drivers=["a"])
    d = full.sections_dict()
    assert d is not None and d["one_line_summary"] == "s" and d["key_drivers"] == ["a"]


# ── trace summary projection ─────────────────────────────────────────────────
def test_trace_summary_normal_path():
    ts = build_read_model(report_id=_RID, raw=_raw(), stock=None).trace_summary
    assert ts.trace_id == "trace-1"
    assert ts.generation_path.source == "KIS"
    assert ts.generation_path.interpretation_source == "llm"
    assert ts.generation_path.template_fallback_used is False
    assert ts.generation_path.path_label == "normal"
    assert ts.data_quality.data_status == "normal" and ts.data_quality.limited is False
    assert ts.data_quality.available_periods == ["3m", "1y"] and ts.data_quality.chart_count == 2
    assert ts.verification_summary.outcome == "passed"
    assert ts.verification_summary.failed_indicators_count == 0
    assert ts.stability.verification_consistent is True
    assert ts.flags.used_fallback is False and ts.flags.had_regeneration is False
    assert ts.flags.verification_warning is False
    assert ts.flags.has_daily_chart is True and ts.flags.has_weekly_chart is False


def test_trace_summary_template_fallback_path():
    raw = _raw(
        interpretation={"text": "폴백.", "source": "template_fallback"},
        verification={"calc_passed": True, "regime_passed": True, "label_matched": False,
                      "outcome": "template_fallback", "regen_count": 1},
    )
    ts = build_read_model(report_id=_RID, raw=raw, stock=None).trace_summary
    assert ts.generation_path.path_label == "template_fallback"
    assert ts.generation_path.template_fallback_used is True
    assert ts.flags.used_fallback is True
    assert ts.flags.had_regeneration is True                    # regen_count=1
    assert ts.flags.verification_warning is True                # outcome!=passed & label_matched False
    assert ts.stability.verification_consistent is False


def test_trace_summary_regenerated_path():
    raw = _raw(
        interpretation={"text": "재생성.", "source": "llm_regenerated"},
        verification={"calc_passed": True, "regime_passed": True, "label_matched": True,
                      "outcome": "passed", "regen_count": 1},
    )
    ts = build_read_model(report_id=_RID, raw=raw, stock=None).trace_summary
    assert ts.generation_path.path_label == "regenerated"
    assert ts.flags.had_regeneration is True and ts.flags.used_fallback is False
    assert ts.flags.verification_warning is False


def test_trace_summary_limited_data_flag():
    raw = _raw(data_status="data_limited")
    ts = build_read_model(report_id=_RID, raw=raw, stock=None).trace_summary
    assert ts.data_quality.limited is True and ts.flags.limited_data is True


def test_trace_summary_intraday_flag():
    raw = _raw(intraday_context={"as_of": "x"})
    ts = build_read_model(report_id=_RID, raw=raw, stock=None).trace_summary
    assert ts.flags.has_intraday_context is True and ts.data_quality.intraday_available is True


def test_trace_summary_backward_compat_empty_payload():
    ts = build_read_model(report_id=_RID, raw={}, stock=None).trace_summary
    assert ts.generation_path.path_label == "normal"            # 기본 안정
    assert ts.data_quality.chart_count == 0 and ts.data_quality.available_periods == []
    assert ts.stability.verification_consistent is None          # verification 없음
    assert ts.flags.used_fallback is False and ts.flags.verification_warning is False


# ── follow-up read flow projection ───────────────────────────────────────────
from datetime import UTC, datetime  # noqa: E402

from db.models.technical.report_followup import TechnicalReportFollowup  # noqa: E402
from db.models.technical.technical_report import TechnicalReport  # noqa: E402
from src.api.services.technical_report_service import build_followups_read_model  # noqa: E402


def _report(**over) -> TechnicalReport:
    base = dict(
        id=_RID, request_id="req-1", ticker="373220", stock_code="373220",
        stock_name="LGES(저장당시)", final_regime="uptrend_intact", daily_regime="uptrend_intact",
        alignment_flag="aligned", data_status="normal", output_payload=_raw(),
    )
    base.update(over)
    return TechnicalReport(**base)


def _fu(**over) -> TechnicalReportFollowup:
    base = dict(
        id=uuid4(), report_id=_RID, question="추가 질문?", answer="추가 답변.",
        model_name="gpt-x", trace_id="tr-fu", request_id="req-fu",
        created_at=datetime(2026, 7, 9, 1, tzinfo=UTC), context_snapshot=None,
    )
    base.update(over)
    return TechnicalReportFollowup(**base)


def test_followups_read_model_binds_parent_summary():
    from db.models.common.stock import Stock
    stock = Stock(stock_code="373220", stock_name="LG에너지솔루션", market="KOSPI")
    rm = build_followups_read_model(report=_report(), stock=stock, followups=[_fu()])
    assert rm.report_id == _RID
    assert rm.stock.stock_name == "LG에너지솔루션"                 # canonical 우선
    assert rm.report_summary.one_line_summary == "과열·약한 긍정"  # parent report 요약 연결
    assert rm.report_summary.final_regime == "uptrend_intact"
    assert rm.followup_count == 1
    fu = rm.followups[0]
    assert fu.question == "추가 질문?" and fu.answer_length == len("추가 답변.")
    assert fu.model_name == "gpt-x" and fu.trace_id == "tr-fu"
    assert fu.context.has_context_snapshot is False               # snapshot None


def test_followups_empty_is_stable():
    rm = build_followups_read_model(report=_report(), stock=None, followups=[])
    assert rm.followups == [] and rm.followup_count == 0
    assert rm.stock.stock_code == "373220"                        # stock None → report fallback


def test_followup_context_summarized_from_snapshot():
    snap = {"final_regime": "downtrend", "directional_bias": "bearish",
            "data_status": "data_limited", "signal_score": -0.4, "as_of": "2026-07-08T00:00:00+00:00"}
    rm = build_followups_read_model(report=_report(), stock=None, followups=[_fu(context_snapshot=snap)])
    ctx = rm.followups[0].context
    assert ctx.has_context_snapshot is True
    assert ctx.base_report_regime == "downtrend" and ctx.base_report_bias == "bearish"
    assert ctx.base_report_data_status == "data_limited" and ctx.base_report_signal_score == -0.4
    assert ctx.base_report_as_of == "2026-07-08T00:00:00+00:00"


def test_followup_context_tolerates_unknown_snapshot_shape():
    # writer 미정의 → 알려진 키 없으면 has_context_snapshot=True 지만 base_* 는 None(예외 없음).
    rm = build_followups_read_model(report=_report(), stock=None,
                                    followups=[_fu(context_snapshot={"weird": {"nested": 1}})])
    ctx = rm.followups[0].context
    assert ctx.has_context_snapshot is True and ctx.base_report_regime is None


def test_read_model_has_followup_count_default_zero():
    rm = build_read_model(report_id=_RID, raw=_raw(), stock=None)
    assert rm.followup_count == 0


def test_parent_snapshot_roundtrips_through_read_context():
    # writer 가 저장한 snapshot 을 read `_followup_context` 가 그대로 요약으로 복원한다(키 정합).
    from src.api.services.technical_report_service import _followup_context, _parent_context_snapshot
    from db.models.common.stock import Stock
    stock = Stock(stock_code="373220", stock_name="LG에너지솔루션", market="KOSPI")
    snap = _parent_context_snapshot(report=_report(), stock=stock)
    assert snap["snapshot_version"] == 1 and snap["base_report_id"] == str(_RID)
    assert snap["base_report_regime"] == "uptrend_intact" and snap["base_report_bias"] == "bullish"
    ctx = _followup_context(snap)                               # write→read 정합
    assert ctx.has_context_snapshot is True
    assert ctx.base_report_regime == "uptrend_intact" and ctx.base_report_bias == "bullish"
    assert ctx.base_report_signal_score == 0.3


# ── list/index item projection ───────────────────────────────────────────────
def test_list_item_projection_and_blocks():
    from db.models.common.stock import Stock
    from src.api.services.technical_report_service import build_list_item
    stock = Stock(stock_code="373220", stock_name="LG에너지솔루션", market="KOSPI")
    it = build_list_item(report=_report(), stock=stock, followup_count=2)
    assert it.report_id == _RID
    assert it.stock.stock_name == "LG에너지솔루션"                # canonical 우선
    assert it.summary.one_line_summary == "과열·약한 긍정"
    assert it.summary.directional_bias == "bullish" and it.summary.final_regime == "uptrend_intact"
    assert it.status.data_status == "normal" and it.status.path_label == "normal"
    assert it.status.verification_warning is False and it.status.limited_data is False
    assert it.engagement.followup_count == 2
    assert it.meta.created_at is None or it.meta.trace_id == "trace-1"


def test_list_item_status_matches_detail_trace_summary():
    # 목록 status 축약이 detail trace_summary 파생과 동일 규칙(일관성 잠금).
    from src.api.services.technical_report_service import build_list_item, build_read_model
    raw = _raw(interpretation={"text": "폴백.", "source": "template_fallback"},
               verification={"calc_passed": True, "regime_passed": True, "label_matched": False,
                             "outcome": "template_fallback", "regen_count": 1},
               data_status="data_limited")
    detail = build_read_model(report_id=_RID, raw=raw, stock=None).trace_summary
    it = build_list_item(report=_report(output_payload=raw), stock=None, followup_count=0)
    assert it.status.path_label == detail.generation_path.path_label == "template_fallback"
    assert it.status.verification_warning == detail.flags.verification_warning is True
    assert it.status.limited_data == detail.flags.limited_data is True


def test_list_item_backward_safe_empty_payload():
    from src.api.services.technical_report_service import build_list_item
    it = build_list_item(report=_report(output_payload={}), stock=None, followup_count=0)
    assert it.summary.one_line_summary is None
    assert it.status.path_label == "normal" and it.status.verification_warning is False
    assert it.summary.final_regime == "uptrend_intact"            # denorm 컬럼 fallback
    assert it.stock.stock_code == "373220"


# ── trust/quality summary projection ─────────────────────────────────────────
def test_trust_summary_projection():
    from src.api.services.technical_report_service import build_read_model
    raw = _raw()
    raw["technical_signals"] = [
        {"indicator": "moving_average", "signal": "positive", "detail_source": "llm"},
        {"indicator": "rsi", "signal": "neutral", "detail_source": "template_fallback"},
    ]
    ts = build_read_model(report_id=_RID, raw=raw, stock=None).trust_summary
    assert ts.signal_quality.signal_score == 0.3 and ts.signal_quality.consensus == "weak_positive"
    assert ts.signal_quality.signal_label == "약한 긍정"           # consensus 파생 라벨
    assert ts.signal_quality.confidence == 0.42
    assert ts.data_quality.data_status == "normal"
    assert ts.verification_gate.outcome == "passed" and ts.verification_gate.verification_warning is False
    # source_linkage: 2건 중 llm 1건 → 0.5
    assert ts.source_linkage.total_signal_items == 2
    assert ts.source_linkage.sourced_signal_items == 1
    assert ts.source_linkage.source_coverage_ratio == 0.5


def test_trust_summary_source_linkage_zero_safe():
    from src.api.services.technical_report_service import build_read_model
    raw = _raw()
    raw["technical_signals"] = []
    ts = build_read_model(report_id=_RID, raw=raw, stock=None).trust_summary
    assert ts.source_linkage.total_signal_items == 0
    assert ts.source_linkage.source_coverage_ratio == 0.0        # 0-div 안전


# ── full charts read model ───────────────────────────────────────────────────
def test_charts_read_model_full_payload():
    from db.models.common.stock import Stock
    from src.api.services.technical_report_service import build_charts_read_model
    raw = _raw()
    raw["charts"] = [
        {"period": "3m", "chart_data": {"candle_unit": "D", "candles": [{"o": 1}], "annotations": [{"kind": "x"}]}},
        {"period": "5y", "chart_data": {"candle_unit": "W", "candles": [], "annotations": []}},
    ]
    stock = Stock(stock_code="373220", stock_name="LG에너지솔루션", market="KOSPI")
    cm = build_charts_read_model(report=_report(output_payload=raw), stock=stock)
    assert cm.available_periods == ["3m", "5y"] and cm.stock.stock_name == "LG에너지솔루션"
    c0 = cm.charts[0]
    assert c0.period == "3m" and c0.candle_unit == "D" and c0.has_chart_data is True
    assert c0.chart_data["candles"] == [{"o": 1}]                # full payload 노출
    assert c0.annotations == [{"kind": "x"}] and c0.annotation_count == 1


def test_charts_read_model_empty_safe():
    from src.api.services.technical_report_service import build_charts_read_model
    cm = build_charts_read_model(report=_report(output_payload={}), stock=None)
    assert cm.charts == [] and cm.available_periods == []


# ── detailed trace read model (truthful, duration null) ──────────────────────
def test_trace_detail_steps_and_null_duration():
    from src.api.services.technical_report_service import build_trace_detail
    td = build_trace_detail(report=_report())
    assert td.overall.total_steps == 5 and td.overall.total_duration_ms is None   # 미측정
    assert td.overall.llm_used is True and td.overall.data_source_summary == "KIS"
    keys = [s.step_key for s in td.steps]
    assert keys == ["data_collect", "regime_classify", "signal_aggregate", "interpret_report", "verify"]
    assert all(s.duration_ms is None for s in td.steps)          # 지어내지 않음
    interp_step = next(s for s in td.steps if s.step_key == "interpret_report")
    assert interp_step.llm_involved is True and interp_step.status == "ok"


def test_trace_detail_fallback_and_limited():
    from src.api.services.technical_report_service import build_trace_detail
    raw = _raw(interpretation={"text": "폴백.", "source": "template_fallback"},
               verification={"calc_passed": True, "regime_passed": True, "label_matched": False,
                             "outcome": "template_fallback", "regen_count": 1},
               data_status="data_limited")
    td = build_trace_detail(report=_report(output_payload=raw))
    assert td.overall.llm_used is False
    dc = next(s for s in td.steps if s.step_key == "data_collect")
    assert dc.status == "degraded"                               # data_limited
    ip = next(s for s in td.steps if s.step_key == "interpret_report")
    assert ip.status == "fallback" and ip.llm_involved is False
    vf = next(s for s in td.steps if s.step_key == "verify")
    assert vf.status == "fallback"


# ── 의미 잠금(semantics) 테스트 — 문서 계약과 projection 일치 고정 ──────────────
def test_verification_gate_pass_vs_warn_criteria():
    from src.api.services.technical_report_service import build_read_model
    # PASS: outcome=passed AND calc∧regime∧label
    pass_raw = _raw(verification={"calc_passed": True, "regime_passed": True, "label_matched": True,
                                  "outcome": "passed", "regen_count": 0})
    g = build_read_model(report_id=_RID, raw=pass_raw, stock=None).trust_summary.verification_gate
    assert g.outcome == "passed" and g.verification_warning is False
    # WARN: label_matched False (정합 깨짐) → outcome passed 여도 warning
    warn1 = _raw(verification={"calc_passed": True, "regime_passed": True, "label_matched": False,
                               "outcome": "passed", "regen_count": 0})
    assert build_read_model(report_id=_RID, raw=warn1, stock=None).trust_summary.verification_gate.verification_warning is True
    # WARN: outcome != passed
    warn2 = _raw(verification={"calc_passed": True, "regime_passed": True, "label_matched": True,
                               "outcome": "template_fallback", "regen_count": 1})
    assert build_read_model(report_id=_RID, raw=warn2, stock=None).trust_summary.verification_gate.verification_warning is True


def test_source_coverage_excludes_template_fallback():
    from src.api.services.technical_report_service import build_read_model
    raw = _raw()
    raw["technical_signals"] = [
        {"indicator": "moving_average", "detail_source": "llm"},
        {"indicator": "rsi", "detail_source": "llm_regenerated"},
        {"indicator": "volume", "detail_source": "template_fallback"},   # 분자 제외
    ]
    sl = build_read_model(report_id=_RID, raw=raw, stock=None).trust_summary.source_linkage
    assert sl.total_signal_items == 3 and sl.sourced_signal_items == 2    # template 제외
    assert sl.source_coverage_ratio == round(2 / 3, 3)


def test_charts_all_periods_returned_eager():
    from src.api.services.technical_report_service import build_charts_read_model
    raw = _raw()
    raw["charts"] = [
        {"period": "3m", "chart_data": {"candle_unit": "D", "candles": []}},
        {"period": "1y", "chart_data": {"candle_unit": "D", "candles": []}},
        {"period": "5y", "chart_data": {"candle_unit": "W", "candles": []}},
    ]
    cm = build_charts_read_model(report=_report(output_payload=raw), stock=None)
    assert cm.available_periods == ["3m", "1y", "5y"]                    # all-period eager(잠금)
    assert len(cm.charts) == 3


# ── indicator cards (지표 카드 read model) ───────────────────────────────────
def _raw_cards(**over) -> dict:
    raw = _raw()
    raw["technical_signals"] = [
        {"indicator": "moving_average", "signal": "negative", "value": 412000.0, "weight": 0.3,
         "detail": "이동평균 부정", "detail_source": "llm",
         "metrics": ["5MA 449300.0", "20MA 496500.0", "60MA 570683.3"]},
        {"indicator": "rsi", "signal": "neutral", "value": 33.2, "weight": 0.2,
         "detail": "RSI 중립", "detail_source": "llm", "metrics": ["RSI(14) 33.2", "기준 35/70"]},
        {"indicator": "volume", "signal": "negative", "value": 1.04, "weight": 0.2,
         "detail": "거래량 부정", "detail_source": "template_fallback", "metrics": ["거래량비 1.04"]},
        {"indicator": "support_resistance", "signal": "neutral", "value": 412000.0, "weight": 0.2,
         "detail": "지지저항 중립", "detail_source": "llm", "metrics": ["지지 403500.0", "저항 582000.0"]},
        {"indicator": "pattern", "signal": "negative", "value": 21000.0, "weight": 0.1,
         "detail": "패턴 부정", "detail_source": "llm", "metrics": ["몸통 21000.0"]},
    ]
    raw["charts"] = [
        {"period": "1y", "chart_data": {"candle_unit": "D", "annotations": [
            {"kind": "dead_cross", "date": "2026-06-01", "label": "데드크로스", "importance": "high"},
            {"kind": "cup_handle_candidate", "date": "2026-05-13", "label": "컵앤핸들 후보",
             "importance": "medium", "meta": {"cup_depth_pct": 0.28, "candidate_stage": "handle_forming",
                                              "volume_confirmed": False}},
        ]}},
    ]
    raw.update(over)
    return raw


def test_indicator_cards_five_with_weight_and_calc_basis():
    rm = build_read_model(report_id=_RID, raw=_raw_cards(), stock=None)
    cards = {c.indicator: c for c in rm.indicator_cards}
    assert set(cards) == {"moving_average", "rsi", "volume", "support_resistance", "pattern"}
    # weight 는 read model signals 에도, 카드에도 노출.
    assert rm.signals.items[0].weight == 0.3
    ma = cards["moving_average"]
    assert ma.title == "이동평균" and ma.signal_label == "부정" and ma.weight == 0.3
    assert ma.calc_basis.ma == {"5": 449300.0, "20": 496500.0, "60": 570683.3}
    assert ma.calc_basis.alignment == "역배열"                     # 5<20<60
    rsi = cards["rsi"]
    assert rsi.calc_basis.rsi_period == 14 and rsi.calc_basis.oversold == 35.0 and rsi.calc_basis.overbought == 70.0
    assert cards["volume"].calc_basis.relative_volume == 1.04
    sr = cards["support_resistance"].calc_basis
    assert sr.support == 403500.0 and sr.resistance == 582000.0 and sr.position == "지지 근접"
    assert cards["moving_average"].verified is True                # 리포트 verification passed


def test_pattern_card_exposes_cup_handle_annotation_only():
    rm = build_read_model(report_id=_RID, raw=_raw_cards(), stock=None)
    pattern = next(c for c in rm.indicator_cards if c.indicator == "pattern")
    kinds = [pc.kind for pc in pattern.pattern_candidates]
    assert "cup_handle_candidate" in kinds
    pc = next(p for p in pattern.pattern_candidates if p.kind == "cup_handle_candidate")
    assert pc.period == "1y" and pc.label == "컵앤핸들 후보"
    assert pc.meta["candidate_stage"] == "handle_forming"          # meta 그대로 전달
    # annotation-only 정책: signal_score/final_regime/consensus 는 영향 없음(기존값 불변).
    assert rm.signals.signal_score == 0.3 and rm.summary.final_regime == "uptrend_intact"
    assert rm.summary.directional_bias == "bullish"                # cup_handle 이 방향 바꾸지 않음


def test_pattern_card_empty_when_no_candidate():
    raw = _raw_cards()
    raw["charts"] = [{"period": "1y", "chart_data": {"annotations": [
        {"kind": "dead_cross", "date": "2026-06-01"}]}}]
    rm = build_read_model(report_id=_RID, raw=raw, stock=None)
    pattern = next(c for c in rm.indicator_cards if c.indicator == "pattern")
    assert pattern.pattern_candidates == []                        # 없으면 빈 배열(안전)


def test_indicator_cards_backward_safe_empty_payload():
    rm = build_read_model(report_id=_RID, raw={}, stock=None)
    assert rm.indicator_cards == []                                # 구버전/빈 payload → 빈 배열
