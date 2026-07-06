from __future__ import annotations

from typing import Any

from src.agents.fundamental.core.contract import FundamentalRequest
from src.agents.fundamental.data.cache import CacheInspection
from src.agents.fundamental.data import latest_report
from src.agents.fundamental.nodes import collect_node
from src.agents.fundamental.retrieval import source_policy


def test_financial_fetch_uses_fresh_cache_without_network(monkeypatch) -> None:
    rows = [{"rcept_no": "20260301000001", "account_id": "ifrs-full_Revenue"}]

    def fake_fetch_financials(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError("fresh cache must not call DART")

    monkeypatch.setattr(source_policy, "load_cached", lambda key: rows)
    monkeypatch.setattr(
        source_policy,
        "inspect_cache",
        lambda key: CacheInspection(key, "cache.json", True, True, 10.0, 86400),
    )
    monkeypatch.setattr(source_policy, "fetch_financials", fake_fetch_financials)

    result = source_policy.fetch_financial_statement_rows(
        "00356361",
        2025,
        reprt_code="11011",
        fs_div="CFS",
        use_cache=True,
    )

    assert result.rows == rows
    assert result.source_record.source == "cache"
    assert result.source_record.cache_status == "hit"
    assert result.source_record.rcept_nos == ["20260301000001"]


def test_financial_fetch_bypasses_cache_for_live_check(monkeypatch) -> None:
    rows = [{"rcept_no": "20260301000002", "account_id": "ifrs-full_Equity"}]

    monkeypatch.setattr(source_policy, "load_cached", lambda key: [{"rcept_no": "cached"}])
    monkeypatch.setattr(
        source_policy,
        "inspect_cache",
        lambda key: CacheInspection(key, "cache.json", True, True, 10.0, 86400),
    )
    monkeypatch.setattr(source_policy, "fetch_financials", lambda *args, **kwargs: rows)

    result = source_policy.fetch_financial_statement_rows(
        "00356361",
        2025,
        reprt_code="11011",
        fs_div="CFS",
        use_cache=False,
    )

    assert result.rows == rows
    assert result.source_record.source == "dart"
    assert result.source_record.cache_status == "bypass"
    assert result.source_record.reason == "live_check_requested"


def test_source_summary_counts_cache_and_network() -> None:
    records = [
        source_policy.DartSourceRecord(
            endpoint="fnlttSinglAcntAll",
            cache_key="a",
            corp_code="00356361",
            bsns_year=2024,
            reprt_code="11011",
            fs_div="CFS",
            source="cache",
            cache_status="hit",
            row_count=1,
            rcept_nos=["1"],
            as_of="2026-07-06T00:00:00+00:00",
            ttl_seconds=86400,
        ),
        source_policy.DartSourceRecord(
            endpoint="fnlttSinglAcntAll",
            cache_key="b",
            corp_code="00356361",
            bsns_year=2025,
            reprt_code="11011",
            fs_div="CFS",
            source="dart",
            cache_status="stale",
            row_count=1,
            rcept_nos=["2"],
            as_of="2026-07-06T00:00:00+00:00",
            ttl_seconds=86400,
        ),
    ]

    summary = source_policy.summarize_source_records(records)

    assert summary["financial_source_count"] == 2
    assert summary["financial_network_calls"] == 1
    assert summary["financial_cache_hits"] == 1
    assert summary["financial_stale_refreshes"] == 1


def test_financial_fetch_uses_stale_cache_when_refresh_fails(monkeypatch) -> None:
    rows = [{"rcept_no": "20260301000003", "account_id": "ifrs-full_Assets"}]

    monkeypatch.setattr(source_policy, "load_cached", lambda key: None)
    monkeypatch.setattr(source_policy, "load_cached_any_age", lambda key: rows)
    monkeypatch.setattr(
        source_policy,
        "inspect_cache",
        lambda key: CacheInspection(key, "cache.json", True, False, 90000.0, 86400),
    )

    def fake_fetch_financials(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise source_policy.DartApiError("100", "invalid api key")

    monkeypatch.setattr(source_policy, "fetch_financials", fake_fetch_financials)

    result = source_policy.fetch_financial_statement_rows(
        "00356361",
        2025,
        reprt_code="11011",
        fs_div="CFS",
        use_cache=True,
    )

    assert result.rows == rows
    assert result.source_record.source == "cache"
    assert result.source_record.cache_status == "stale"
    assert result.source_record.reason == "refresh_failed:DartApiError"


def test_financial_fetch_marks_corrupt_cache_reason(monkeypatch) -> None:
    rows = [{"rcept_no": "20260301000004", "account_id": "ifrs-full_Assets"}]

    monkeypatch.setattr(source_policy, "load_cached", lambda key: None)
    monkeypatch.setattr(source_policy, "load_cached_any_age", lambda key: None)
    monkeypatch.setattr(
        source_policy,
        "inspect_cache",
        lambda key: CacheInspection(key, "cache.json", True, True, 10.0, 86400),
    )
    monkeypatch.setattr(source_policy, "fetch_financials", lambda *args, **kwargs: rows)

    result = source_policy.fetch_financial_statement_rows(
        "00356361",
        2025,
        reprt_code="11011",
        fs_div="CFS",
        use_cache=True,
    )

    assert result.rows == rows
    assert result.source_record.source == "dart"
    assert result.source_record.cache_status == "miss"
    assert result.source_record.reason == "cache_corrupt"


def test_latest_report_uses_short_ttl_cache(monkeypatch) -> None:
    payload = {
        "bsns_year": 2026,
        "reprt_code": "11014",
        "reprt_name": "3분기보고서",
        "mode": "latest",
    }

    monkeypatch.setattr(
        latest_report,
        "inspect_cache",
        lambda key, ttl_seconds: CacheInspection(key, "latest.json", True, True, 120.0, ttl_seconds),
    )
    monkeypatch.setattr(latest_report, "load_cached_any_age", lambda key: payload)

    def fake_probe(*args: Any, **kwargs: Any) -> source_policy.FinancialFetchResult:
        raise AssertionError("fresh latest-report cache must not probe DART")

    monkeypatch.setattr(latest_report, "fetch_financial_statement_rows", fake_probe)

    selection = latest_report.discover_latest_report("00356361", "CFS")

    assert selection.bsns_year == 2026
    assert selection.reprt_code == "11014"
    assert selection.probe_calls == 0
    assert selection.probe_records == []


def test_latest_report_records_probe_sources(monkeypatch) -> None:
    rows = [{"rcept_no": "20260701000001", "account_id": "ifrs-full_Revenue"}]
    saved: dict[str, Any] = {}

    monkeypatch.setattr(
        latest_report,
        "inspect_cache",
        lambda key, ttl_seconds: CacheInspection(key, "latest.json", False, False, None, ttl_seconds),
    )
    monkeypatch.setattr(latest_report, "save_cache", lambda key, data: saved.update({"key": key, "data": data}))

    def fake_probe(
        corp_code: str,
        bsns_year: int,
        *,
        reprt_code: str,
        fs_div: str,
        use_cache: bool,
    ) -> source_policy.FinancialFetchResult:
        assert use_cache is False
        probe_rows = rows if reprt_code == "11014" else []
        return source_policy.FinancialFetchResult(
            rows=probe_rows,
            source_record=source_policy.DartSourceRecord(
                endpoint="fnlttSinglAcntAll",
                cache_key=f"{corp_code}_{bsns_year}_{reprt_code}_{fs_div}",
                corp_code=corp_code,
                bsns_year=bsns_year,
                reprt_code=reprt_code,
                fs_div=fs_div,
                source="dart",
                cache_status="bypass",
                row_count=len(probe_rows),
                rcept_nos=["20260701000001"] if probe_rows else [],
                as_of="2026-07-06T00:00:00+00:00",
                ttl_seconds=86400,
                reason="live_check_requested",
            ),
        )

    monkeypatch.setattr(latest_report, "fetch_financial_statement_rows", fake_probe)

    selection = latest_report.discover_latest_report("00356361", "CFS")

    assert selection.reprt_code == "11014"
    assert selection.probe_calls == 1
    assert len(selection.probe_records) == 1
    assert selection.probe_records[0].reason == "latest_report_probe:live_check_requested"
    assert saved["data"]["reprt_code"] == "11014"


def test_collect_latest_mode_only_bypasses_cache_for_latest_year(monkeypatch) -> None:
    calls: list[tuple[int, bool]] = []

    monkeypatch.setattr(collect_node, "resolve", lambda ticker: "00356361")
    monkeypatch.setattr(collect_node, "resolve_name", lambda ticker: "삼성전자")
    monkeypatch.setattr(
        collect_node,
        "discover_latest_report",
        lambda corp_code, fs_div: latest_report.ReportSelection(
            bsns_year=2026,
            reprt_code="11011",
            reprt_name="사업보고서",
            mode="latest",
        ),
    )
    monkeypatch.setattr(collect_node, "fetch_share_count", lambda *args, **kwargs: None)
    monkeypatch.setattr(collect_node, "fetch_regular_report_insights", lambda *args, **kwargs: ({}, 0))

    def fake_fetch_financial_statement_rows(
        corp_code: str,
        bsns_year: int,
        *,
        reprt_code: str,
        fs_div: str,
        use_cache: bool,
    ) -> source_policy.FinancialFetchResult:
        calls.append((bsns_year, use_cache))
        rows = [
            {
                "rcept_no": f"{bsns_year}0301000001",
                "account_id": "ifrs-full_Revenue",
                "account_nm": "매출액",
                "thstrm_amount": "1000",
            }
        ]
        return source_policy.FinancialFetchResult(
            rows=rows,
            source_record=source_policy.DartSourceRecord(
                endpoint="fnlttSinglAcntAll",
                cache_key=f"{corp_code}_{bsns_year}_{reprt_code}_{fs_div}",
                corp_code=corp_code,
                bsns_year=bsns_year,
                reprt_code=reprt_code,
                fs_div=fs_div,
                source="cache" if use_cache else "dart",
                cache_status="hit" if use_cache else "bypass",
                row_count=1,
                rcept_nos=[f"{bsns_year}0301000001"],
                as_of="2026-07-06T00:00:00+00:00",
                ttl_seconds=86400,
            ),
        )

    monkeypatch.setattr(collect_node, "fetch_financial_statement_rows", fake_fetch_financial_statement_rows)

    request = FundamentalRequest(
        request_id="req-1",
        trace_id="trace-1",
        ticker="005930",
        report_mode="latest",
        years=3,
    )

    result = collect_node.collect_node({"request": request, "use_cache": True})

    assert result["data_status"] == "normal"
    assert calls == [(2024, True), (2025, True), (2026, False)]
