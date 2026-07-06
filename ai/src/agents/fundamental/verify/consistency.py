from __future__ import annotations

from ..normalize.standardize import MetricValue

BALANCE_IDENTITY_FAILED_PREFIX = "VERIFY_BALANCE_IDENTITY_FAILED_"


def validate_balance_identity(yearly_metrics: dict[str, dict[str, MetricValue]]) -> list[str]:
    """Check assets ~= liabilities + equity when the required rows exist."""
    flags: list[str] = []
    for year, metrics in yearly_metrics.items():
        assets = metrics.get("assets") or metrics.get("equity_and_liabilities")
        liabilities = metrics.get("liabilities")
        equity = metrics.get("equity")
        if not (assets and liabilities and equity):
            continue
        tolerance = max(abs(assets.value) * 0.0001, 1_000_000)
        if abs(assets.value - (liabilities.value + equity.value)) > tolerance:
            flags.append(f"{BALANCE_IDENTITY_FAILED_PREFIX}{year}")
    return flags
