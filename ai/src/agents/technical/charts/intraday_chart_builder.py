"""1d 장중 분봉 차트 빌더 (chart_annotation_spec §3.1, Beta).

입력은 **이미 정규화된** `list[IntradayCandle]`(+`previous_close`)이다. KIS 호출·OHLC 재계산은
하지 않는다(candles를 그대로 쓰고 파생값만 계산). D/W/M `build_chart_payloads`(chart_builder.py)와
분리된 **별도 경로**이며, 공식 `charts` 편입(supervisor 조립)은 아직 하지 않는다 — 이 함수는
`period="1d"`/`candle_unit="1min"` ChartPayload 하나를 생성할 뿐이다.

v1 필수: candles·day_high/low·previous_close·short_ma. (volume은 candles[].volume로 표현.)
VWAP·intraday RSI는 선택이라 계산하지 않고 `IntradayChartData` 기본값(빈 배열)으로 둔다.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..schemas.contracts import ChartPayload
from ..schemas.enums import ChartPeriod
from ..schemas.intraday import IntradayCandle, IntradayChartData, IntradayPoint

# 분봉 단기 MA(봉 수). 정식 config화(config.md)는 후속 커밋 — 지금은 builder-local 명명 상수.
DEFAULT_INTRADAY_SHORT_MA_WINDOW = 5


def build_intraday_chart_payload(
    candles: Sequence[IntradayCandle],
    *,
    previous_close: float | None = None,
    short_ma_window: int = DEFAULT_INTRADAY_SHORT_MA_WINDOW,
) -> ChartPayload:
    """`list[IntradayCandle]` → period="1d"/candle_unit="1min" ChartPayload.

    day_high/low는 candles의 high/low에서, short_ma는 close 단순이동평균에서 산출한다.
    candles가 비면 day_high/low=None·short_ma=[]로 안전 생성한다(장시작 전·휴장 등).
    """
    candles = list(candles)
    day_high = max((c.high for c in candles), default=None)
    day_low = min((c.low for c in candles), default=None)
    chart_data = IntradayChartData(
        candle_unit="1min",
        candles=candles,
        previous_close=previous_close,
        day_high=day_high,
        day_low=day_low,
        short_ma=_short_ma_points(candles, short_ma_window),
    )
    return ChartPayload(period=ChartPeriod.ONE_DAY, chart_data=chart_data)


def _short_ma_points(candles: list[IntradayCandle], window: int) -> list[IntradayPoint]:
    """close 단순이동평균(window 봉). 확보분(window번째 봉)부터 각 시각에 1점."""
    if window <= 0 or len(candles) < window:
        return []
    points: list[IntradayPoint] = []
    for i in range(window - 1, len(candles)):
        avg = sum(c.close for c in candles[i - window + 1 : i + 1]) / window
        points.append(IntradayPoint(timestamp=candles[i].timestamp, value=avg))
    return points
