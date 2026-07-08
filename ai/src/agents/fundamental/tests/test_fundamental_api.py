from __future__ import annotations

from fastapi.testclient import TestClient

from src.agents.fundamental.core.contract import FundamentalAgentInput, FundamentalResponse
from src.api import fundamental as fundamental_api
from src.main import app


def _sample_response(request: FundamentalAgentInput) -> FundamentalResponse:
    return FundamentalResponse(
        request_id=request.request_id,
        ticker=request.ticker,
        corp_name="삼성전자",
        verdict="테스트 응답입니다.",
        verdict_label="insufficient_data",
        confidence=0.3,
        score=0,
        score_breakdown={},
        ratios={},
        trend={},
        interpretation="테스트 응답입니다.",
        evidence=[],
        risk_flags=[],
        report_html="<section>테스트</section>",
        meta={
            "trace_id": request.trace_id,
            "input_interpretation": {"report_mode": "annual"},
        },
    )


def test_fundamental_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/internal/fundamental/health")

    assert response.status_code == 200
    assert response.json()["service"] == "fundamental-agent"


def test_fundamental_analyze_endpoint_uses_public_contract(monkeypatch) -> None:
    async def fake_analyze(public_input: FundamentalAgentInput) -> FundamentalResponse:
        assert public_input.query == "최신 3년 수익성 분석"
        return _sample_response(public_input)

    monkeypatch.setattr(fundamental_api, "analyze_fundamental_public", fake_analyze)
    client = TestClient(app)

    response = client.post(
        "/internal/fundamental/analyze",
        json={
            "request_id": "req-1",
            "trace_id": "trace-1",
            "ticker": "005930",
            "query": "최신 3년 수익성 분석",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == "req-1"
    assert payload["ticker"] == "005930"
    assert payload["meta"]["trace_id"] == "trace-1"


def test_fundamental_analyze_endpoint_rejects_internal_fields() -> None:
    client = TestClient(app)

    response = client.post(
        "/internal/fundamental/analyze",
        json={
            "request_id": "req-1",
            "trace_id": "trace-1",
            "ticker": "005930",
            "query": "재무 분석",
            "intent": "valuation",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
