"""지지/저항 후보 계산.

입력은 내부 표준 `OHLCV` 시퀀스(과거→최신 오름차순)라고 가정한다.
후보 수치만 계산하고 "지지 근처"·"저항 근처" 판정은 하지 않는다(그건 regime/risk 단계).

정책:
  - 각 index 기준 현재 포함 최근 lookback개 봉의 저가 최솟값을 support 후보,
    고가 최댓값을 resistance 후보로 둔다.
  - 반환 리스트는 항상 입력과 같은 길이. 창 미충족 앞 구간은 support/resistance 모두 None.
  - 빈 입력이면 빈 리스트.
  - KIS/Redis/DB/LLM을 호출하지 않는다.

정본: `config.md §2` (SUPPORT_LOOKBACK_DAYS).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from ..config import SUPPORT_LOOKBACK_DAYS
from ..schemas.ohlcv import OHLCV


class SupportResistanceRow(TypedDict):
    support: float | None
    resistance: float | None


def calculate_support_resistance(
    ohlcv: Sequence[OHLCV], lookback: int = SUPPORT_LOOKBACK_DAYS
) -> list[SupportResistanceRow]:
    """최근 lookback개 봉의 low 최소/high 최대를 지지/저항 후보로 반환한다."""
    lows = [float(bar.low) for bar in ohlcv]
    highs = [float(bar.high) for bar in ohlcv]
    n = len(lows)
    result: list[SupportResistanceRow] = [
        {"support": None, "resistance": None} for _ in range(n)
    ]
    if lookback <= 0:
        return result
    for i in range(lookback - 1, n):
        low_slice = lows[i - lookback + 1 : i + 1]
        high_slice = highs[i - lookback + 1 : i + 1]
        result[i] = {"support": min(low_slice), "resistance": max(high_slice)}
    return result
