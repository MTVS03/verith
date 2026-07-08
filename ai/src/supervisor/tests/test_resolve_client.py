"""StockResolverClient 매핑 테스트 (httpx.MockTransport, 실 네트워크 없음).

정상 200(resolved/ambiguous/not_found)·422 도메인 처리와, tool-error(5xx·timeout·연결·형식오류)
분리를 검증한다.
"""

from __future__ import annotations

import httpx
import pytest

from src.supervisor.resolve_client import ResolverToolError, StockResolverClient


def _client(handler) -> StockResolverClient:
    transport = httpx.MockTransport(handler)
    return StockResolverClient(base_url="http://test").with_transport(transport)


def test_resolved_maps_stock():
    def handler(request):
        return httpx.Response(200, json={
            "status": "resolved", "reason": "exact_match",
            "stock": {"stock_code": "005930", "stock_name": "삼성전자", "market": "KOSPI"},
            "candidates": [],
        })

    result = _client(handler).resolve("삼성전자")
    assert result.status == "resolved"
    assert result.stock.stock_code == "005930" and result.stock.market == "KOSPI"


def test_ambiguous_maps_candidates():
    def handler(request):
        return httpx.Response(200, json={
            "status": "ambiguous", "reason": "multiple_stocks", "stock": None,
            "candidates": [
                {"stock_code": "006040", "stock_name": "동원산업", "market": "KOSPI",
                 "matched_text": "동원", "match_type": "ambiguous_group"},
                {"stock_code": "049770", "stock_name": "동원F&B", "market": "KOSDAQ",
                 "matched_text": "동원", "match_type": "ambiguous_group"},
            ],
        })

    result = _client(handler).resolve("동원")
    assert result.status == "ambiguous"
    assert {c.stock_code for c in result.candidates} == {"006040", "049770"}
    assert result.stock is None


def test_not_found_domain():
    def handler(request):
        return httpx.Response(200, json={"status": "not_found", "reason": "no_match",
                                         "stock": None, "candidates": []})
    assert _client(handler).resolve("로제").status == "not_found"


def test_422_empty_query_is_domain_not_found():
    def handler(request):
        return httpx.Response(422, json={"detail": "query normalizes to empty"})
    # 장애가 아니라 종목 없음(도메인).
    assert _client(handler).resolve("   ").status == "not_found"


def test_5xx_is_tool_error():
    def handler(request):
        return httpx.Response(503, json={"detail": "unavailable"})
    with pytest.raises(ResolverToolError) as ei:
        _client(handler).resolve("삼성전자")
    assert ei.value.kind == "backend_error"


def test_timeout_is_tool_error():
    def handler(request):
        raise httpx.TimeoutException("timeout", request=request)
    with pytest.raises(ResolverToolError) as ei:
        _client(handler).resolve("삼성전자")
    assert ei.value.kind == "timeout"


def test_connection_error_is_tool_error():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)
    with pytest.raises(ResolverToolError) as ei:
        _client(handler).resolve("삼성전자")
    assert ei.value.kind == "connection"


def test_resolved_without_stock_is_invalid_response():
    def handler(request):
        return httpx.Response(200, json={"status": "resolved", "reason": "exact_match",
                                         "stock": None, "candidates": []})
    with pytest.raises(ResolverToolError) as ei:
        _client(handler).resolve("삼성전자")
    assert ei.value.kind == "invalid_response"


def test_unexpected_status_value_is_invalid_response():
    def handler(request):
        return httpx.Response(200, json={"status": "weird", "reason": "x"})
    with pytest.raises(ResolverToolError) as ei:
        _client(handler).resolve("삼성전자")
    assert ei.value.kind == "invalid_response"
