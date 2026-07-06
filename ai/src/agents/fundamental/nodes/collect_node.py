from __future__ import annotations

from typing import Any

from ..data.corp_code import UnknownStockCodeError, resolve, resolve_name
from ..data.latest_report import discover_latest_report, latest_annual_selection
from ..data.regular_disclosure import fetch_regular_report_insights, fetch_share_count
from ..normalize.standardize import standardize_year_rows
from ..report.period import period_basis
from ..retrieval.source_policy import DartSourceRecord, fetch_financial_statement_rows, summarize_source_records
from ..core.state import FundamentalAgentState


def _needs_insight_fallback(insights: dict[str, Any]) -> bool:
    for value in insights.values():
        if not isinstance(value, dict) or value.get("status") == "unavailable":
            continue
        meaningful = [item for key, item in value.items() if key not in {"rcept_no", "source_endpoint", "status", "reason"}]
        if any(item not in (None, "", "-") for item in meaningful):
            return False
    return True


def _append_source_risk_flags(source_records: list[DartSourceRecord], risk_flags: list[str]) -> None:
    if any(record.reason and record.reason.startswith("refresh_failed") for record in source_records):
        if "STALE_DART_CACHE_FALLBACK" not in risk_flags:
            risk_flags.append("STALE_DART_CACHE_FALLBACK")


def collect_node(state: FundamentalAgentState) -> dict[str, Any]:
    request = state["request"]
    use_cache = state.get("use_cache", True)
    try:
        corp_code = resolve(request.ticker)
        corp_name = request.corp_name or resolve_name(request.ticker)
    except UnknownStockCodeError:
        return {
            "corp_code": "",
            "corp_name": request.corp_name or request.ticker,
            "years": [],
            "fs_div": request.fs_div,
            "reprt_code": "",
            "reprt_name": "",
            "report_mode": request.report_mode,
            "period_basis": {},
            "dart_calls": 0,
            "source_records": [],
            "retrieval_summary": {},
            "risk_flags": ["UNSUPPORTED_TICKER"],
            "yearly_metrics": {},
            "share_count": None,
            "insights": {},
            "data_status": "unsupported_ticker",
            "data_status_reason": "지원하지 않는 종목코드입니다.",
        }

    risk_flags: list[str] = []
    source_records: list[DartSourceRecord] = []
    yearly_metrics = {}
    dart_calls = 0
    fs_div = request.fs_div
    if request.report_mode == "latest":
        selection = discover_latest_report(corp_code, fs_div)
        use_cache = False
        dart_calls += selection.probe_calls
    else:
        selection = latest_annual_selection()

    current_year = selection.bsns_year
    reprt_code = selection.reprt_code
    years = [str(year) for year in range(current_year - request.years + 1, current_year + 1)]

    for year in years:
        result = fetch_financial_statement_rows(
            corp_code,
            int(year),
            reprt_code=reprt_code,
            fs_div=fs_div,
            use_cache=use_cache,
        )
        rows = result.rows
        source_records.append(result.source_record)
        dart_calls += 1
        if not rows and fs_div == "CFS":
            fallback = fetch_financial_statement_rows(
                corp_code,
                int(year),
                reprt_code=reprt_code,
                fs_div="OFS",
                use_cache=use_cache,
            )
            rows = fallback.rows
            source_records.append(fallback.source_record)
            dart_calls += 1
            fs_div = "OFS"
            risk_flags.append("OFS_FALLBACK")
        _append_source_risk_flags(source_records, risk_flags)
        yearly_metrics[year] = standardize_year_rows(rows, year)

    if not any(yearly_metrics.values()):
        return {
            "corp_code": corp_code,
            "corp_name": corp_name,
            "years": years,
            "fs_div": fs_div,
            "reprt_code": reprt_code,
            "reprt_name": selection.reprt_name,
            "report_mode": selection.mode,
            "period_basis": period_basis(years[-1], reprt_code, selection.reprt_name),
            "dart_calls": dart_calls,
            "source_records": source_records,
            "retrieval_summary": summarize_source_records(source_records),
            "risk_flags": risk_flags + ["DART_EMPTY_DATA"],
            "yearly_metrics": yearly_metrics,
            "share_count": None,
            "insights": {},
            "data_status": "empty_data",
            "data_status_reason": "DART에서 계산 가능한 재무제표 행을 찾지 못했습니다.",
        }

    share_count = None
    try:
        share_count = fetch_share_count(corp_code, int(years[-1]), reprt_code=reprt_code, use_cache=use_cache)
        dart_calls += 1
    except Exception:
        share_count = None

    insights, insight_calls = fetch_regular_report_insights(
        corp_code,
        int(years[-1]),
        reprt_code=reprt_code,
        use_cache=use_cache,
    )
    dart_calls += insight_calls
    if reprt_code != "11011" and _needs_insight_fallback(insights):
        annual = latest_annual_selection()
        fallback_insights, fallback_calls = fetch_regular_report_insights(
            corp_code,
            annual.bsns_year,
            reprt_code=annual.reprt_code,
            use_cache=use_cache,
        )
        dart_calls += fallback_calls
        if not _needs_insight_fallback(fallback_insights):
            insights = fallback_insights
            insights["_fallback_source"] = {
                "reprt_code": annual.reprt_code,
                "reprt_name": annual.reprt_name,
                "bsns_year": annual.bsns_year,
                "reason": "interim_report_missing_context",
            }

    return {
        "corp_code": corp_code,
        "corp_name": corp_name,
        "years": years,
        "fs_div": fs_div,
        "reprt_code": reprt_code,
        "reprt_name": selection.reprt_name,
        "report_mode": selection.mode,
        "period_basis": period_basis(years[-1], reprt_code, selection.reprt_name),
        "dart_calls": dart_calls,
        "source_records": source_records,
        "retrieval_summary": summarize_source_records(source_records),
        "risk_flags": risk_flags,
        "yearly_metrics": yearly_metrics,
        "share_count": share_count,
        "insights": insights,
        "data_status": "normal",
    }
