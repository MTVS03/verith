"""캔들 기본 특징 계산.

입력은 내부 표준 `OHLCV` 시퀀스(과거→최신 오름차순)라고 가정한다.
봉 하나하나의 몸통·꼬리·양봉/음봉 원천값만 계산한다.

정책:
  - 컵앤핸들·박스권·돌파 등 차트 패턴을 확정하지 않는다(그건 charts 단계).
  - 긍정/부정 신호나 투자 권유 표현을 만들지 않는다.
  - 반환 리스트는 입력과 같은 길이. 각 봉은 OHLC가 모두 있으므로 값에 None이 없다.
  - 종가=시가(도지)면 is_bullish·is_bearish 둘 다 False.
  - 빈 입력이면 빈 리스트.
  - KIS/Redis/DB/LLM을 호출하지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from ..schemas.ohlcv import OHLCV


class CandleFeatureRow(TypedDict):
    body: float
    upper_wick: float
    lower_wick: float
    is_bullish: bool
    is_bearish: bool


def calculate_candle_features(ohlcv: Sequence[OHLCV]) -> list[CandleFeatureRow]:
    """봉별 body·upper_wick·lower_wick·is_bullish·is_bearish를 계산한다."""
    result: list[CandleFeatureRow] = []
    for bar in ohlcv:
        open_price = float(bar.open)
        close_price = float(bar.close)
        high_price = float(bar.high)
        low_price = float(bar.low)
        body_top = max(open_price, close_price)
        body_bottom = min(open_price, close_price)
        result.append(
            {
                "body": abs(close_price - open_price),
                "upper_wick": high_price - body_top,
                "lower_wick": body_bottom - low_price,
                "is_bullish": close_price > open_price,
                "is_bearish": close_price < open_price,
            }
        )
    return result
