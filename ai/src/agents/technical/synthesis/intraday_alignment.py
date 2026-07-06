"""intraday 흐름 힌트·정합 분류 helper — 순수 계산(chart_annotation_spec §3.1, Beta).

이미 만들어진 `IntradayContext`와 기존 D/W/M `final_regime`(Regime)만 읽어서:
  - `infer_intraday_regime_hint`  : 장중 흐름 요약 힌트(방향/급변/불가)
  - `classify_regime_alignment`   : D/W/M 국면과 intraday 힌트의 정합(aligned/counter/neutral/unavailable)
  - `apply_intraday_hint_to_context`: 위 둘을 context에 얹은 새 컨텍스트 반환(얇은 조립)

**final_regime 을 바꾸지 않는다**(읽기 전용). confidence/signal_score 실제 보정·risk_notes 생성은
이 파일 범위가 아니다(후속 Phase). KIS 호출 없음.

방향 매핑 정본: `regime_rules.md`(§alignment)·`regime/multiframe.py`(_POSITIVE/_NEGATIVE_REGIMES)와
동일하게 유지한다 — 아래 로컬 집합은 그 정본과 test로 동기화를 강제한다(drift 방지).
"""

from __future__ import annotations

from ..schemas.enums import Regime
from ..schemas.intraday import IntradayContext, IntradayRegimeHint, RegimeAlignment

# ── 방향 분류(정본 동기화: regime_rules.md §alignment / regime.multiframe) ──────
_BULLISH_REGIMES = frozenset({Regime.BULLISH_REVERSAL_WATCH, Regime.UPTREND_INTACT})
_BEARISH_REGIMES = frozenset({Regime.DOWNTREND})
# 나머지(OVERHEATED·OVERSOLD_REBOUND_WATCH·SIDEWAYS)=중립, UNAVAILABLE=판정 불가.

# ── 임계값(명명 상수 — 정식 config화는 후속 config.md) ─────────────────────────
INTRADAY_VOLATILE_RETURN_PCT = 3.0    # |당일 등락률| ≥ 3% → volatile
INTRADAY_VOLATILE_RANGE_PCT = 0.05    # 당일 레인지 폭 ≥ 전일종가 5% → volatile
INTRADAY_DIRECTION_RETURN_PCT = 0.5   # |등락률| ≥ 0.5% 를 방향 1표로 인정
INTRADAY_RANGE_NEAR_HIGH = 0.66       # 레인지 위치 ≥ 0.66 → 상방 1표(고가 근처)
INTRADAY_RANGE_NEAR_LOW = 0.34        # 레인지 위치 ≤ 0.34 → 하방 1표(저가 근처)
INTRADAY_DIRECTION_MIN_AGREEMENT = 2  # 최소 2개 지표 합의해야 방향 확정(단일 값 확정 금지)


def infer_intraday_regime_hint(context: IntradayContext) -> IntradayRegimeHint:
    """장중 흐름 요약 힌트. 보수적 — 값 부족/비정상이면 unavailable, 단일 값으로 방향 확정 안 함."""
    if context.status != "normal":
        return "unavailable"
    ret = context.intraday_return_pct
    trend = context.short_ma_trend
    pos = context.day_range_position
    if ret is None or trend is None or pos is None:  # 핵심 값 부족 → 판단 불가
        return "unavailable"

    range_pct = _range_pct(context)
    if abs(ret) >= INTRADAY_VOLATILE_RETURN_PCT or (
        range_pct is not None and range_pct >= INTRADAY_VOLATILE_RANGE_PCT
    ):
        return "volatile_intraday"

    score = 0
    if ret >= INTRADAY_DIRECTION_RETURN_PCT:
        score += 1
    elif ret <= -INTRADAY_DIRECTION_RETURN_PCT:
        score -= 1
    if trend == "up":
        score += 1
    elif trend == "down":
        score -= 1
    if pos >= INTRADAY_RANGE_NEAR_HIGH:
        score += 1
    elif pos <= INTRADAY_RANGE_NEAR_LOW:
        score -= 1

    if score >= INTRADAY_DIRECTION_MIN_AGREEMENT:
        return "upward_intraday"
    if score <= -INTRADAY_DIRECTION_MIN_AGREEMENT:
        return "downward_intraday"
    return "sideways_intraday"


def classify_regime_alignment(
    final_regime: Regime, intraday_hint: IntradayRegimeHint,
) -> RegimeAlignment:
    """D/W/M final_regime과 intraday 힌트의 정합. 명확한 bullish/bearish 계열만 aligned/counter."""
    if intraday_hint == "unavailable" or final_regime == Regime.UNAVAILABLE:
        return "unavailable"
    if intraday_hint in ("sideways_intraday", "volatile_intraday"):
        return "neutral"  # 방향이 불명확하면 정합 판정하지 않음

    hint_bullish = intraday_hint == "upward_intraday"  # 나머지는 downward_intraday
    if final_regime in _BULLISH_REGIMES:
        return "aligned" if hint_bullish else "counter"
    if final_regime in _BEARISH_REGIMES:
        return "counter" if hint_bullish else "aligned"
    return "neutral"  # 애매한 국면(overheated·oversold_rebound_watch·sideways) → 중립


def apply_intraday_hint_to_context(
    context: IntradayContext, final_regime: Regime,
) -> IntradayContext:
    """hint·alignment를 계산해 context에 얹은 **새 IntradayContext**를 반환한다.

    final_regime은 읽기만 하고 바꾸지 않는다. confidence/signal_score 보정은 하지 않는다(0.0 유지).
    """
    hint = infer_intraday_regime_hint(context)
    alignment = classify_regime_alignment(final_regime, hint)
    return context.model_copy(
        update={"intraday_regime_hint": hint, "regime_alignment": alignment}
    )


def _range_pct(context: IntradayContext) -> float | None:
    """당일 레인지 폭(전일종가 대비). day_high/low·previous_close 없거나 0이면 None."""
    high, low, prev = context.day_high, context.day_low, context.previous_close
    if high is None or low is None or prev is None or prev <= 0:
        return None
    return (high - low) / prev
