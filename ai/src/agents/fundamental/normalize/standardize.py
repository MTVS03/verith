from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .account_mapper import canonical_metric


@dataclass
class MetricValue:
    value: float
    fiscal_year: str
    rcept_no: str
    account_id: str
    account_nm: str
    sj_div: str = ""
    currency: str = "KRW"


def _parse_amount(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _pick_latest(existing: MetricValue | None, candidate: MetricValue) -> MetricValue:
    if existing is None:
        return candidate
    return candidate if candidate.rcept_no > existing.rcept_no else existing


def standardize_year_rows(rows: list[dict[str, Any]], fiscal_year: str) -> dict[str, MetricValue]:
    metrics: dict[str, MetricValue] = {}
    for row in rows:
        canonical = canonical_metric(row)
        if canonical is None:
            continue
        amount = _parse_amount(row.get("thstrm_amount"))
        if amount is None:
            continue
        value = MetricValue(
            value=amount,
            fiscal_year=fiscal_year,
            rcept_no=str(row.get("rcept_no") or ""),
            account_id=str(row.get("account_id") or row.get("account_nm") or canonical),
            account_nm=str(row.get("account_nm") or canonical),
            sj_div=str(row.get("sj_div") or ""),
            currency=str(row.get("currency") or "KRW"),
        )
        metrics[canonical] = _pick_latest(metrics.get(canonical), value)
    if "liabilities" not in metrics and "equity_and_liabilities" in metrics and "equity" in metrics:
        base = metrics["equity_and_liabilities"]
        equity = metrics["equity"]
        metrics["liabilities"] = MetricValue(
            value=base.value - equity.value,
            fiscal_year=fiscal_year,
            rcept_no=base.rcept_no,
            account_id="derived:equity_and_liabilities_minus_equity",
            account_nm="부채총계(자본과부채총계-자본총계)",
            sj_div=base.sj_div or "BS",
            currency=base.currency,
        )
    return metrics
