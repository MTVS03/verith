"""멀티프레임 보정 — 주/월봉 추세와 alignment_flag·regime_context 계산.

`regime_rules.md §2`의 코드 구현이다. LLM·KIS·DB·Redis를 쓰지 않는다.

핵심 규약:
  - final_regime은 일봉 라벨 그대로. 조합 라벨("상승 중 단기 과열" 등)을 만들지 않는다.
  - 상위 추세 맥락은 라벨이 아니라 alignment_flag·regime_context로만 표현한다.
  - 기준 상위 추세는 월봉 우선, 월봉 unavailable이면 주봉 대체.
  - 중립 국면(overheated / oversold_rebound_watch / sideways / unavailable)은 상위 추세와 무관하게 alignment=neutral.
  - 상위 추세가 sideways/unavailable이면 neutral.
  - regime_context는 코드 생성 고정 템플릿 문장(LLM 아님, 투자 권유 표현 없음).

contracts.RegimeResult는 여기서 조립하지 않는다(supervisor 단계 몫). 로컬 dataclass로 반환한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..config import (
    MIN_MONTHLY_BARS,
    MIN_WEEKLY_BARS,
    TREND_SIDEWAYS_THRESHOLD_PCT,
    TREND_SLOPE_LOOKBACK,
)
from ..schemas.enums import AlignmentFlag, Regime, Trend
from ..schemas.ohlcv import OHLCV

# 일봉 regime 성격 (enums.md §1 성격 열). 방향성 계열만 alignment 판정 대상.
_POSITIVE_REGIMES = frozenset({Regime.BULLISH_REVERSAL_WATCH, Regime.UPTREND_INTACT})
_NEGATIVE_REGIMES = frozenset({Regime.DOWNTREND})

_TREND_LABEL = {Trend.UP: "상승", Trend.DOWN: "하락", Trend.SIDEWAYS: "횡보"}


@dataclass(frozen=True)
class MultiframeRegimeResult:
    daily_regime: Regime
    final_regime: Regime
    weekly_trend: Trend
    monthly_trend: Trend
    alignment_flag: AlignmentFlag
    regime_context: str


def compute_trend(ohlcv: Sequence[OHLCV], min_bars: int) -> Trend:
    """상위 타임프레임 추세를 변화율로 판정한다.

    slope_pct = (최신 종가 − TREND_SLOPE_LOOKBACK봉 전 종가) / 그 종가.
    +밴드 초과 up / −밴드 미만 down / 밴드 이내 sideways.
    봉 수 부족(min_bars 미만)이거나 기준 종가가 0이면 unavailable.
    """
    if len(ohlcv) < min_bars or len(ohlcv) <= TREND_SLOPE_LOOKBACK:
        return Trend.UNAVAILABLE
    latest_close = float(ohlcv[-1].close)
    past_close = float(ohlcv[-1 - TREND_SLOPE_LOOKBACK].close)
    if past_close == 0:
        return Trend.UNAVAILABLE
    slope_pct = (latest_close - past_close) / past_close
    if slope_pct > TREND_SIDEWAYS_THRESHOLD_PCT:
        return Trend.UP
    if slope_pct < -TREND_SIDEWAYS_THRESHOLD_PCT:
        return Trend.DOWN
    return Trend.SIDEWAYS


def _alignment_and_context(
    daily_regime: Regime, weekly_trend: Trend, monthly_trend: Trend
) -> tuple[AlignmentFlag, str]:
    """일봉 국면 성격 + 기준 상위 추세로 alignment_flag와 regime_context를 만든다."""
    is_positive = daily_regime in _POSITIVE_REGIMES
    is_negative = daily_regime in _NEGATIVE_REGIMES

    # 중립 국면: 상위 추세와 무관하게 neutral
    if not is_positive and not is_negative:
        return (
            AlignmentFlag.NEUTRAL,
            "방향성이 없는 중립 국면이라 상위 추세와의 정합/역행을 판정하지 않습니다.",
        )

    # 기준 상위 추세 선택 (월봉 우선 → 주봉 대체)
    if monthly_trend != Trend.UNAVAILABLE:
        reference, ref_name, use_weekly = monthly_trend, "월봉", False
    elif weekly_trend != Trend.UNAVAILABLE:
        reference, ref_name, use_weekly = weekly_trend, "주봉", True
    else:
        return (
            AlignmentFlag.NEUTRAL,
            "상위 타임프레임(주봉·월봉) 데이터가 부족해 상위 추세를 판정하지 않습니다.",
        )

    # 기준 추세가 횡보면 방향성 판정 안 함
    if reference == Trend.SIDEWAYS:
        return (
            AlignmentFlag.NEUTRAL,
            f"상위 추세({ref_name})가 횡보라 방향성 정합/역행을 판정하지 않습니다.",
        )

    # 기준 추세 up/down → 정합/역행
    dir_word = _TREND_LABEL[reference]
    aligned = (is_positive and reference == Trend.UP) or (is_negative and reference == Trend.DOWN)
    flag = AlignmentFlag.ALIGNED if aligned else AlignmentFlag.COUNTER_TREND
    polarity = "긍정" if is_positive else "부정"

    if use_weekly:
        prefix = f"월봉 데이터가 없어 주봉 추세({dir_word})를 상위 기준으로 사용합니다. "
    else:
        prefix = f"상위 추세(월봉 {dir_word}) 기준. "

    if aligned:
        body = "일봉 국면과 방향이 일치합니다(정합)."
    else:
        body = f"일봉의 {polarity} 신호는 상위 추세와 역행합니다."

    context = prefix + body

    # 월봉 기준일 때 주봉이 엇갈리면 보조 맥락 추가 (월봉 우선 판정)
    if not use_weekly and weekly_trend not in (Trend.UNAVAILABLE, monthly_trend):
        context += f" (주봉은 {_TREND_LABEL[weekly_trend]}로 월봉과 엇갈립니다 — 월봉 기준 판정.)"

    return flag, context


def analyze_multiframe(
    daily_regime: Regime,
    weekly_ohlcv: Sequence[OHLCV],
    monthly_ohlcv: Sequence[OHLCV],
) -> MultiframeRegimeResult:
    """일봉 regime + 주/월봉 OHLCV → 멀티프레임 결과(추세·alignment·context)."""
    weekly_trend = compute_trend(weekly_ohlcv, MIN_WEEKLY_BARS)
    monthly_trend = compute_trend(monthly_ohlcv, MIN_MONTHLY_BARS)
    alignment_flag, regime_context = _alignment_and_context(
        daily_regime, weekly_trend, monthly_trend
    )
    return MultiframeRegimeResult(
        daily_regime=daily_regime,
        final_regime=daily_regime,  # 조합 라벨 없음 — 일봉 라벨 그대로
        weekly_trend=weekly_trend,
        monthly_trend=monthly_trend,
        alignment_flag=alignment_flag,
        regime_context=regime_context,
    )
