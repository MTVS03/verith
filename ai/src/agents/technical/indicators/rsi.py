"""RSI(상대강도지수) 계산 — 와일더(Wilder) 방식.

입력은 내부 표준 `OHLCV` 시퀀스(과거→최신 오름차순)라고 가정한다.
RSI 값만 계산하고 과열/침체 등 국면 라벨은 만들지 않는다 — 그건 regime 단계.

정책:
  - 반환 리스트는 항상 입력과 같은 길이. 첫 유효 RSI는 index=period(변화량 period개 필요),
    그 앞 구간은 None.
  - 값 범위는 0~100.
  - 변화량 특수 케이스: 평균이득>0·평균손실=0 → 100 / 평균이득=0·평균손실>0 → 0 /
    **평균이득=평균손실=0(무변동) → 50**.
  - 빈 입력·데이터 부족(길이 ≤ period)이면 전 구간 None.
  - KIS/Redis/DB/LLM을 호출하지 않는다.

정본: `config.md §1` (RSI_PERIOD).
"""

from __future__ import annotations

from collections.abc import Sequence

from ..config import RSI_PERIOD
from ..schemas.ohlcv import OHLCV


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    """평균 이득/손실 → RSI(0~100). 무변동 등 경계는 docstring 정책을 따른다."""
    if avg_gain == 0 and avg_loss == 0:
        return 50.0
    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_rsi(ohlcv: Sequence[OHLCV], period: int = RSI_PERIOD) -> list[float | None]:
    """와일더 RSI 시계열. 앞 구간은 None, 무변동 구간은 50 정책(모듈 docstring 참고)."""
    closes = [float(bar.close) for bar in ohlcv]
    n = len(closes)
    result: list[float | None] = [None] * n
    if period <= 0 or n <= period:
        return result

    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, n)]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, n)]

    # 시드: 첫 period개 변화량의 단순평균 → index=period 위치의 RSI
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result[period] = _rsi_from_averages(avg_gain, avg_loss)

    # 이후: 와일더 평활 (직전 평균에 가중)
    for i in range(period + 1, n):
        gain = gains[i - 1]
        loss = losses[i - 1]
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        result[i] = _rsi_from_averages(avg_gain, avg_loss)

    return result
