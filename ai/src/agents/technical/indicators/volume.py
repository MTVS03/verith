"""거래량·거래대금 기본 계산.

입력은 내부 표준 `OHLCV` 시퀀스(과거→최신 오름차순)라고 가정한다.
평균·비율 원천값만 계산하고 `low_liquidity` 등 리스크 판정은 하지 않는다(그건 risk 단계).

정책:
  - 반환 리스트는 항상 입력과 같은 길이. 창 미충족 앞 구간은 None.
  - 평균은 현재 봉 포함 직전 window개 단순평균.
  - volume_ratio = 현재 거래량 / 평균 거래량. 평균이 None이거나 0이면 None.
  - 빈 입력이면 빈 리스트.
  - KIS/Redis/DB/LLM을 호출하지 않는다.

정본: `config.md §1` (VOLUME_AVG_WINDOW).
"""

from __future__ import annotations

from collections.abc import Sequence

from ..config import VOLUME_AVG_WINDOW
from ..schemas.ohlcv import OHLCV


def _trailing_average(values: Sequence[float], window: int) -> list[float | None]:
    """현재 포함 직전 window개 단순평균. 앞 구간·window<=0은 None."""
    n = len(values)
    if window <= 0:
        return [None] * n
    result: list[float | None] = [None] * n
    for i in range(window - 1, n):
        result[i] = sum(values[i - window + 1 : i + 1]) / window
    return result


def calculate_volume_average(
    ohlcv: Sequence[OHLCV], window: int = VOLUME_AVG_WINDOW
) -> list[float | None]:
    """거래량 이동평균."""
    return _trailing_average([float(bar.volume) for bar in ohlcv], window)


def calculate_trading_value_average(
    ohlcv: Sequence[OHLCV], window: int = VOLUME_AVG_WINDOW
) -> list[float | None]:
    """거래대금 이동평균."""
    return _trailing_average([float(bar.trading_value) for bar in ohlcv], window)


def calculate_volume_ratio(
    ohlcv: Sequence[OHLCV], window: int = VOLUME_AVG_WINDOW
) -> list[float | None]:
    """현재 거래량 / 평균 거래량. 평균이 None이거나 0이면 None(0 나눗셈 방지)."""
    volumes = [float(bar.volume) for bar in ohlcv]
    averages = _trailing_average(volumes, window)
    result: list[float | None] = [None] * len(volumes)
    for i, avg in enumerate(averages):
        if avg is None or avg == 0:
            continue
        result[i] = volumes[i] / avg
    return result
