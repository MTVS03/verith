"""이동평균(SMA)·볼린저밴드 계산.

입력은 내부 표준 `OHLCV` 시퀀스(과거→최신 오름차순, date는 ISO)라고 가정한다.
지표 원천값만 계산하고 신호 라벨(positive/negative)·국면(regime)은 만들지 않는다.

정책:
  - 반환 리스트는 항상 입력과 같은 길이. 계산 불가능한 앞 구간(창 미충족)은 None.
  - 빈 입력이면 빈 리스트를 반환한다(예외로 죽이지 않음).
  - 표준편차는 **모집단 표준편차(ddof=0)** — 볼린저밴드 표준 관례.
  - KIS/Redis/DB/LLM을 호출하지 않는다.

정본: `config.md §1` (MA_WINDOWS·BOLLINGER_PERIOD·BOLLINGER_STD).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from ..config import BOLLINGER_PERIOD, BOLLINGER_STD, MA_WINDOWS
from ..schemas.ohlcv import OHLCV


class BollingerBandRow(TypedDict):
    middle: float | None
    upper: float | None
    lower: float | None


def calculate_sma(values: Sequence[float], window: int) -> list[float | None]:
    """단순이동평균. 각 index에서 직전 window개(현재 포함) 평균. 앞 구간은 None.

    window<=0이면 계산이 불가능하므로 전 구간 None을 반환한다.
    """
    n = len(values)
    if window <= 0:
        return [None] * n
    result: list[float | None] = [None] * n
    for i in range(window - 1, n):
        window_slice = values[i - window + 1 : i + 1]
        result[i] = sum(window_slice) / window
    return result


def calculate_moving_averages(ohlcv: Sequence[OHLCV]) -> dict[int, list[float | None]]:
    """MA_WINDOWS(5·20·60) 각각의 종가 SMA를 {window: 시계열}로 반환한다."""
    closes = [float(bar.close) for bar in ohlcv]
    return {window: calculate_sma(closes, window) for window in MA_WINDOWS}


def calculate_bollinger_bands(ohlcv: Sequence[OHLCV]) -> list[BollingerBandRow]:
    """볼린저밴드(middle·upper·lower)를 봉마다 계산. 앞 구간은 세 값 모두 None.

    middle = 종가 SMA(BOLLINGER_PERIOD), 밴드폭 = BOLLINGER_STD × 모집단 표준편차(ddof=0).
    """
    closes = [float(bar.close) for bar in ohlcv]
    n = len(closes)
    result: list[BollingerBandRow] = [
        {"middle": None, "upper": None, "lower": None} for _ in range(n)
    ]
    if BOLLINGER_PERIOD <= 0:
        return result
    for i in range(BOLLINGER_PERIOD - 1, n):
        window_slice = closes[i - BOLLINGER_PERIOD + 1 : i + 1]
        middle = sum(window_slice) / BOLLINGER_PERIOD
        variance = sum((price - middle) ** 2 for price in window_slice) / BOLLINGER_PERIOD
        std = variance ** 0.5
        result[i] = {
            "middle": middle,
            "upper": middle + BOLLINGER_STD * std,
            "lower": middle - BOLLINGER_STD * std,
        }
    return result
