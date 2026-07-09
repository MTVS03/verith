"""노드 10(interpret_report) 단위테스트. 실제 LLM 호출 없음 — fake LlmClient만 사용.

검사 축(test_plan §5·contracts §2):
  - payload는 코드 확정값만 담고 value=None을 보존한다(확정 4).
  - LLM 응답 파싱(정상·코드펜스·오류).
  - detail만 병합하고 signal/value/weight를 바꾸지 않는다.
  - 검증 실패분만 template fallback, source(llm/llm_regenerated/template_fallback) 처리.
  - fallback은 확정값만 문장화하며 매수/매도·새 판단이 없다.
"""

from __future__ import annotations

import json

import pytest

from src.agents.technical.nodes import interpret_report as node
from src.agents.technical.observability.trajectory_eval import contains_forbidden_terms, evaluate
from src.agents.technical.schemas.contracts import RegimeResult, RiskItem, SignalSummary
from src.agents.technical.schemas.enums import (
    AlignmentFlag,
    ConfidenceLevel,
    Consensus,
    DirectionalBias,
    GenerationSource,
    IndicatorType,
    Regime,
    RiskFlag,
    Signal,
    Trend,
)
from src.agents.technical.synthesis.signal_score import IndicatorSignalResult

MA = IndicatorType.MOVING_AVERAGE
RSI = IndicatorType.RSI
VOL = IndicatorType.VOLUME


class FakeLlm:
    """주입된 응답 문자열을 그대로 돌려주는 fake. 네트워크 없음."""

    def __init__(self, response: str):
        self._response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._response


def _regime(final=Regime.OVERHEATED, alignment=AlignmentFlag.NEUTRAL) -> RegimeResult:
    return RegimeResult(
        daily_regime=final, final_regime=final,
        weekly_trend=Trend.UP, monthly_trend=Trend.UP,
        alignment_flag=alignment, regime_context="상위 추세는 상승이나 단기 과열이 관찰됩니다.",
    )


def _signal(consensus=Consensus.WEAK_POSITIVE, level=ConfidenceLevel.MEDIUM) -> SignalSummary:
    return SignalSummary(consensus=consensus, signal_score=0.30, confidence=0.42,
                         confidence_level=level, confidence_basis="긍정 2·중립 2·부정 1로 엇갈림.")


def _signals():
    return [
        IndicatorSignalResult(MA, Signal.POSITIVE, 82900.0, ["5MA 82900.0", "20MA 81400.0"], 0.30),
        IndicatorSignalResult(RSI, Signal.NEUTRAL, 58.2, ["RSI(14) 58.2"], 0.20),
        IndicatorSignalResult(VOL, Signal.NEUTRAL, None, [], 0.20),  # value=None (계산 불가)
    ]


VALID_OUTPUT = json.dumps({
    "interpretation_text": "현재는 과열 국면이며 약한 긍정으로 해석됩니다. "
                           "거래량 확인이 약해 신호 강도는 제한적입니다. 이 내용은 참고 정보입니다.",
    "details": [
        {"indicator": "moving_average", "detail": "이동평균선 기준 긍정 신호가 관찰됩니다."},
        {"indicator": "rsi", "detail": "RSI는 중립 구간입니다."},
        {"indicator": "volume", "detail": "거래량은 중립 수준입니다."},
    ],
}, ensure_ascii=False)


# ── payload (확정값만·value=None 보존) ──────────────────────────────────────
def test_build_payload_shape_and_value_none():
    payload = node.build_payload(regime=_regime(), signal=_signal(),
                                 signals=_signals(), risks=[])
    assert payload["final_regime"] == "overheated"
    assert payload["consensus"] == "weak_positive"
    assert payload["confidence_level"] == "medium"
    vol = next(t for t in payload["technical_signals"] if t["indicator"] == "volume")
    assert vol["value"] is None          # 확정 4: None을 임의로 바꾸지 않는다
    assert "weight" not in payload["technical_signals"][0]  # LLM 서술에 불필요


def test_build_payload_includes_risk():
    risks = [RiskItem(flag=RiskFlag.VOLUME_NOT_CONFIRMED, note="거래량 확인이 약합니다.")]
    payload = node.build_payload(regime=_regime(), signal=_signal(), signals=_signals(), risks=risks)
    assert payload["risk_items"] == [{"flag": "volume_not_confirmed", "note": "거래량 확인이 약합니다."}]


# ── 렌더·파싱 ────────────────────────────────────────────────────────────────
def test_render_prompt_injects_payload():
    template = node.load_prompt(node.INTERPRET_PROMPT)
    rendered = node.render_prompt(template, {"final_regime": "overheated"})
    assert "{payload_json}" not in rendered
    assert "overheated" in rendered


def test_parse_valid_and_fenced():
    assert node.parse_llm_output(VALID_OUTPUT)["interpretation_text"]
    fenced = f"```json\n{VALID_OUTPUT}\n```"
    assert node.parse_llm_output(fenced)["details"]


def test_parse_invalid_raises():
    with pytest.raises(node.LlmOutputParseError):
        node.parse_llm_output("not json at all")
    with pytest.raises(node.LlmOutputParseError):
        node.parse_llm_output("[1, 2, 3]")  # 최상위 object 아님


def test_parse_rejects_extra_top_key():
    with pytest.raises(node.LlmOutputParseError):
        node.parse_llm_output(json.dumps(
            {"interpretation_text": "x", "extra": {"signal_score": 1.0}}, ensure_ascii=False))


def test_parse_rejects_extra_detail_key():
    with pytest.raises(node.LlmOutputParseError):
        node.parse_llm_output(json.dumps(
            {"interpretation_text": "x",
             "details": [{"indicator": "moving_average", "detail": "d", "signal": "negative"}]},
            ensure_ascii=False))


def test_generate_single_call():
    client = FakeLlm(VALID_OUTPUT)
    out = node.generate(client, template="{payload_json}", payload={"a": 1})
    assert out["interpretation_text"]
    assert len(client.prompts) == 1  # 단일 호출(루프 아님)


# ── verify 통합 ──────────────────────────────────────────────────────────────
def test_verify_pass_and_fail():
    out = node.parse_llm_output(VALID_OUTPUT)
    result = node.verify(out, regime=_regime(), signal=_signal(), signals=_signals())
    assert result.passed, result.failures

    distorted = {"interpretation_text": "상승 추세가 뚜렷합니다.",  # 과열인데 상승 추세로 왜곡
                 "details": [{"indicator": "moving_average", "detail": "이동평균선은 부정적입니다."},
                             {"indicator": "rsi", "detail": "RSI는 중립 구간입니다."},
                             {"indicator": "volume", "detail": "거래량은 중립 수준입니다."}]}
    bad = node.verify(distorted, regime=_regime(), signal=_signal(), signals=_signals())
    assert not bad.passed


def test_verify_low_confidence_high_claim_fails():
    out = {"interpretation_text": "과열 국면이며 약한 긍정입니다. 신뢰도가 높습니다.",
           "details": [{"indicator": "moving_average", "detail": "이동평균선 긍정 신호."},
                       {"indicator": "rsi", "detail": "RSI는 중립 구간입니다."},
                       {"indicator": "volume", "detail": "거래량은 중립 수준입니다."}]}
    result = node.verify(out, regime=_regime(), signal=_signal(level=ConfidenceLevel.LOW),
                         signals=_signals())
    assert not result.passed
    assert any(f.reason.startswith("conflict") for f in result.failures)


def test_verify_risk_omission_fails():
    out = {"interpretation_text": "과열 국면이며 약한 긍정입니다.",  # 거래량/위험 언급 없음
           "details": [{"indicator": "moving_average", "detail": "이동평균선 긍정 신호."},
                       {"indicator": "rsi", "detail": "RSI는 중립 구간입니다."},
                       {"indicator": "volume", "detail": "거래량은 중립 수준입니다."}]}
    risks = [RiskItem(flag=RiskFlag.VOLUME_NOT_CONFIRMED, note="거래량 확인이 약합니다.")]
    result = node.verify(out, regime=_regime(), signal=_signal(), signals=_signals(), risks=risks)
    assert not result.passed
    assert any(f.reason == "risk_not_mentioned" for f in result.failures)


# ── 병합 (detail만·source 처리) ─────────────────────────────────────────────
def test_details_from_llm_uses_llm_and_preserves_order():
    out = node.parse_llm_output(VALID_OUTPUT)
    signals = _signals()
    details = node.details_from_llm(out, signals=signals, source=GenerationSource.LLM)
    assert [d.indicator for d in details] == ["moving_average", "rsi", "volume"]
    assert all(d.detail_source == GenerationSource.LLM for d in details)
    assert details[0].detail == "이동평균선 기준 긍정 신호가 관찰됩니다."
    # 확정값 불변: signals 원본은 그대로(신호·value 미변경)
    assert signals[0].signal == Signal.POSITIVE
    assert signals[2].value is None


def test_details_partial_fallback_only_failed():
    out = node.parse_llm_output(VALID_OUTPUT)
    signals = _signals()
    details = node.details_from_llm(out, signals=signals, source=GenerationSource.LLM,
                                    failed_indicators=frozenset({"moving_average"}))
    by_ind = {d.indicator: d for d in details}
    assert by_ind["moving_average"].detail_source == GenerationSource.TEMPLATE_FALLBACK
    assert by_ind["rsi"].detail_source == GenerationSource.LLM  # 나머지 유지 (REGEN-04)


def test_details_missing_indicator_falls_back():
    out = {"interpretation_text": "x", "details": [
        {"indicator": "moving_average", "detail": "이동평균선 긍정."}]}  # rsi·volume 누락
    details = node.details_from_llm(out, signals=_signals(), source=GenerationSource.LLM)
    by_ind = {d.indicator: d for d in details}
    assert by_ind["rsi"].detail_source == GenerationSource.TEMPLATE_FALLBACK
    assert by_ind["volume"].detail_source == GenerationSource.TEMPLATE_FALLBACK


# ── 지표별 설명 확장(additive): reason/caution/watchpoint ───────────────────────
def test_details_from_llm_captures_additive_fields():
    out = {"interpretation_text": "x", "details": [
        {"indicator": "moving_average", "detail": "이동평균선 긍정.",
         "detail_reason": "5MA가 20·60MA 위라 정배열입니다.",
         "detail_caution": "이동평균은 후행 지표입니다.",
         "detail_watchpoint": "배열 유지·크로스를 확인하세요."},
        {"indicator": "rsi", "detail": "RSI 중립."},
        {"indicator": "volume", "detail": "거래량 중립."},
    ]}
    by_ind = {d.indicator: d for d in
              node.details_from_llm(out, signals=_signals(), source=GenerationSource.LLM)}
    ma = by_ind["moving_average"]
    assert ma.detail_source == GenerationSource.LLM
    assert ma.detail_reason == "5MA가 20·60MA 위라 정배열입니다."
    assert ma.detail_caution == "이동평균은 후행 지표입니다."
    assert ma.detail_watchpoint == "배열 유지·크로스를 확인하세요."


def test_details_from_llm_backfills_missing_additive():
    # LLM이 detail만 주고 additive 필드를 생략해도, 결정론 백필로 3필드가 비지 않는다(카드 공백 방지).
    out = node.parse_llm_output(VALID_OUTPUT)  # additive 필드 없음
    by_ind = {d.indicator: d for d in
              node.details_from_llm(out, signals=_signals(), source=GenerationSource.LLM)}
    rsi = by_ind["rsi"]
    assert rsi.detail_source == GenerationSource.LLM  # 본문 detail 은 LLM
    assert rsi.detail == "RSI는 중립 구간입니다."
    assert rsi.detail_reason and rsi.detail_caution and rsi.detail_watchpoint  # 백필됨(비지 않음)
    assert "RSI" in rsi.detail_caution  # 지표별 결정론 hint


def test_fallback_detail_fills_all_four_fields():
    fb = node.fallback_detail(MA, Signal.POSITIVE, ["5MA 82900.0"])
    assert fb.detail and fb.detail_reason and fb.detail_caution and fb.detail_watchpoint
    assert fb.detail_source == GenerationSource.TEMPLATE_FALLBACK
    assert "긍정" in fb.detail_reason  # 확정 signal 근거 설명
    assert "이동평균" in fb.detail_caution  # 지표별 결정론 hint(MA)


def test_parse_accepts_additive_detail_keys():
    out = node.parse_llm_output(json.dumps({"interpretation_text": "x", "details": [
        {"indicator": "rsi", "detail": "중립", "detail_reason": "r",
         "detail_caution": "c", "detail_watchpoint": "w"}]}, ensure_ascii=False))
    assert out["details"][0]["detail_reason"] == "r"


def test_additive_fields_do_not_break_verify():
    # additive 필드가 있어도 검증(③)은 detail 만 보므로 결과 불변(회귀 방지).
    out = node.parse_llm_output(VALID_OUTPUT)
    for e in out["details"]:
        e["detail_reason"] = "설명"
        e["detail_watchpoint"] = "관찰"
    ev = node.verify(out, regime=_regime(), signal=_signal(), signals=_signals(), risks=())
    assert not ev.details_structure_failed


def test_interpretation_from_llm_source():
    out = node.parse_llm_output(VALID_OUTPUT)
    result = node.interpretation_from_llm(
        out, source=GenerationSource.LLM_REGENERATED,
        regime=_regime(), signal=_signal(), signals=_signals(), risks=(),
    )
    assert result.source == GenerationSource.LLM_REGENERATED
    assert result.text.startswith("현재는 과열")
    # directional_bias 는 LLM 이 아니라 consensus(weak_positive)에서 코드가 파생.
    assert result.directional_bias == DirectionalBias.BULLISH
    # 섹션은 LLM 누락 시 결정론 기본값으로 채워진다.
    assert result.one_line_summary and result.timeframe_alignment and result.invalidation_or_caution


# ── template fallback (새 판단 없이 확정값만) ───────────────────────────────
def test_fallback_interpretation_uses_confirmed_only():
    risks = [RiskItem(flag=RiskFlag.OVERHEATED_MOMENTUM, note="단기 과열."),
             RiskItem(flag=RiskFlag.VOLUME_NOT_CONFIRMED, note="거래량 약함.")]
    result = node.fallback_interpretation(regime=_regime(), signal=_signal(), risks=risks)
    assert result.source == GenerationSource.TEMPLATE_FALLBACK
    assert "과열" in result.text
    assert "약한 긍정" in result.text
    assert "보통" in result.text
    # 강화된 risk 해설: 단순 라벨 나열이 아니라 의미+제약+관찰이 담긴다.
    assert "단기 과열 부담" in result.text          # 라벨("단기 과열 관찰") 대신 의미 서술
    assert "확신이 제한" in result.text             # 해석 제약 문장
    assert result.text.endswith("참고 정보입니다.")
    assert contains_forbidden_terms(result.text) == []


# ── risk_interpretation 고도화(맥락 있는 해설·나열 금지) ────────────────────────
def _risks_combo():
    return [RiskItem(flag=RiskFlag.VOLUME_NOT_CONFIRMED, note="거래량 약함."),
            RiskItem(flag=RiskFlag.NEAR_SUPPORT, note="지지 근접."),
            RiskItem(flag=RiskFlag.MIXED_SIGNALS, note="신호 엇갈림.")]


def test_risk_text_is_explanatory_not_a_flag_list():
    txt = node._risk_text(_risks_combo())
    # 나쁜(구) 형태: "위험 요인으로 A·B·C이(가) 확인됩니다." — 이 패턴이 아니어야 한다.
    assert not txt.startswith("위험 요인으로 ")
    # 최소 2문장 + 해석 제약 + 관찰 포인트가 담긴다(맥락 있는 해설).
    assert txt.count(".") >= 2
    assert "확신이 제한" in txt
    assert "추가로 확인" in txt
    # 의미 서술(라벨 나열 아님)
    assert "거래량 확인이 약해" in txt and "지지 구간에 근접" in txt


def test_risk_text_no_advice_or_exaggeration():
    for combo in ([RiskItem(flag=RiskFlag.NEAR_RESISTANCE, note="x")],
                  [RiskItem(flag=RiskFlag.OVERHEATED_MOMENTUM, note="x")],
                  _risks_combo()):
        txt = node._risk_text(combo)
        assert contains_forbidden_terms(txt) == []            # 매수/매도/목표가 등 없음
        for bad in ("폭락", "반드시", "곧 하락", "손절", "목표가"):
            assert bad not in txt


def test_payload_includes_risk_hints():
    risks = _risks_combo()
    payload = node.build_payload(regime=_regime(), signal=_signal(), signals=_signals(), risks=risks)
    hints = payload["risk_hints"]
    assert [h["flag"] for h in hints] == ["volume_not_confirmed", "near_support", "mixed_signals"]
    h0 = hints[0]
    assert h0["label"] and h0["meaning"] and h0["watch"]       # 라벨·의미·관찰 힌트 존재
    assert payload["risk_items"][0]["flag"] == "volume_not_confirmed"  # 기존 risk_items 유지(회귀 0)


def test_risk_interpretation_from_llm_is_used_verbatim():
    # LLM 이 rich 한 risk_interpretation 을 주면 그대로 쓰고 fallback 나열로 덮지 않는다.
    out = node.parse_llm_output(json.dumps({
        "interpretation_text": "x",
        "risk_interpretation": "지지 근접 자체는 반등 여지를 주지만 거래량 확인이 약해 추세 전환으로 보긴 어렵습니다.",
    }, ensure_ascii=False))
    res = node.interpretation_from_llm(out, source=GenerationSource.LLM,
                                       regime=_regime(), signal=_signal(), signals=_signals(),
                                       risks=_risks_combo())
    assert res.risk_interpretation.startswith("지지 근접 자체는")


def test_fallback_detail_matches_signal_and_no_forbidden():
    for sig in (Signal.POSITIVE, Signal.NEUTRAL, Signal.NEGATIVE):
        d = node.fallback_detail(MA, sig, ["5MA 82900.0"])
        assert d.detail_source == GenerationSource.TEMPLATE_FALLBACK
        assert contains_forbidden_terms(d.detail) == []
    # 폴백 detail 자체는 검증 ③ 신호 규칙을 통과한다(방어적으로 자기모순 없음)
    fb = node.fallback_detail(MA, Signal.POSITIVE, [])
    res = evaluate({"interpretation_text": "과열, 약한 긍정, 참고 정보.",
                    "details": [{"indicator": "moving_average", "detail": fb.detail}]},
                   final_regime=Regime.OVERHEATED, consensus=Consensus.WEAK_POSITIVE,
                   alignment_flag=AlignmentFlag.NEUTRAL, signals=[(MA, Signal.POSITIVE)])
    assert res.passed, res.failures


def test_unavailable_interpretation():
    result = node.unavailable_interpretation()
    assert result.source == GenerationSource.TEMPLATE_FALLBACK
    assert "국면을 판정하지 않" in result.text


# ── 확정값 재생성 시도 무시 ─────────────────────────────────────────────────
def test_llm_attempt_to_change_signal_is_ignored_by_merge():
    # LLM이 detail 항목에 signal을 끼워넣어도 병합은 detail만 읽는다(코드 확정 signal 불변).
    out = {"interpretation_text": "x", "details": [
        {"indicator": "moving_average", "detail": "이동평균선 긍정.", "signal": "negative"},
        {"indicator": "rsi", "detail": "RSI 중립.", "signal": "positive"},
        {"indicator": "volume", "detail": "거래량 중립."}]}
    details = node.details_from_llm(out, signals=_signals(), source=GenerationSource.LLM)
    # DetailResult에는 signal 필드가 없다 — 확정 signal은 병합 대상이 아니다.
    assert not hasattr(details[0], "signal")
    assert details[0].detail == "이동평균선 긍정."


# ── 구조화 해석 upgrade (이번 브랜치) ────────────────────────────────────────
def test_build_payload_includes_data_status_hint():
    payload = node.build_payload(regime=_regime(), signal=_signal(), signals=_signals(),
                                 risks=[], data_status="data_limited")
    assert payload["data_status"] == "data_limited"
    # 미지정이면 키 없음(하위호환).
    assert "data_status" not in node.build_payload(
        regime=_regime(), signal=_signal(), signals=_signals(), risks=[])


def test_directional_bias_derived_from_consensus():
    assert node.bias_from_consensus(Consensus.STRONG_POSITIVE) == DirectionalBias.BULLISH
    assert node.bias_from_consensus(Consensus.WEAK_POSITIVE) == DirectionalBias.BULLISH
    assert node.bias_from_consensus(Consensus.NEUTRAL) == DirectionalBias.NEUTRAL
    assert node.bias_from_consensus(Consensus.STRONG_NEGATIVE) == DirectionalBias.BEARISH


def test_fallback_interpretation_fills_all_sections():
    risks = [RiskItem(flag=RiskFlag.OVERHEATED_MOMENTUM, note="단기 과열.")]
    r = node.fallback_interpretation(
        regime=_regime(alignment=AlignmentFlag.COUNTER_TREND), signal=_signal(),
        risks=risks, signals=_signals())
    assert r.source == GenerationSource.TEMPLATE_FALLBACK
    assert r.directional_bias == DirectionalBias.BULLISH            # consensus 파생
    assert r.one_line_summary and r.trend_interpretation and r.signal_interpretation
    assert r.risk_interpretation and r.timeframe_alignment and r.what_to_watch_next
    assert r.invalidation_or_caution
    assert "역행" in r.timeframe_alignment                          # counter_trend 반영
    assert len(r.warning_points) == 1 and "과열" in r.warning_points[0]   # risk 라벨
    assert r.key_drivers                                            # 지표 기반 근거


def test_unavailable_interpretation_neutral_and_no_overstatement():
    r = node.unavailable_interpretation()
    assert r.directional_bias == DirectionalBias.NEUTRAL
    assert r.warning_points == ["데이터 부족"]
    # 과장/추천/미래 단정 금지어가 없어야 한다.
    for field in (r.text, r.one_line_summary, r.invalidation_or_caution, r.trend_interpretation):
        assert not contains_forbidden_terms(field or "")


def test_interpretation_from_llm_keeps_llm_sections():
    out = {
        "interpretation_text": "현재는 과열 국면입니다. 참고 정보입니다.",
        "one_line_summary": "과열·약한 긍정",
        "timeframe_alignment": "주봉·월봉과 정합합니다.",
        "key_drivers": ["이동평균 긍정", "거래량 미확인"],
    }
    r = node.interpretation_from_llm(out, source=GenerationSource.LLM,
                                     regime=_regime(), signal=_signal(), signals=_signals(), risks=())
    assert r.one_line_summary == "과열·약한 긍정"                    # LLM 값 우선
    assert r.key_drivers == ["이동평균 긍정", "거래량 미확인"]
    assert r.trend_interpretation                                   # 누락 섹션은 결정론 기본값


def test_parse_accepts_and_type_checks_sections():
    good = json.dumps({"interpretation_text": "t", "one_line_summary": "s",
                       "key_drivers": ["a", "b"]}, ensure_ascii=False)
    assert node.parse_llm_output(good)["key_drivers"] == ["a", "b"]
    with pytest.raises(node.LlmOutputParseError):
        node.parse_llm_output(json.dumps({"key_drivers": "not-a-list"}))
    with pytest.raises(node.LlmOutputParseError):
        node.parse_llm_output(json.dumps({"one_line_summary": ["should-be-str"]}))


def test_verification_scans_section_forbidden_terms():
    out = {
        "interpretation_text": "현재는 과열 국면이며 약한 긍정으로 해석됩니다. 참고 정보입니다.",
        "one_line_summary": "지금 매수하세요",           # 금지어 — 섹션에서도 잡혀야
        "details": [],
    }
    ev = evaluate(out, final_regime=Regime.OVERHEATED, consensus=Consensus.WEAK_POSITIVE,
                  alignment_flag=AlignmentFlag.NEUTRAL, signals=[])
    assert not ev.passed
    assert any(f.reason == "forbidden_term" and "interpretation.one_line_summary" in f.target
               for f in ev.failures)


# ── verify_expressions: payload↔verify 계약 정렬(fix/interpret-verify-contract) ──
def test_build_payload_injects_verify_expressions_from_rules():
    from src.agents.technical.observability.keyword_rules import CONSENSUS_RULES, REGIME_RULES
    from src.agents.technical.schemas.enums import Regime
    regime = _regime(final=Regime.DOWNTREND, alignment=AlignmentFlag.NEUTRAL)
    signal = _signal(consensus=Consensus.STRONG_NEGATIVE)
    ve = node.build_payload(regime=regime, signal=signal, signals=_signals(),
                            risks=[])["verify_expressions"]
    # 검증이 요구하는 한글 대표어가 그대로 실린다(단일 출처 keyword_rules).
    assert ve["interpretation_must_include_any"]["regime"] == list(REGIME_RULES[Regime.DOWNTREND].required_any)
    assert ve["interpretation_must_include_any"]["consensus"] == list(CONSENSUS_RULES[Consensus.STRONG_NEGATIVE].required_any)
    assert "하락 추세" in ve["interpretation_must_include_any"]["regime"]
    assert "강한 부정" in ve["interpretation_must_include_any"]["consensus"]
    # neutral alignment 도 서술 표현을 준다(정합/역행 단독어 회피용).
    assert ve["interpretation_must_include_any"].get("alignment")
    # 영문 enum 금지 + 반대어(긍정/정합) avoid.
    assert ve["do_not_use_english_enum"] is True
    assert "긍정" in ve["must_avoid"] and "정합" in ve["must_avoid"]
    # 지표별 detail 표현.
    assert ve["detail_must_include_any_by_indicator"]["moving_average"] == ["긍정"]


def test_verify_expressions_risk_mention_and_confidence():
    from src.agents.technical.schemas.enums import RiskFlag
    risks = [RiskItem(flag=RiskFlag.VOLUME_NOT_CONFIRMED, note="거래량 약함")]
    ve = node.build_payload(regime=_regime(), signal=_signal(), signals=_signals(),
                            risks=risks)["verify_expressions"]
    assert "거래량" in ve["must_mention_risk_any"]               # risk 있으면 언급 표현 제공
