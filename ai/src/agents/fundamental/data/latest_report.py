from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .cache import inspect_cache, load_cached_any_age, save_cache
from ..retrieval.source_policy import DartSourceRecord, fetch_financial_statement_rows


REPORT_CODE_LABELS = {
    "11011": "사업보고서",
    "11013": "1분기보고서",
    "11012": "반기보고서",
    "11014": "3분기보고서",
}


@dataclass(frozen=True)
class ReportSelection:
    bsns_year: int
    reprt_code: str
    reprt_name: str
    mode: str
    probe_calls: int = 0
    probe_records: list[DartSourceRecord] = field(default_factory=list)


LATEST_REPORT_TTL_SECONDS = 60 * 60 * 6


def _latest_report_cache_key(corp_code: str, fs_div: str) -> str:
    return f"latest_report_{corp_code}_{fs_div}"


def _cached_selection(corp_code: str, fs_div: str) -> ReportSelection | None:
    key = _latest_report_cache_key(corp_code, fs_div)
    inspection = inspect_cache(key, ttl_seconds=LATEST_REPORT_TTL_SECONDS)
    if not inspection.exists or not inspection.fresh:
        return None
    payload = load_cached_any_age(key)
    if not isinstance(payload, dict):
        return None
    try:
        return ReportSelection(
            bsns_year=int(payload["bsns_year"]),
            reprt_code=str(payload["reprt_code"]),
            reprt_name=str(payload["reprt_name"]),
            mode=str(payload["mode"]),
            probe_calls=0,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _save_selection(corp_code: str, fs_div: str, selection: ReportSelection) -> None:
    payload: dict[str, Any] = {
        "bsns_year": selection.bsns_year,
        "reprt_code": selection.reprt_code,
        "reprt_name": selection.reprt_name,
        "mode": selection.mode,
    }
    save_cache(_latest_report_cache_key(corp_code, fs_div), payload)


def _probe_record(record: DartSourceRecord) -> DartSourceRecord:
    reason = "latest_report_probe"
    if record.reason:
        reason = f"{reason}:{record.reason}"
    return record.model_copy(update={"reason": reason})


def latest_annual_selection() -> ReportSelection:
    year = datetime.now(timezone.utc).year - 1
    return ReportSelection(
        bsns_year=year,
        reprt_code="11011",
        reprt_name=REPORT_CODE_LABELS["11011"],
        mode="annual",
    )


def discover_latest_report(corp_code: str, fs_div: str) -> ReportSelection:
    """Find the newest DART financial report with usable rows.

    DART financial statements are filing-based, not tick-by-tick real-time data.
    This checks the latest available periodic filing in descending freshness
    order and returns the first report code with financial rows.
    """

    cached = _cached_selection(corp_code, fs_div)
    if cached is not None:
        return cached

    current_year = datetime.now(timezone.utc).year
    candidates = [
        (current_year, "11014"),
        (current_year, "11012"),
        (current_year, "11013"),
        (current_year - 1, "11011"),
        (current_year - 1, "11014"),
        (current_year - 1, "11012"),
        (current_year - 1, "11013"),
    ]
    probe_records: list[DartSourceRecord] = []
    for year, reprt_code in candidates:
        result = fetch_financial_statement_rows(
            corp_code,
            year,
            reprt_code=reprt_code,
            fs_div=fs_div,
            use_cache=False,
        )
        probe_records.append(_probe_record(result.source_record))
        if result.rows:
            selection = ReportSelection(
                bsns_year=year,
                reprt_code=reprt_code,
                reprt_name=REPORT_CODE_LABELS[reprt_code],
                mode="latest",
                probe_calls=len(probe_records),
                probe_records=probe_records,
            )
            _save_selection(corp_code, fs_div, selection)
            return selection
    fallback = latest_annual_selection()
    selection = ReportSelection(
        bsns_year=fallback.bsns_year,
        reprt_code=fallback.reprt_code,
        reprt_name=fallback.reprt_name,
        mode=fallback.mode,
        probe_calls=len(candidates),
        probe_records=probe_records,
    )
    _save_selection(corp_code, fs_div, selection)
    return selection
