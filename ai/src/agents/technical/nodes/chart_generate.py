"""노드 9 — 차트생성. daily/weekly/monthly OHLCV → list[ChartPayload].

얇은 어댑터: `charts/chart_builder.build_chart_payloads`만 호출한다. overlays·subcharts·
annotation 계산과 chart_data 계약(ChartData) 검증은 chart_builder 안에 있으며 노드가 바꾸지 않는다.

chart_builder는 순수 chart JSON만 만든다 — chart_data에 regime/synthesis/risk/technical_signals/
confidence를 넣지 않는다(그 계약을 노드가 깨지 않도록 아무 값도 추가로 주입하지 않는다).
"""

from __future__ import annotations

from collections.abc import Sequence

from ..charts.chart_builder import build_chart_payloads
from ..schemas.contracts import ChartPayload
from ..schemas.ohlcv import OHLCV


def run_chart_generate(
    daily: Sequence[OHLCV],
    weekly: Sequence[OHLCV],
    monthly: Sequence[OHLCV],
) -> list[ChartPayload]:
    """3m/1y/5y ChartPayload를 생성한다. 3m·1y는 일봉, 5y는 주봉 기준(chart_builder 정책)."""
    if not daily:
        raise ValueError("daily OHLCV is required for chart_generate")
    return build_chart_payloads(daily, weekly, monthly)
