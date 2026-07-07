from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from ..data.cache import TTL_SECONDS, inspect_cache, load_cached, load_cached_any_age
from ..data.dart_client import DartApiError, fetch_financials


_DART_REFRESH_ERRORS = (DartApiError, httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError)


SourceKind = Literal["cache", "dart"]
CacheStatus = Literal["hit", "miss", "stale", "bypass"]


class DartSourceRecord(BaseModel):
    endpoint: str
    cache_key: str
    corp_code: str
    bsns_year: int
    reprt_code: str
    fs_div: str
    source: SourceKind
    cache_status: CacheStatus
    row_count: int
    rcept_nos: list[str] = Field(default_factory=list)
    as_of: str
    ttl_seconds: int
    reason: str | None = None


class FinancialFetchResult(BaseModel):
    rows: list[dict[str, Any]]
    source_record: DartSourceRecord


def financial_cache_key(corp_code: str, bsns_year: int, reprt_code: str, fs_div: str) -> str:
    return f"fnltt_{corp_code}_{bsns_year}_{reprt_code}_{fs_div}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rcept_nos(rows: list[dict[str, Any]]) -> list[str]:
    values = {str(row.get("rcept_no") or "") for row in rows}
    return sorted(value for value in values if value)


def _record(
    *,
    corp_code: str,
    bsns_year: int,
    reprt_code: str,
    fs_div: str,
    cache_key: str,
    source: SourceKind,
    cache_status: CacheStatus,
    rows: list[dict[str, Any]],
    reason: str | None = None,
) -> DartSourceRecord:
    return DartSourceRecord(
        endpoint="fnlttSinglAcntAll",
        cache_key=cache_key,
        corp_code=corp_code,
        bsns_year=bsns_year,
        reprt_code=reprt_code,
        fs_div=fs_div,
        source=source,
        cache_status=cache_status,
        row_count=len(rows),
        rcept_nos=_rcept_nos(rows),
        as_of=_now_iso(),
        ttl_seconds=TTL_SECONDS,
        reason=reason,
    )


def fetch_financial_statement_rows(
    corp_code: str,
    bsns_year: int,
    *,
    reprt_code: str,
    fs_div: str,
    use_cache: bool,
) -> FinancialFetchResult:
    """DART 재무제표 원문을 조회하고 캐시/실시간 출처를 함께 반환한다."""
    cache_key = financial_cache_key(corp_code, bsns_year, reprt_code, fs_div)
    inspection = inspect_cache(cache_key)
    cached_any_age: Any | None = None
    if use_cache:
        cached = load_cached(cache_key)
        if cached is not None:
            rows = list(cached)
            return FinancialFetchResult(
                rows=rows,
                source_record=_record(
                    corp_code=corp_code,
                    bsns_year=bsns_year,
                    reprt_code=reprt_code,
                    fs_div=fs_div,
                    cache_key=cache_key,
                    source="cache",
                    cache_status="hit",
                    rows=rows,
                ),
            )
        if inspection.exists:
            cached_any_age = load_cached_any_age(cache_key)
        cache_is_corrupt = inspection.exists and cached_any_age is None
        cache_status: CacheStatus = "stale" if inspection.exists and not cache_is_corrupt else "miss"
        if cache_is_corrupt:
            reason = "cache_corrupt"
        elif inspection.exists and not inspection.fresh:
            reason = "ttl_expired"
        else:
            reason = "no_cache_file"
    else:
        cache_status = "bypass"
        reason = "live_check_requested"

    try:
        rows = fetch_financials(
            corp_code,
            bsns_year,
            reprt_code=reprt_code,
            fs_div=fs_div,
            use_cache=False,
        )
    except _DART_REFRESH_ERRORS as exc:
        stale = cached_any_age if use_cache and inspection.exists else None
        if stale is None:
            raise
        rows = list(stale)
        return FinancialFetchResult(
            rows=rows,
            source_record=_record(
                corp_code=corp_code,
                bsns_year=bsns_year,
                reprt_code=reprt_code,
                fs_div=fs_div,
                cache_key=cache_key,
                source="cache",
                cache_status="stale",
                rows=rows,
                reason=f"refresh_failed:{type(exc).__name__}",
            ),
        )
    return FinancialFetchResult(
        rows=rows,
        source_record=_record(
            corp_code=corp_code,
            bsns_year=bsns_year,
            reprt_code=reprt_code,
            fs_div=fs_div,
            cache_key=cache_key,
            source="dart",
            cache_status=cache_status,
            rows=rows,
            reason=reason,
        ),
    )


def summarize_source_records(records: list[DartSourceRecord]) -> dict[str, Any]:
    network_calls = sum(1 for record in records if record.source == "dart")
    cache_hits = sum(1 for record in records if record.cache_status == "hit")
    stale_refreshes = sum(1 for record in records if record.cache_status == "stale")
    bypassed = sum(1 for record in records if record.cache_status == "bypass")
    return {
        "policy": "live_check_with_ttl_cache",
        "financial_statement_ttl_seconds": TTL_SECONDS,
        "financial_source_count": len(records),
        "financial_network_calls": network_calls,
        "financial_cache_hits": cache_hits,
        "financial_stale_refreshes": stale_refreshes,
        "financial_bypassed_cache": bypassed,
        "financial_sources": [record.model_dump() for record in records],
    }
