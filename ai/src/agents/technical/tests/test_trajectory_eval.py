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
    ConfidenceLevel,
    Consensus,
    IndicatorType,
    Regime,
    RiskFlag,
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
                       REGIME_RULES[Regime.BULLISH_REVERSAL_WATCH]) == []
    fails = _text_failures("상승 전환 관찰 신호가 나타나며 약한 긍정으로 해석됩니다.",
                           regime=Regime.BULLISH_REVERSAL_WATCH,
                           consensus=Consensus.WEAK_POSITIVE, alignment=AlignmentFlag.NEUTRAL)
    assert fails == []


def test_neutral_alignment_representative_not_flagged():
    # 중립 대표 표현 안의 "정합"·"역행"은 무효화되어 충돌로 잡히지 않는다(§5.3 규칙 3).
    assert check_label("정합/역행 판정 대상 아님", ALIGNMENT_RULES[AlignmentFlag.NEUTRAL]) == []


def test_forbidden_term_in_negation_still_fails():
    # 부정문 안이어도 금지어 등장 자체가 실패(§5.3 규칙 5).
    assert contains_forbidden_terms("매수 신호는 아닙니다.") == ["매수"]


def test_verify_strips_markdown_before_matching():
    # 핵심 조건 bold(**...**) 허용 — verify 는 별표 제거 plain text 로 검사한다.
    # ① 대표 표현이 **로 감싸여 쪼개져도 매칭돼야 한다(missing_required 안 뜸).
    assert check_label("현재 **약한 긍정**으로 해석됩니다.",
                       REGIME_RULES[Regime.BULLISH_REVERSAL_WATCH]) is not None
    from src.agents.technical.observability.keyword_rules import LabelRule
    rule = LabelRule(required_any=["지지 구간"], conflict_any=[], require_representative=True)
    assert check_label("**지지 구간** 근접", rule) == []          # 부분 bold 도 통과
    # ② 금지어를 bold 로 감싸도 여전히 잡힌다(우회 불가).
    assert contains_forbidden_terms("**매수** 추천") == ["매수", "추천"]


# ── 지표별 detail 왜곡 (DETAIL-01~05) ───────────────────────────────────────
def test_detail01_signal_distortion():
    fails = evaluate_details(
        [{"indicator": "moving_average", "detail": "이동평균선은 부정적입니다."}],
        signals=[(MA, Signal.POSITIVE)],
    )
    assert any(f.reason.startswith("conflict") for f in fails)


def test_detail02_neutral_signal_distortion():
    # neutral인데 "부정적" 방향 서술 → 대표어 "중립" 부재로 실패(missing_required).
    fails = evaluate_details(
        [{"indicator": "rsi", "detail": "RSI는 과매수라 부정적입니다."}],
        signals=[(RSI, Signal.NEUTRAL)],
    )
    assert any(f.reason == "missing_required" for f in fails)


def test_detail06_positive_reversal_by_phrase():
    # 정확 단어(부정적)가 아니라 반전 서술(부정 신호)도 잡아야 한다.
    fails = evaluate_details(
        [{"indicator": "moving_average", "detail": "하락 흐름이며 부정 신호입니다."}],
        signals=[(MA, Signal.POSITIVE)],
    )
    assert any(f.reason == "conflict:부정" for f in fails)


def test_detail07_neutral_strong_positive():
    fails = evaluate_details(
        [{"indicator": "rsi", "detail": "강한 긍정 신호입니다."}],
        signals=[(RSI, Signal.NEUTRAL)],
    )
    assert any(f.reason == "conflict:강한 긍정" for f in fails)


def test_detail08_negative_positive_word():
    fails = evaluate_details(
        [{"indicator": "volume", "detail": "상승 흐름이며 긍정 신호입니다."}],
        signals=[(VOL, Signal.NEGATIVE)],
    )
    assert any(f.reason == "conflict:긍정" for f in fails)


def test_valid_neutral_negation_phrase_passes():
    # "긍정도 부정도 아닌 중립"은 방향 단정이 아니므로 통과해야 한다(오탐 방지).
    fails = evaluate_details(
        [{"indicator": "rsi", "detail": "긍정도 부정도 아닌 중립 구간입니다."}],
        signals=[(RSI, Signal.NEUTRAL)],
    )
    assert fails == []


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


# ── confidence 왜곡 (CONF-01·02) ────────────────────────────────────────────
def test_conf01_low_but_high_claim():
    fails = evaluate_text(
        "과열 국면이며 약한 긍정입니다. 신뢰도가 높으며 확실합니다.",
        final_regime=Regime.OVERHEATED, consensus=Consensus.WEAK_POSITIVE,
        alignment_flag=AlignmentFlag.NEUTRAL, confidence_level=ConfidenceLevel.LOW,
    )
    reasons = {f.reason for f in fails}
    assert "conflict:신뢰도가 높" in reasons  # 신뢰도 반대 라벨 단정
    assert "forbidden_term" in reasons         # "확실합니다"


def test_conf02_high_but_low_claim():
    fails = evaluate_text(
        "과열 국면이며 약한 긍정입니다. 신뢰도가 낮습니다.",
        final_regime=Regime.OVERHEATED, consensus=Consensus.WEAK_POSITIVE,
        alignment_flag=AlignmentFlag.NEUTRAL, confidence_level=ConfidenceLevel.HIGH,
    )
    assert any(f.reason.startswith("conflict") for f in fails)


def test_confidence_medium_no_check():
    fails = evaluate_text(
        "과열 국면이며 약한 긍정입니다. 신뢰도는 보통입니다.",
        final_regime=Regime.OVERHEATED, consensus=Consensus.WEAK_POSITIVE,
        alignment_flag=AlignmentFlag.NEUTRAL, confidence_level=ConfidenceLevel.MEDIUM,
    )
    assert fails == []


# ── risk 누락 (RISK-MENTION-01·02) ──────────────────────────────────────────
def test_risk_omission_fails():
    fails = evaluate_text(
        "과열 국면이며 약한 긍정입니다.",  # 위험 요인 언급 전무
        final_regime=Regime.OVERHEATED, consensus=Consensus.WEAK_POSITIVE,
        alignment_flag=AlignmentFlag.NEUTRAL, risk_flags=[RiskFlag.VOLUME_NOT_CONFIRMED],
    )
    assert any(f.reason == "risk_not_mentioned" for f in fails)


def test_risk_mention_passes():
    fails = evaluate_text(
        "과열 국면이며 약한 긍정입니다. 거래량 확인이 약해 신호 강도는 제한적입니다.",
        final_regime=Regime.OVERHEATED, consensus=Consensus.WEAK_POSITIVE,
        alignment_flag=AlignmentFlag.NEUTRAL, risk_flags=[RiskFlag.VOLUME_NOT_CONFIRMED],
    )
    assert fails == []


# ── 금지어 확장 (FORBID-01·02·03) ───────────────────────────────────────────
def test_forbidden_terms_expanded():
    assert contains_forbidden_terms("이 종목을 추천합니다.") == ["추천"]
    assert contains_forbidden_terms("목표 가격은 999,999원입니다.") == ["목표 가격"]
    assert contains_forbidden_terms("상승할 가능성이 높습니다.") == ["상승할 가능성"]


# ── 중첩 확정값 필드 (EXTRA-01) ─────────────────────────────────────────────
def test_nested_forbidden_output_field():
    result = evaluate(
        {"interpretation_text": "과열, 약한 긍정.", "details": [],
         "extra": {"signal_score": 1.0, "final_regime": "uptrend_intact"}},
        final_regime=Regime.OVERHEATED, consensus=Consensus.WEAK_POSITIVE,
        alignment_flag=AlignmentFlag.NEUTRAL, signals=[],
    )
    assert not result.passed
    infos = {f.info for f in result.failures if f.reason == "forbidden_output_field"}
    assert "signal_score" in infos and "final_regime" in infos


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
