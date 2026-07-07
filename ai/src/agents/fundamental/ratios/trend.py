from typing import Any

from ..normalize.standardize import MetricValue
from .calculators import _safe_ratio


def build_trend(yearly_metrics: dict[str, dict[str, MetricValue]]) -> dict[str, Any]:
    years = sorted(yearly_metrics)
    revenue: list[float | None] = []
    operating_income: list[float | None] = []
    roe: list[float | None] = []
    for year in years:
        metrics = yearly_metrics[year]
        rev = metrics.get("revenue")
        op = metrics.get("operating_income")
        profit = metrics.get("profit_loss")
        equity = metrics.get("equity")
        revenue.append(rev.value if rev else None)
        operating_income.append(op.value if op else None)
        roe_value = _safe_ratio(profit.value if profit else None, equity.value if equity else None)
        roe.append(round(roe_value, 2) if roe_value is not None else None)
    return {"years": years, "revenue": revenue, "op_income": operating_income, "roe": roe}
