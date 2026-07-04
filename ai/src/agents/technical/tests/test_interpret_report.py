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


def test_interpretation_from_llm_source():
    out = node.parse_llm_output(VALID_OUTPUT)
    result = node.interpretation_from_llm(out, source=GenerationSource.LLM_REGENERATED)
    assert result.source == GenerationSource.LLM_REGENERATED
    assert result.text.startswith("현재는 과열")


# ── template fallback (새 판단 없이 확정값만) ───────────────────────────────
def test_fallback_interpretation_uses_confirmed_only():
    risks = [RiskItem(flag=RiskFlag.OVERHEATED_MOMENTUM, note="단기 과열."),
             RiskItem(flag=RiskFlag.VOLUME_NOT_CONFIRMED, note="거래량 약함.")]
    result = node.fallback_interpretation(regime=_regime(), signal=_signal(), risks=risks)
    assert result.source == GenerationSource.TEMPLATE_FALLBACK
    assert "과열" in result.text
    assert "약한 긍정" in result.text
    assert "보통" in result.text
    assert "단기 과열 관찰" in result.text
    assert result.text.endswith("참고 정보입니다.")
    assert contains_forbidden_terms(result.text) == []


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
