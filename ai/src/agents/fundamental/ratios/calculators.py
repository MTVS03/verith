from __future__ import annotations

from typing import Any

from ..core.contract import Evidence, EvidenceAccount
from ..data.regular_disclosure import ShareCountData
from ..normalize.standardize import MetricValue

RATIO_META = {
    "roe": {"label": "ROE", "category": "수익성", "unit": "%"},
    "operating_margin": {"label": "영업이익률", "category": "수익성", "unit": "%"},
    "net_margin": {"label": "순이익률", "category": "수익성", "unit": "%"},
    "debt_ratio": {"label": "부채비율", "category": "안정성", "unit": "%"},
    "current_ratio": {"label": "유동비율", "category": "안정성", "unit": "%"},
    "revenue_growth": {"label": "매출성장률", "category": "성장성", "unit": "%"},
    "operating_income_growth": {"label": "영업이익성장률", "category": "성장성", "unit": "%"},
    "eps": {"label": "EPS", "category": "밸류 기초", "unit": "원"},
    "bps": {"label": "BPS", "category": "밸류 기초", "unit": "원"},
}

MISSING_REASONS = {
    "roe": "당기순이익 또는 자본총계가 누락되었거나 자본총계가 0 이하라 ROE를 왜곡 없이 계산할 수 없습니다.",
    "operating_margin": "매출액 또는 영업이익 계정이 누락되어 영업이익률을 계산하지 않았습니다.",
    "net_margin": "매출액 또는 당기순이익 계정이 누락되어 순이익률을 계산하지 않았습니다.",
    "debt_ratio": "부채총계 또는 자본총계가 누락되었거나 자본총계가 0 이하라 부채비율을 계산하지 않았습니다.",
    "current_ratio": "유동자산 또는 유동부채 계정이 누락되어 유동비율을 계산하지 않았습니다.",
    "revenue_growth": "당기 또는 전기 매출액이 누락되었거나 전기 매출액이 0 이하라 성장률을 %로 산출하지 않았습니다.",
    "operating_income_growth": "전기 영업이익이 0 이하이거나 필수 계정이 누락되어 흑자전환/적자지속 가능성을 % 성장률로 강제 표현하지 않았습니다.",
    "eps": "DART 원문에서 보통주 기본 EPS 계정을 안정적으로 식별하지 못해 추정하지 않았습니다.",
    "bps": "DART 주식의 총수 현황에서 발행주식수를 안정적으로 확보하지 못해 총자본 기준 BPS를 산출하지 않았습니다.",
}


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    if denominator < 0:
        return None
    return numerator / denominator * 100


def _metric_value(metrics: dict[str, MetricValue], key: str) -> float | None:
    item = metrics.get(key)
    return item.value if item else None


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def yoy(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    if previous < 0:
        return None
    if current < 0:
        return None
    return round((current - previous) / abs(previous) * 100, 2)


def _growth_status(current: float | None, previous: float | None) -> tuple[str, str | None, str | None]:
    if current is None or previous in (None, 0):
        return "unavailable", None, None
    if previous < 0:
        if current > 0:
            return "not_meaningful", "전기 적자에서 당기 흑자로 전환되어 성장률을 %로 표시하지 않습니다.", "turnaround_positive"
        return "not_meaningful", "전기 적자 또는 음수 기준이라 성장률을 %로 표시하지 않습니다.", "loss_continued"
    if current < 0:
        return "not_meaningful", "전기 흑자에서 당기 적자로 전환되어 성장률을 %로 표시하지 않습니다.", "turnaround_negative"
    return "available", None, None


def _source_url(rcept_no: str) -> str:
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


def _account_evidence(item: MetricValue | None, role: str) -> EvidenceAccount | None:
    if item is None:
        return None
    return EvidenceAccount(
        account_id=item.account_id,
        account_nm=item.account_nm,
        sj_div=item.sj_div,
        amount=item.value,
        currency=item.currency,
        role=role,
        fiscal_year=item.fiscal_year,
        rcept_no=item.rcept_no,
        source_url=_source_url(item.rcept_no),
    )


def _share_count_evidence(share_count: ShareCountData, fiscal_year: str) -> EvidenceAccount:
    return EvidenceAccount(
        account_id=f"{share_count.source_endpoint}:{share_count.source_field}",
        account_nm="발행주식수",
        sj_div="SHARES",
        amount=share_count.issued_shares,
        currency="shares",
        role="share_count",
        fiscal_year=fiscal_year,
        rcept_no=share_count.rcept_no,
        source_url=_source_url(share_count.rcept_no),
    )


def _compact_accounts(accounts: list[EvidenceAccount | None]) -> list[EvidenceAccount]:
    return [account for account in accounts if account is not None]


def calculate_ratios(
    yearly_metrics: dict[str, dict[str, MetricValue]],
    share_count: ShareCountData | None = None,
) -> tuple[dict[str, Any], list[Evidence], list[str]]:
    years = sorted(yearly_metrics)
    latest_year = years[-1] if years else ""
    previous_year = years[-2] if len(years) >= 2 else None
    latest = yearly_metrics.get(latest_year, {})
    previous = yearly_metrics.get(previous_year, {}) if previous_year else {}
    risk_flags: list[str] = []

    revenue = _metric_value(latest, "revenue")
    operating_income = _metric_value(latest, "operating_income")
    profit_loss = _metric_value(latest, "profit_loss")
    equity = _metric_value(latest, "equity")
    liabilities = _metric_value(latest, "liabilities")
    current_assets = _metric_value(latest, "current_assets")
    current_liabilities = _metric_value(latest, "current_liabilities")

    revenue_growth_status, revenue_growth_reason, revenue_growth_direction = _growth_status(revenue, _metric_value(previous, "revenue"))
    operating_income_growth_status, operating_income_growth_reason, operating_income_growth_direction = _growth_status(
        operating_income,
        _metric_value(previous, "operating_income"),
    )

    values = {
        "roe": _round(_safe_ratio(profit_loss, equity)),
        "operating_margin": _round(_safe_ratio(operating_income, revenue)),
        "net_margin": _round(_safe_ratio(profit_loss, revenue)),
        "debt_ratio": _round(_safe_ratio(liabilities, equity)),
        "current_ratio": _round(_safe_ratio(current_assets, current_liabilities)),
        "revenue_growth": yoy(revenue, _metric_value(previous, "revenue")),
        "operating_income_growth": yoy(operating_income, _metric_value(previous, "operating_income")),
        "eps": _metric_value(latest, "basic_eps"),
        "bps": _round(equity / share_count.issued_shares) if equity and share_count else None,
    }
    status_overrides = {
        "revenue_growth": revenue_growth_status,
        "operating_income_growth": operating_income_growth_status,
    }
    reason_overrides = {
        "revenue_growth": revenue_growth_reason,
        "operating_income_growth": operating_income_growth_reason,
    }
    direction_overrides = {
        "revenue_growth": revenue_growth_direction,
        "operating_income_growth": operating_income_growth_direction,
    }
    display_overrides = {
        "revenue_growth": (
            "흑자전환"
            if revenue_growth_direction == "turnaround_positive"
            else "적자전환"
            if revenue_growth_direction == "turnaround_negative"
            else None
        ),
        "operating_income_growth": (
            "흑자전환"
            if operating_income_growth_direction == "turnaround_positive"
            else "적자전환"
            if operating_income_growth_direction == "turnaround_negative"
            else None
        ),
    }
    if latest.get("liabilities") and latest["liabilities"].account_id.startswith("derived:"):
        risk_flags.append("DERIVED_LIABILITIES")

    evidence: list[Evidence] = []
    metric_sources: dict[str, tuple[tuple[str, str, str], ...]] = {
        "roe": (("profit_loss", "numerator", "latest"), ("equity", "denominator", "latest")),
        "operating_margin": (("operating_income", "numerator", "latest"), ("revenue", "denominator", "latest")),
        "net_margin": (("profit_loss", "numerator", "latest"), ("revenue", "denominator", "latest")),
        "debt_ratio": (("liabilities", "numerator", "latest"), ("equity", "denominator", "latest")),
        "current_ratio": (("current_assets", "numerator", "latest"), ("current_liabilities", "denominator", "latest")),
        "revenue_growth": (("revenue", "current", "latest"), ("revenue", "previous", "previous")),
        "operating_income_growth": (
            ("operating_income", "current", "latest"),
            ("operating_income", "previous", "previous"),
        ),
        "eps": (("basic_eps", "source_value", "latest"),),
        "bps": (("equity", "equity", "latest"),),
    }
    for metric, value in values.items():
        status = status_overrides.get(metric, "available" if value is not None else "unavailable")
        if value is None and status == "unavailable":
            risk_flags.append(f"MISSING_{metric.upper()}")
            continue
        if value is None and status == "not_meaningful":
            risk_flags.append(f"NOT_MEANINGFUL_{metric.upper()}")
            continue
        source_specs = metric_sources.get(metric)
        if source_specs is None:
            continue
        accounts = _compact_accounts(
            [
                _account_evidence(
                    latest.get(key) if period == "latest" else previous.get(key),
                    role,
                )
                for key, role, period in source_specs
            ]
        )
        if metric == "bps" and share_count is not None:
            accounts.append(_share_count_evidence(share_count, latest_year))
        if not accounts:
            continue
        primary = accounts[0]
        evidence.append(
            Evidence(
                claim=f"{metric} {value}",
                metric=metric,
                value=float(value),
                unit=RATIO_META[metric]["unit"],
                fiscal_year=latest_year,
                rcept_no=primary.rcept_no or "",
                account_ids=[account.account_id for account in accounts],
                accounts=accounts,
                source_url=primary.source_url or _source_url(primary.rcept_no or ""),
            )
        )

    ratios = {}
    for metric, value in values.items():
        meta = RATIO_META[metric]
        status = status_overrides.get(metric, "available" if value is not None else "unavailable")
        item = {
            "label": meta["label"],
            "category": meta["category"],
            "value": value,
            "unit": meta["unit"],
            "fiscal_year": latest_year,
            "status": status,
        }
        if value is None:
            item["reason"] = reason_overrides.get(metric) or MISSING_REASONS[metric]
        if display_overrides.get(metric):
            item["display_value"] = display_overrides[metric]
        if direction_overrides.get(metric):
            item["direction"] = direction_overrides[metric]
        if metric == "bps" and value is not None and share_count is not None:
            item["basis"] = share_count.basis
            item["share_class"] = share_count.share_class
            item["issued_shares"] = share_count.issued_shares
            item["distributed_shares"] = share_count.distributed_shares
            item["treasury_shares"] = share_count.treasury_shares
            item["source_endpoint"] = share_count.source_endpoint
            item["source_field"] = share_count.source_field
        ratios[metric] = item
    return ratios, evidence, risk_flags
