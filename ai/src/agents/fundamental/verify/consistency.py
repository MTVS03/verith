from __future__ import annotations

from typing import Any

from ..normalize.standardize import MetricValue

BALANCE_IDENTITY_FAILED_PREFIX = "VERIFY_BALANCE_IDENTITY_FAILED_"
EPS_MISMATCH_FLAG = "CONSISTENCY_EPS_MISMATCH"
EPS_SKIPPED_PERIOD_MISMATCH = "CONSISTENCY_EPS_SKIPPED_PERIOD_MISMATCH"


def is_consistency_flag(flag: str) -> bool:
    return flag.startswith(BALANCE_IDENTITY_FAILED_PREFIX) or flag == EPS_MISMATCH_FLAG


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


def validate_eps_consistency(
    ratios: dict[str, Any],
    insights: dict[str, Any],
    reprt_code: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    """사업보고서 기준 계산 EPS와 배당 공시 EPS를 대조한다."""
    eps_item = ratios.get("eps") or {}
    calculated_eps = eps_item.get("value")
    dividend = insights.get("dividend") or {}
    dart_eps = dividend.get("dart_eps")
    if calculated_eps is None or dart_eps is None:
        return [], []

    if reprt_code != "11011":
        return [], [
            {
                "code": EPS_SKIPPED_PERIOD_MISMATCH,
                "reason": "계산 EPS와 배당 공시 EPS의 기준 기간이 달라 대조를 건너뜁니다.",
                "reprt_code": reprt_code,
                "calculated_eps": calculated_eps,
                "dart_eps": dart_eps,
            }
        ]

    tolerance = max(abs(float(dart_eps)) * 0.05, 1.0)
    difference = abs(float(calculated_eps) - float(dart_eps))
    note = {
        "code": "CONSISTENCY_EPS_MATCH" if difference <= tolerance else EPS_MISMATCH_FLAG,
        "reprt_code": reprt_code,
        "calculated_eps": calculated_eps,
        "dart_eps": dart_eps,
        "difference": round(difference, 4),
        "tolerance": round(tolerance, 4),
        "source_endpoint": dividend.get("source_endpoint", "alotMatter"),
        "rcept_no": dividend.get("rcept_no", ""),
    }
    if difference > tolerance:
        return [EPS_MISMATCH_FLAG], [note]
    return [], [note]
