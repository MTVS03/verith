"""fundamental report 저장/조회/삭제 통합 테스트."""

from __future__ import annotations

import copy
from collections.abc import AsyncGenerator
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from db.models.common.agent_report import AgentReport
from db.models.common.stock import Stock
from db.models.fundamental.fundamental_report import FundamentalReport
from db.models.fundamental.report_evidence import ReportEvidence
from db.models.fundamental.report_insight import ReportInsight
from db.models.fundamental.report_interpretation import FundamentalReportInterpretation
from db.models.fundamental.report_ratio import ReportRatio
from db.models.fundamental.report_verification import FundamentalReportVerification
from db.session import get_session
from src.api.deps import get_ai_client
from src.api.main import app

TICKER = "051910"
_POST = "/api/fundamental/reports"
_REQ = {"ticker": TICKER, "query": "최근 3년 매출 성장률", "client_session_id": "fund-sess-1"}


def _normal_output() -> dict:
    report_id = "11111111-1111-1111-1111-111111111111"
    ratio_id = "22222222-2222-2222-2222-222222222222"
    evidence_id = "33333333-3333-3333-3333-333333333333"
    return {
        "agent": "fundamental",
        "request_id": "__REQUEST_ID__",
        "ticker": TICKER,
        "corp_name": "LG화학",
        "verdict": "매출 성장률은 완만합니다.",
        "verdict_label": "moderate",
        "confidence": 0.81,
        "score": 62,
        "score_breakdown": {"score_type": "absolute_financial_health"},
        "analyst_plan": {},
        "evidence_graph": {},
        "retrieval_context": {},
        "ratios": {},
        "trend": {},
        "insights": {},
        "interpretation": "최근 3년 매출 흐름을 확인했습니다.",
        "evidence": [],
        "risk_flags": [],
        "report_html": "<section>fundamental</section>",
        "meta": {
            "trace_id": "__TRACE_ID__",
            "erd_payload": {
                "stock": {"stock_code": TICKER, "stock_name": "LG화학"},
                "fundamental_report": {
                    "id": report_id,
                    "request_id": "__REQUEST_ID__",
                    "stock_code": TICKER,
                    "corp_code": "00356361",
                    "bsns_year": 2025,
                    "years": 3,
                    "fs_div": "CFS",
                    "report_mode": "annual",
                    "reprt_code": "11011",
                    "reprt_name": "사업보고서",
                    "period_label": "2025",
                    "verdict": "매출 성장률은 완만합니다.",
                    "verdict_label": "moderate",
                    "confidence": 0.81,
                    "fin_score": 62,
                    "data_status": "normal",
                    "risk_flags": [],
                    "score_breakdown": {"score_type": "absolute_financial_health"},
                    "report_html": "<section>fundamental</section>",
                    "llm_provider": "template",
                    "llm_model": "rule-based",
                    "llm_latency_ms": 0,
                    "dart_calls": 4,
                    "trace_id": "__TRACE_ID__",
                    "as_of": "2026-07-08T09:00:00+00:00",
                    "created_at": "2026-07-08T09:00:00+00:00",
                    "meta": {"workflow": ["collect", "report"]},
                },
                "report_ratios": [
                    {
                        "id": ratio_id,
                        "report_id": report_id,
                        "ratio_name": "revenue_growth",
                        "label": "매출성장률",
                        "category": "성장성",
                        "fiscal_year": 2025,
                        "fiscal_period": "2025",
                        "value": "12.5",
                        "unit": "%",
                        "display_value": "12.5%",
                        "status": "available",
                        "reason": None,
                        "formula": "(current_revenue - previous_revenue) / previous_revenue * 100",
                        "basis": {"source": "deterministic"},
                    }
                ],
                "report_evidence": [
                    {
                        "id": evidence_id,
                        "report_id": report_id,
                        "ratio_id": ratio_id,
                        "metric": "revenue_growth",
                        "claim": "매출성장률 12.5%",
                        "rcept_no": "20260301000001",
                        "bsns_year": 2025,
                        "fiscal_period": "2025",
                        "sj_div": "IS",
                        "account_id": "ifrs-full_Revenue",
                        "account_nm": "매출액",
                        "amount": "1000000",
                        "unit": "KRW",
                        "display_value": "100만원",
                        "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260301000001",
                        "role": "current",
                        "raw": {"account_id": "ifrs-full_Revenue"},
                    }
                ],
                "report_interpretation": {
                    "id": "44444444-4444-4444-4444-444444444444",
                    "report_id": report_id,
                    "interpretation": "최근 3년 매출 흐름을 확인했습니다.",
                    "interpretation_source": "template",
                    "provider": "template",
                    "model": "rule-based",
                    "prompt_meta": {"risk_flags": []},
                },
                "report_verification": {
                    "id": "55555555-5555-5555-5555-555555555555",
                    "report_id": report_id,
                    "binding_passed": True,
                    "consistency_passed": True,
                    "verdict_stable": True,
                    "outcome": "passed",
                    "regen_count": 0,
                    "evidence_count": 1,
                    "guard_violations": [],
                    "flags": [],
                },
                "report_insights": [
                    {
                        "id": "66666666-6666-6666-6666-666666666666",
                        "report_id": report_id,
                        "insight_type": "dividend",
                        "source_endpoint": "alotMatter",
                        "rcept_no": "20260301000001",
                        "payload": {"status": "available"},
                    }
                ],
                "report_filing_snippets": [],
            },
        },
    }


class FakeFundamentalAIClient:
    def __init__(self, output: dict) -> None:
        self._output = output

    async def analyze_fundamental(self, payload: dict) -> dict:
        out = copy.deepcopy(self._output)
        out["request_id"] = payload["request_id"]
        out["meta"]["trace_id"] = payload["trace_id"]
        root = out["meta"]["erd_payload"]["fundamental_report"]
        root["request_id"] = payload["request_id"]
        root["trace_id"] = payload["trace_id"]
        return out


async def _client(db_session, output: dict) -> AsyncGenerator[AsyncClient, None]:
    async def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_ai_client] = lambda: FakeFundamentalAIClient(output)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _create(client: AsyncClient) -> UUID:
    resp = await client.post(_POST, json=_REQ)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert set(body.keys()) == {"report_id", "report"}
    assert body["report"]["ticker"] == TICKER
    return UUID(body["report_id"])


async def _count(session, model, report_id: UUID) -> int:
    return await session.scalar(
        select(func.count()).select_from(model).where(model.report_id == report_id)
    )


async def test_fundamental_create_get_list_delete_roundtrip(db_session):
    async for client in _client(db_session, _normal_output()):
        rid = await _create(client)

        report = await db_session.get(FundamentalReport, rid)
        assert report is not None
        assert report.stock_code == TICKER
        assert report.corp_code == "00356361"
        assert report.years == 3
        assert report.report_mode == "annual"
        assert report.fin_score == 62
        assert report.report_html == "<section>fundamental</section>"

        assert await _count(db_session, ReportRatio, rid) == 1
        assert await _count(db_session, ReportEvidence, rid) == 1
        assert await _count(db_session, FundamentalReportInterpretation, rid) == 1
        assert await _count(db_session, FundamentalReportVerification, rid) == 1
        assert await _count(db_session, ReportInsight, rid) == 1

        agent = await db_session.scalar(select(AgentReport).where(AgentReport.agent_report_id == rid))
        assert agent is not None
        assert agent.agent_type == "fundamental"
        assert agent.answer_text == "매출 성장률은 완만합니다."
        assert agent.summary == {
            "fin_score": 62,
            "verdict_label": "moderate",
            "period_label": "2025",
        }

        stock = await db_session.get(Stock, TICKER)
        assert stock is not None
        assert stock.stock_name == "LG화학"

        get_resp = await client.get(f"{_POST}/{rid}")
        assert get_resp.status_code == 200
        detail = get_resp.json()
        assert detail["report_id"] == str(rid)
        assert detail["report"]["fundamental_report"]["stock_code"] == TICKER
        assert detail["report"]["report_ratios"][0]["ratio_name"] == "revenue_growth"
        assert detail["report"]["report_evidence"][0]["unit"] == "KRW"
        assert detail["report"]["report_insights"][0]["insight_type"] == "dividend"

        list_resp = await client.get(_POST, params={"stock_code": TICKER})
        assert list_resp.status_code == 200
        listed = list_resp.json()
        assert listed["count"] >= 1
        assert any(item["agent_report_id"] == str(rid) for item in listed["items"])

        delete_resp = await client.delete(f"{_POST}/{rid}")
        assert delete_resp.status_code == 204
        assert await db_session.get(FundamentalReport, rid) is None
        assert await _count(db_session, ReportRatio, rid) == 0
        assert await _count(db_session, ReportEvidence, rid) == 0
        assert await db_session.scalar(select(AgentReport).where(AgentReport.agent_report_id == rid)) is None
        assert await db_session.get(Stock, TICKER) is not None


async def test_fundamental_get_delete_missing_404(db_session):
    async for client in _client(db_session, _normal_output()):
        missing = "00000000-0000-0000-0000-000000000000"
        get_resp = await client.get(f"{_POST}/{missing}")
        assert get_resp.status_code == 404
        delete_resp = await client.delete(f"{_POST}/{missing}")
        assert delete_resp.status_code == 404


async def test_fundamental_contract_violation_rejected(db_session):
    broken = _normal_output()
    del broken["meta"]["erd_payload"]["fundamental_report"]
    async for client in _client(db_session, broken):
        before = await db_session.scalar(select(func.count()).select_from(FundamentalReport))
        resp = await client.post(_POST, json=_REQ)
        assert resp.status_code == 502, resp.text
        after = await db_session.scalar(select(func.count()).select_from(FundamentalReport))
        assert after == before
