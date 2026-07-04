"""synthesis 단위테스트 (SYN-*, test_plan.md §3.1). 외부 호출 없음, 코드 확정값만 검증."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.technical.config import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_WEIGHTS,
    INDICATOR_WEIGHTS,
    MIN_AVG_VOLUME,
    RSI_OVERBOUGHT,
    SIGNAL_STRONG,
    SIGNAL_WEAK,
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
from src.agents.technical.schemas.ohlcv import OHLCV
from src.agents.technical.synthesis.confidence import (
    classify_confidence_level,
    compute_agreement,
    compute_confidence,
    compute_conflict_absence,
    compute_trend_clarity,
    compute_volume_confirm,
)
from src.agents.technical.synthesis.risk import detect_risks
from src.agents.technical.synthesis.signal_score import (
    IndicatorSignalResult,
    SignalScoreResult,
    aggregate_signal_score,
    classify_consensus,
    compute_signal_score,
    moving_average_signal,
    pattern_signal,
    rsi_signal,
    support_resistance_signal,
    volume_signal,
)

SYNTHESIS_DIR = Path(__file__).resolve().parent.parent / "synthesis"


def candle(is_bullish=False, is_bearish=False, body=1.0, lower_wick=0.0, upper_wick=0.0):
    return {"body": body, "upper_wick": upper_wick, "lower_wick": lower_wick,
            "is_bullish": is_bullish, "is_bearish": is_bearish}


def isr(indicator: IndicatorType, signal: Signal) -> IndicatorSignalResult:
    return IndicatorSignalResult(indicator=indicator, signal=signal, value=None,
                                 metrics=[], weight=INDICATOR_WEIGHTS[indicator.value])


def make_result(*pairs) -> SignalScoreResult:
    signals = [isr(it, s) for it, s in pairs]
    score, consensus = aggregate_signal_score(signals)
    return SignalScoreResult(signals, score, consensus)


# ── signal_score ──────────────────────────────────────────────────────────────
def test_indicator_weights_sum_to_one():
    assert abs(sum(INDICATOR_WEIGHTS.values()) - 1.0) < 1e-9


def test_moving_average_signal_rule():
    assert moving_average_signal(110, 105, 100) == Signal.POSITIVE   # close>20MA & 5MA>20MA
    assert moving_average_signal(90, 95, 100) == Signal.NEGATIVE     # close<20MA & 5MA<20MA
    assert moving_average_signal(110, 95, 100) == Signal.NEUTRAL     # 혼재
    assert moving_average_signal(110, None, 100) is None             # 제외


def test_rsi_signal_rule():
    assert rsi_signal(60) == Signal.POSITIVE
    assert rsi_signal(40) == Signal.NEGATIVE
    assert rsi_signal(75) == Signal.NEUTRAL      # 극단(>=70)
    assert rsi_signal(30) == Signal.NEUTRAL      # 극단(<=35)
    assert rsi_signal(50) == Signal.NEUTRAL      # 정중앙
    assert rsi_signal(None) is None              # 제외


def test_volume_signal_rule():
    assert volume_signal(100, 105, 1.2) == Signal.POSITIVE   # 상승봉 + ratio>=1
    assert volume_signal(105, 100, 1.2) == Signal.NEGATIVE   # 하락봉 + ratio>=1
    assert volume_signal(100, 105, 0.5) == Signal.NEUTRAL    # ratio<1 미확인
    assert volume_signal(None, 105, 1.2) == Signal.NEUTRAL   # prev 없음


def test_support_resistance_signal_rule():
    assert support_resistance_signal(100.0, 100.0, 200.0) == Signal.POSITIVE  # 지지 근처
    assert support_resistance_signal(200.0, 100.0, 200.0) == Signal.NEGATIVE  # 저항 근처
    assert support_resistance_signal(150.0, 100.0, 200.0) == Signal.NEUTRAL   # 사이
    assert support_resistance_signal(150.0, None, None) is None               # 제외


def test_pattern_signal_rule():
    assert pattern_signal(candle(is_bullish=True)) == Signal.POSITIVE
    assert pattern_signal(candle(is_bearish=True)) == Signal.NEGATIVE
    assert pattern_signal(candle(body=0.0)) == Signal.NEUTRAL  # 도지


def test_signal_encoding_and_renormalization():
    # 단일 지표 positive → 재정규화로 score=1.0
    assert make_result((IndicatorType.MOVING_AVERAGE, Signal.POSITIVE)).signal_score == 1.0
    assert make_result((IndicatorType.PATTERN, Signal.NEGATIVE)).signal_score == -1.0
    # 혼재: ma(0.3,+1)+rsi(0.2,-1) → (0.3-0.2)/0.5 = 0.2
    mixed = make_result((IndicatorType.MOVING_AVERAGE, Signal.POSITIVE),
                        (IndicatorType.RSI, Signal.NEGATIVE))
    assert mixed.signal_score == pytest.approx(0.2)


def test_all_excluded_is_zero_neutral():
    score, consensus = aggregate_signal_score([])
    assert score == 0.0 and consensus == Consensus.NEUTRAL


def test_consensus_boundaries_inclusive():
    assert classify_consensus(SIGNAL_STRONG) == Consensus.STRONG_POSITIVE   # 0.5 포함
    assert classify_consensus(SIGNAL_WEAK) == Consensus.WEAK_POSITIVE       # 0.3 포함
    assert classify_consensus(0.29) == Consensus.NEUTRAL
    assert classify_consensus(-SIGNAL_WEAK) == Consensus.WEAK_NEGATIVE      # -0.3 포함
    assert classify_consensus(-SIGNAL_STRONG) == Consensus.STRONG_NEGATIVE  # -0.5 포함


def test_signal_score_within_range():
    result = make_result((IndicatorType.MOVING_AVERAGE, Signal.POSITIVE),
                         (IndicatorType.RSI, Signal.NEGATIVE),
                         (IndicatorType.VOLUME, Signal.NEUTRAL))
    assert -1.0 <= result.signal_score <= 1.0


def test_compute_signal_score_returns_intermediate_not_contracts():
    bars = [OHLCV(date="2026-01-01", open=i, high=i + 1, low=i - 1, close=i,
                  volume=100_000 + i, trading_value=2_000_000_000 + i) for i in range(1, 61)]
    result = compute_signal_score(bars)
    assert isinstance(result, SignalScoreResult)
    assert all(isinstance(s, IndicatorSignalResult) for s in result.technical_signals)
    # detail·detail_source는 이 단계에서 만들지 않는다
    assert not hasattr(result.technical_signals[0], "detail")


# ── confidence ────────────────────────────────────────────────────────────────
def test_confidence_weights_sum_to_one():
    assert abs(sum(CONFIDENCE_WEIGHTS.values()) - 1.0) < 1e-9


def test_agreement_all_same_direction_is_one():
    r = make_result((IndicatorType.MOVING_AVERAGE, Signal.POSITIVE),
                    (IndicatorType.RSI, Signal.POSITIVE))
    assert compute_agreement(r) == pytest.approx(1.0)


def test_agreement_all_neutral_is_zero():
    r = make_result((IndicatorType.VOLUME, Signal.NEUTRAL),
                    (IndicatorType.PATTERN, Signal.NEUTRAL))
    assert compute_agreement(r) == 0.0


def test_volume_confirm_clamp():
    assert compute_volume_confirm(1.5) == 1.0
    assert compute_volume_confirm(0.5) == 0.5
    assert compute_volume_confirm(None) == 0.0


def test_trend_clarity_rules():
    assert compute_trend_clarity(Regime.UPTREND_INTACT, AlignmentFlag.ALIGNED) == 1.0
    assert compute_trend_clarity(Regime.DOWNTREND, AlignmentFlag.COUNTER_TREND) == 0.3
    assert compute_trend_clarity(Regime.UPTREND_INTACT, AlignmentFlag.NEUTRAL) == 0.6
    assert compute_trend_clarity(Regime.SIDEWAYS, AlignmentFlag.ALIGNED) == 0.0
    assert compute_trend_clarity(Regime.OVERHEATED, AlignmentFlag.NEUTRAL) == 0.0


def test_conflict_absence_lowers_on_conflict():
    conflict = make_result((IndicatorType.MOVING_AVERAGE, Signal.POSITIVE),   # 0.30
                           (IndicatorType.SUPPORT_RESISTANCE, Signal.NEGATIVE))  # 0.20
    assert compute_conflict_absence(conflict) == pytest.approx(1.0 - 2 * 0.20)  # 0.6
    one_way = make_result((IndicatorType.MOVING_AVERAGE, Signal.POSITIVE))
    assert compute_conflict_absence(one_way) == 1.0


def test_confidence_range_and_level_boundaries():
    r = make_result((IndicatorType.MOVING_AVERAGE, Signal.POSITIVE))
    c = compute_confidence(r, volume_ratio=1.0, final_regime=Regime.UPTREND_INTACT,
                           alignment_flag=AlignmentFlag.ALIGNED)
    assert 0.0 <= c.confidence <= 1.0
    assert classify_confidence_level(CONFIDENCE_HIGH) == ConfidenceLevel.HIGH
    assert classify_confidence_level(CONFIDENCE_MEDIUM) == ConfidenceLevel.MEDIUM
    assert classify_confidence_level(CONFIDENCE_MEDIUM - 0.01) == ConfidenceLevel.LOW


# ── risk ──────────────────────────────────────────────────────────────────────
def _base_kwargs():
    return dict(close=150.0, support=100.0, resistance=200.0, rsi=55.0,
                final_regime=Regime.UPTREND_INTACT, alignment_flag=AlignmentFlag.ALIGNED,
                volume_ratio=1.5, avg_volume=1_000_000.0, avg_trading_value=5_000_000_000.0)


def _flags(items):
    return {i.flag for i in items}


def test_volume_not_confirmed():
    r = make_result((IndicatorType.MOVING_AVERAGE, Signal.POSITIVE))
    kw = {**_base_kwargs(), "volume_ratio": 0.5}
    assert RiskFlag.VOLUME_NOT_CONFIRMED in _flags(detect_risks(r, **kw))


def test_near_resistance_with_ref_price():
    r = make_result((IndicatorType.RSI, Signal.NEUTRAL))
    kw = {**_base_kwargs(), "close": 200.0}
    items = detect_risks(r, **kw)
    hit = [i for i in items if i.flag == RiskFlag.NEAR_RESISTANCE]
    assert hit and hit[0].ref_price == 200.0


def test_near_support_with_ref_price():
    r = make_result((IndicatorType.RSI, Signal.NEUTRAL))
    kw = {**_base_kwargs(), "close": 100.0}
    items = detect_risks(r, **kw)
    hit = [i for i in items if i.flag == RiskFlag.NEAR_SUPPORT]
    assert hit and hit[0].ref_price == 100.0


def test_mixed_signals():
    r = make_result((IndicatorType.MOVING_AVERAGE, Signal.POSITIVE),
                    (IndicatorType.RSI, Signal.NEGATIVE))
    assert RiskFlag.MIXED_SIGNALS in _flags(detect_risks(r, **_base_kwargs()))


def test_overheated_momentum():
    r = make_result((IndicatorType.RSI, Signal.NEUTRAL))
    kw = {**_base_kwargs(), "rsi": float(RSI_OVERBOUGHT)}
    assert RiskFlag.OVERHEATED_MOMENTUM in _flags(detect_risks(r, **kw))
    kw2 = {**_base_kwargs(), "rsi": 50.0, "final_regime": Regime.OVERHEATED}
    assert RiskFlag.OVERHEATED_MOMENTUM in _flags(detect_risks(r, **kw2))


def test_counter_higher_trend():
    r = make_result((IndicatorType.RSI, Signal.NEUTRAL))
    kw = {**_base_kwargs(), "alignment_flag": AlignmentFlag.COUNTER_TREND}
    assert RiskFlag.COUNTER_HIGHER_TREND in _flags(detect_risks(r, **kw))


def test_low_liquidity():
    r = make_result((IndicatorType.RSI, Signal.NEUTRAL))
    kw = {**_base_kwargs(), "avg_volume": float(MIN_AVG_VOLUME - 1)}
    assert RiskFlag.LOW_LIQUIDITY in _flags(detect_risks(r, **kw))


def test_risk_notes_not_empty():
    r = make_result((IndicatorType.MOVING_AVERAGE, Signal.POSITIVE),
                    (IndicatorType.RSI, Signal.NEGATIVE))
    kw = {**_base_kwargs(), "close": 100.0, "volume_ratio": 0.5,
          "alignment_flag": AlignmentFlag.COUNTER_TREND, "final_regime": Regime.OVERHEATED,
          "avg_volume": 1.0}
    items = detect_risks(r, **kw)
    assert items and all(i.note.strip() for i in items)


# ── 범위 보호 ─────────────────────────────────────────────────────────────────
def test_no_buy_sell_in_source():
    forbidden = ["매수", "매도", "사라", "팔아", "손절", "목표가"]
    for path in SYNTHESIS_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not [w for w in forbidden if w in text], f"{path.name} 매수/매도 표현"


def test_no_external_dependency_imports():
    banned = ["httpx", "redis", "requests", "openai", "psycopg", "sqlalchemy", "langchain"]
    for path in SYNTHESIS_DIR.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith(("import ", "from ")):
                assert not any(pkg in s for pkg in banned), f"{path.name}: {s}"
