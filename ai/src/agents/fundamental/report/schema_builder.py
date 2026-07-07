from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid5, NAMESPACE_URL

from ..core.contract import Evidence


def _report_id(trace_id: str, ticker: str, bsns_year: int, reprt_code: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"verith:fundamental:{trace_id}:{ticker}:{bsns_year}:{reprt_code}"))


def _evidence_id(report_id: str, metric: str, rcept_no: str, account_id: str, role: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"{report_id}:{metric}:{rcept_no}:{account_id}:{role}"))


def _ratio_id(report_id: str, ratio_name: str, bsns_year: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"{report_id}:{ratio_name}:{bsns_year}"))


def _decimal(value: float | int | None) -> str | None:
    if value is None:
        return None
    decimal_value = Decimal(str(value))
    if decimal_value == decimal_value.to_integral_value():
        return str(decimal_value.quantize(Decimal("1")))
    return format(decimal_value.normalize(), "f")


def _trend_decimal(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float | int):
        return _decimal(value)
    return None


def _ratio_formula(metric: str) -> str:
    formulas = {
        "roe": "profit_loss / equity * 100",
        "operating_margin": "operating_income / revenue * 100",
        "net_margin": "profit_loss / revenue * 100",
        "debt_ratio": "liabilities / equity * 100",
        "current_ratio": "current_assets / current_liabilities * 100",
        "revenue_growth": "(current_revenue - previous_revenue) / previous_revenue * 100",
        "operating_income_growth": "(current_operating_income - previous_operating_income) / previous_operating_income * 100",
        "eps": "dart_basic_eps",
        "bps": "equity / issued_shares",
    }
    return formulas.get(metric, "deterministic_calculator")


def _evidence_role(metric: str, index: int) -> str:
    roles = {
        "roe": ("numerator", "denominator"),
        "operating_margin": ("numerator", "denominator"),
        "net_margin": ("numerator", "denominator"),
        "debt_ratio": ("numerator", "denominator"),
        "current_ratio": ("numerator", "denominator"),
        "revenue_growth": ("current", "previous"),
        "operating_income_growth": ("current", "previous"),
        "eps": ("source_value",),
        "bps": ("equity", "share_count"),
    }
    values = roles.get(metric, ("source_value",))
    return values[index] if index < len(values) else "support"


def _currency(unit: str) -> str:
    return "KRW" if unit == "원" else unit


def _trend_label(metric: str) -> tuple[str, str, str]:
    labels = {
        "revenue": ("매출액", "추세", "원"),
        "op_income": ("영업이익", "추세", "원"),
        "roe": ("ROE", "추세", "%"),
    }
    return labels.get(metric, (metric, "추세", ""))


def build_erd_payload(
    *,
    request_id: str,
    trace_id: str,
    ticker: str,
    corp_name: str,
    corp_code: str,
    bsns_year: int,
    fs_div: str,
    reprt_code: str,
    verdict: str,
    confidence: float,
    score: int,
    label: str,
    ratios: dict[str, Any],
    evidence: list[Evidence],
    trend: dict[str, Any] | None = None,
    interpretation: str,
    interpretation_source: str,
    risk_flags: list[str],
    verification: dict[str, Any],
    retrieval_summary: dict[str, Any],
) -> dict[str, Any]:
    """PostgreSQL ERD에 맞춘 저장용 payload를 만든다.

    이 함수는 DB에 쓰지 않는다. 백엔드가 그대로 매핑할 수 있는 구조만 고정한다.
    """
    created_at = datetime.now(timezone.utc).isoformat()
    report_id = _report_id(trace_id, ticker, bsns_year, reprt_code)
    report_ratios: list[dict[str, Any]] = []
    report_evidence: list[dict[str, Any]] = []
    ratio_ids: dict[str, str] = {}

    for metric, item in ratios.items():
        ratio_id = _ratio_id(report_id, metric, bsns_year)
        ratio_ids[metric] = ratio_id
        report_ratios.append(
            {
                "id": ratio_id,
                "report_id": report_id,
                "ratio_name": metric,
                "bsns_year": int(item.get("fiscal_year") or bsns_year),
                "fiscal_year": int(item.get("fiscal_year") or bsns_year),
                "value": item.get("value"),
                "unit": item.get("unit"),
                "label": item.get("label", metric),
                "category": item.get("category"),
                "display_value": item.get("display_value"),
                "formula": _ratio_formula(metric),
                "status": item.get("status", "available"),
                "reason": item.get("reason"),
                "basis": item.get("basis"),
            }
        )

    trend = trend or {}
    years = [str(year) for year in trend.get("years", [])]
    for trend_metric in ("revenue", "op_income", "roe"):
        values = trend.get(trend_metric, [])
        label, category, unit = _trend_label(trend_metric)
        for year, value in zip(years, values, strict=False):
            if _trend_decimal(value) is None:
                continue
            year_int = int(year)
            if trend_metric in ratio_ids and year_int == bsns_year:
                continue
            ratio_id = _ratio_id(report_id, trend_metric, year_int)
            ratio_ids[f"{trend_metric}:{year}"] = ratio_id
            report_ratios.append(
                {
                    "id": ratio_id,
                    "report_id": report_id,
                    "ratio_name": trend_metric,
                    "bsns_year": year_int,
                    "fiscal_year": year_int,
                    "value": _trend_decimal(value),
                    "unit": unit,
                    "label": label,
                    "category": category,
                    "display_value": None,
                    "formula": _ratio_formula(trend_metric),
                    "status": "available",
                    "reason": None,
                    "basis": {"source": "trend"},
                }
            )

    for item in evidence:
        ratio_id = ratio_ids.get(item.metric) or _ratio_id(report_id, item.metric, int(item.fiscal_year))
        if item.accounts:
            for account in item.accounts:
                account_rcept_no = account.rcept_no or item.rcept_no
                account_year = int(account.fiscal_year or item.fiscal_year)
                role = account.role
                report_evidence.append(
                    {
                        "id": _evidence_id(report_id, item.metric, account_rcept_no, account.account_id, role),
                        "ratio_id": ratio_id,
                        "rcept_no": account_rcept_no,
                        "bsns_year": account_year,
                        "sj_div": account.sj_div,
                        "account_id": account.account_id,
                        "account_nm": account.account_nm,
                        "amount": _decimal(account.amount),
                        "currency": _currency(account.currency),
                        "role": role,
                        "source_url": account.source_url or item.source_url,
                    }
                )
            continue
        for index, account_id in enumerate(item.account_ids):
            report_evidence.append(
                {
                    "id": _evidence_id(report_id, item.metric, item.rcept_no, account_id, _evidence_role(item.metric, index)),
                    "ratio_id": ratio_id,
                    "rcept_no": item.rcept_no,
                    "bsns_year": int(item.fiscal_year),
                    "sj_div": "",
                    "account_id": account_id,
                    "account_nm": "",
                    "amount": _decimal(item.value),
                    "currency": _currency(item.unit),
                    "role": _evidence_role(item.metric, index),
                    "source_url": item.source_url,
                }
            )

    data_status = "normal" if not risk_flags else "partial_with_flags"
    return {
        "stock": {
            "stock_code": ticker,
            "stock_name": corp_name,
        },
        "fundamental_report": {
            "id": report_id,
            "request_id": request_id,
            "stock_code": ticker,
            "corp_code": corp_code,
            "bsns_year": bsns_year,
            "fs_div": fs_div,
            "reprt_code": reprt_code,
            "verdict": verdict,
            "verdict_label": label,
            "confidence": confidence,
            "fin_score": score,
            "data_status": data_status,
            "risk_flags": risk_flags,
            "trace_id": trace_id,
            "as_of": created_at,
            "created_at": created_at,
        },
        "report_ratios": report_ratios,
        "report_evidence": report_evidence,
        "report_interpretation": {
            "id": str(uuid5(NAMESPACE_URL, f"{report_id}:interpretation")),
            "report_id": report_id,
            "interpretation": interpretation,
            "interpretation_source": interpretation_source,
        },
        "report_verification": {
            "id": str(uuid5(NAMESPACE_URL, f"{report_id}:verification")),
            "report_id": report_id,
            "binding_passed": bool(verification.get("binding_passed", True)),
            "consistency_passed": bool(verification.get("consistency_passed", True)),
            "verdict_stable": bool(verification.get("verdict_stable", True)),
            "outcome": str(verification.get("outcome", "passed")),
            "regen_count": int(verification.get("regen_count", 0)),
        },
        "retrieval_summary": retrieval_summary,
    }
