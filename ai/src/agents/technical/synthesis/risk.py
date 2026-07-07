"""risk item 산출 — 코드가 확정하는 리스크 관찰점.

정본: `config.md §6.1`, `enums.md §7`. flag는 코드 확정, note는 **코드 템플릿**(LLM 아님).
note는 짧은 사실 서술 톤이며 투자 권유 표현을 쓰지 않는다. near_support/near_resistance는
위험 경고가 아니라 관찰 지점이므로 중립적으로 서술한다.
"""

from __future__ import annotations

from ..config import (
    MIN_AVG_TRADING_VALUE,
    MIN_AVG_VOLUME,
    NEAR_RESISTANCE_THRESHOLD_PCT,
    NEAR_SUPPORT_THRESHOLD_PCT,
    RSI_OVERBOUGHT,
)
from ..schemas.contracts import RiskItem
from ..schemas.enums import AlignmentFlag, Regime, RiskFlag, Signal
from .signal_score import SignalScoreResult

# 코드 템플릿 note (짧고 중립적, 투자 권유 표현 없음)
_RISK_NOTES = {
    RiskFlag.VOLUME_NOT_CONFIRMED: "거래량 확인이 충분하지 않습니다.",
    RiskFlag.NEAR_RESISTANCE: "저항 후보 가격대에 근접해 있습니다.",
    RiskFlag.NEAR_SUPPORT: "지지 후보 가격대에 근접해 있습니다.",
    RiskFlag.MIXED_SIGNALS: "지표 간 방향성이 엇갈립니다.",
    RiskFlag.OVERHEATED_MOMENTUM: "단기 모멘텀이 과열 구간에 있습니다.",
    RiskFlag.COUNTER_HIGHER_TREND: "상위 추세와 단기 국면이 엇갈립니다.",
    RiskFlag.LOW_LIQUIDITY: "평균 거래 규모가 기준보다 낮습니다.",
}


def _near(close: float, level: float | None, pct: float) -> bool:
    if level is None or level == 0:
        return False
    return abs(close - level) / level <= pct


def detect_risks(
    signal_result: SignalScoreResult,
    *,
    close: float,
    support: float | None,
    resistance: float | None,
    rsi: float | None,
    final_regime: Regime,
    alignment_flag: AlignmentFlag,
    volume_ratio: float | None,
    avg_volume: float | None,
    avg_trading_value: float | None,
) -> list[RiskItem]:
    """조건을 만족하는 risk flag를 고정 순서로 RiskItem 리스트로 반환한다."""
    signals = [r.signal for r in signal_result.technical_signals]
    has_positive = Signal.POSITIVE in signals
    has_negative = Signal.NEGATIVE in signals
    has_directional = has_positive or has_negative

    items: list[RiskItem] = []

    if has_directional and (volume_ratio is None or volume_ratio < 1):
        items.append(_item(RiskFlag.VOLUME_NOT_CONFIRMED))

    if _near(close, resistance, NEAR_RESISTANCE_THRESHOLD_PCT):
        items.append(_item(RiskFlag.NEAR_RESISTANCE, ref_price=resistance))

    if _near(close, support, NEAR_SUPPORT_THRESHOLD_PCT):
        items.append(_item(RiskFlag.NEAR_SUPPORT, ref_price=support))

    if has_positive and has_negative:
        items.append(_item(RiskFlag.MIXED_SIGNALS))

    if (rsi is not None and rsi >= RSI_OVERBOUGHT) or final_regime == Regime.OVERHEATED:
        items.append(_item(RiskFlag.OVERHEATED_MOMENTUM))

    if alignment_flag == AlignmentFlag.COUNTER_TREND:
        items.append(_item(RiskFlag.COUNTER_HIGHER_TREND))

    low_volume = avg_volume is not None and avg_volume < MIN_AVG_VOLUME
    low_value = avg_trading_value is not None and avg_trading_value < MIN_AVG_TRADING_VALUE
    if low_volume or low_value:
        items.append(_item(RiskFlag.LOW_LIQUIDITY))

    return items


def _item(flag: RiskFlag, *, ref_price: float | None = None) -> RiskItem:
    return RiskItem(flag=flag, note=_RISK_NOTES[flag], ref_price=ref_price)
