"""검증 ③ 단위테스트 (test_plan.md §5). 실제 LLM 호출 없음 — 결정론 키워드 판정만 검사.

LLM-01~07(종합 해석 왜곡), DETAIL-01~05(지표 detail 왜곡·구조), 금지어·확정값 재생성 필드,
교차 오판 방지(LLM-07)를 다룬다.
"""

from __future__ import annotations

from src.agents.technical.observability.keyword_rules import (
    ALIGNMENT_RULES,
    REGIME_RULES,
)
from src.agents.technical.observability.trajectory_eval import (
    check_label,
    contains_forbidden_terms,
    evaluate,
    evaluate_details,
    evaluate_text,
)
from src.agents.technical.schemas.enums import (
    AlignmentFlag,
    Consensus,
    IndicatorType,
    Regime,
    Signal,
)

MA = IndicatorType.MOVING_AVERAGE
RSI = IndicatorType.RSI
VOL = IndicatorType.VOLUME
SR = IndicatorType.SUPPORT_RESISTANCE
PAT = IndicatorType.PATTERN


def _text_failures(text, *, regime=Regime.OVERHEATED, consensus=Consensus.WEAK_POSITIVE,
                   alignment=AlignmentFlag.NEUTRAL):
    return evaluate_text(text, final_regime=regime, consensus=consensus, alignment_flag=alignment)


# ── 종합 해석 왜곡 (LLM-01~07) ──────────────────────────────────────────────
def test_llm01_regime_conflict():
    fails = _text_failures("상승 전환이 관찰됩니다.", regime=Regime.SIDEWAYS)
    assert fails  # 충돌어/대표어 부재로 실패


def test_llm02_consensus_flip():
    # 횡보 대표어는 있으나 약한 긍정 대표어가 없어(consensus 왜곡) 실패해야 한다.
    fails = _text_failures("횡보 흐름 속 부정 신호가 우세합니다.",
                           regime=Regime.SIDEWAYS, consensus=Consensus.WEAK_POSITIVE)
    assert any(f.reason == "missing_required" for f in fails)


def test_llm03_counter_trend_context_missing():
    # regime·consensus 대표어는 넣되 역행 맥락만 누락 → alignment counter_trend 실패로 격리
    text = "상승 전환 관찰 신호가 나타나며 약한 긍정으로 해석됩니다."
    fails = _text_failures(text, regime=Regime.BULLISH_REVERSAL_WATCH,
                           consensus=Consensus.WEAK_POSITIVE, alignment=AlignmentFlag.COUNTER_TREND)
    assert any(f.reason == "missing_required" for f in fails)


def test_llm04_target_price_forbidden():
    fails = _text_failures("과열 구간이며 목표가는 90,000원입니다.")
    assert any(f.reason == "forbidden_term" and f.info == "목표가" for f in fails)


def test_llm05_buy_forbidden():
    fails = _text_failures("과열 국면으로 매수 관점입니다.")
    assert any(f.reason == "forbidden_term" and f.info == "매수" for f in fails)


def test_llm06_evasive_missing_representative():
    fails = _text_failures("현재 시장은 흥미로운 국면입니다.", regime=Regime.SIDEWAYS)
    assert any(f.reason == "missing_required" for f in fails)


def test_llm07_cross_check_not_misjudged():
    # "상승 전환 관찰"은 downtrend의 충돌어지만, 현재 라벨(bullish) 사전만 검사하므로 통과해야 한다.
    assert check_label("상승 전환 관찰 신호가 나타납니다.",
                       REGIME_RULES[Regime.BULLISH_REVERSAL_WATCH]) is None
    fails = _text_failures("상승 전환 관찰 신호가 나타나며 약한 긍정으로 해석됩니다.",
                           regime=Regime.BULLISH_REVERSAL_WATCH,
                           consensus=Consensus.WEAK_POSITIVE, alignment=AlignmentFlag.NEUTRAL)
    assert fails == []


def test_neutral_alignment_representative_not_flagged():
    # 중립 대표 표현 안의 "정합"·"역행"은 무효화되어 충돌로 잡히지 않는다(§5.3 규칙 3).
    assert check_label("정합/역행 판정 대상 아님", ALIGNMENT_RULES[AlignmentFlag.NEUTRAL]) is None


def test_forbidden_term_in_negation_still_fails():
    # 부정문 안이어도 금지어 등장 자체가 실패(§5.3 규칙 5).
    assert contains_forbidden_terms("매수 신호는 아닙니다.") == ["매수"]


# ── 지표별 detail 왜곡 (DETAIL-01~05) ───────────────────────────────────────
def test_detail01_signal_distortion():
    fails = evaluate_details(
        [{"indicator": "moving_average", "detail": "이동평균선은 부정적입니다."}],
        signals=[(MA, Signal.POSITIVE)],
    )
    assert any(f.reason.startswith("conflict") for f in fails)


def test_detail02_neutral_signal_distortion():
    fails = evaluate_details(
        [{"indicator": "rsi", "detail": "RSI는 과매수라 부정적입니다."}],
        signals=[(RSI, Signal.NEUTRAL)],
    )
    assert any(f.reason.startswith("conflict") for f in fails)


def test_detail03_count_mismatch():
    signals = [(MA, Signal.POSITIVE), (RSI, Signal.NEUTRAL), (VOL, Signal.NEUTRAL),
               (SR, Signal.NEUTRAL), (PAT, Signal.NEUTRAL)]
    details = [{"indicator": i.value, "detail": "설명"} for i, _ in signals[:4]]
    fails = evaluate_details(details, signals=signals)
    assert any(f.reason == "count_mismatch" for f in fails)


def test_detail04_indicator_code_mismatch():
    fails = evaluate_details(
        [{"indicator": "ma", "detail": "이동평균 설명"}],
        signals=[(MA, Signal.POSITIVE)],
    )
    reasons = {f.reason for f in fails}
    assert "indicator_mismatch" in reasons
    assert "indicator_missing" in reasons


def test_detail05_invented_indicator():
    fails = evaluate_details(
        [{"indicator": "moving_average", "detail": "이동평균 설명"},
         {"indicator": "macd", "detail": "MACD 설명"}],
        signals=[(MA, Signal.POSITIVE)],
    )
    reasons = {f.reason for f in fails}
    assert "count_mismatch" in reasons
    assert "indicator_mismatch" in reasons


def test_valid_detail_passes():
    fails = evaluate_details(
        [{"indicator": "moving_average",
          "detail": "20일선이 60일선을 상향 돌파해 긍정 신호가 관찰됩니다."}],
        signals=[(MA, Signal.POSITIVE)],
    )
    assert fails == []


# ── 확정값 재생성 필드 (§5.2 조건 5) ────────────────────────────────────────
def test_forbidden_output_field_top_level():
    result = evaluate(
        {"interpretation_text": "과열 국면입니다.", "details": [], "signal_score": 0.3},
        final_regime=Regime.OVERHEATED, consensus=Consensus.WEAK_POSITIVE,
        alignment_flag=AlignmentFlag.NEUTRAL, signals=[],
    )
    assert not result.passed
    assert any(f.reason == "forbidden_output_field" and f.info == "signal_score"
               for f in result.failures)


def test_forbidden_output_field_in_detail():
    result = evaluate(
        {"interpretation_text": "과열, 약한 긍정.",
         "details": [{"indicator": "moving_average", "detail": "설명", "signal": "negative"}]},
        final_regime=Regime.OVERHEATED, consensus=Consensus.WEAK_POSITIVE,
        alignment_flag=AlignmentFlag.NEUTRAL, signals=[(MA, Signal.POSITIVE)],
    )
    assert any(f.reason == "forbidden_output_field" and f.info == "signal"
               for f in result.failures)


# ── 정상 통과 ────────────────────────────────────────────────────────────────
def test_full_valid_output_passes():
    output = {
        "interpretation_text": "현재는 과열 국면이며 약한 긍정으로 해석됩니다. "
                               "거래량 확인이 약해 신호 강도는 제한적입니다. "
                               "이 내용은 참고 정보입니다.",
        "details": [
            {"indicator": "moving_average", "detail": "이동평균선 기준 긍정 신호가 관찰됩니다."},
            {"indicator": "rsi", "detail": "RSI는 중립 구간입니다."},
        ],
    }
    result = evaluate(
        output, final_regime=Regime.OVERHEATED, consensus=Consensus.WEAK_POSITIVE,
        alignment_flag=AlignmentFlag.NEUTRAL,
        signals=[(MA, Signal.POSITIVE), (RSI, Signal.NEUTRAL)],
    )
    assert result.passed, result.failures


def test_failed_indicators_property():
    result = evaluate(
        {"interpretation_text": "과열, 약한 긍정, 참고 정보.",
         "details": [
             {"indicator": "moving_average", "detail": "이동평균선은 부정적입니다."},
             {"indicator": "rsi", "detail": "RSI는 중립 구간입니다."},
         ]},
        final_regime=Regime.OVERHEATED, consensus=Consensus.WEAK_POSITIVE,
        alignment_flag=AlignmentFlag.NEUTRAL,
        signals=[(MA, Signal.POSITIVE), (RSI, Signal.NEUTRAL)],
    )
    assert result.failed_indicators == frozenset({"moving_average"})
