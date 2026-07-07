"""technical report 저장/조회/삭제 통합 테스트.

DB: docker PostgreSQL(트랜잭션 롤백 격리). AI: FakeAIClient(conftest) mock.
검증 기준 10개(요청 스펙 §11)를 커버한다.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from db.models.common.agent_report import AgentReport
from db.models.common.stock import Stock
from db.models.technical.report_chart import TechnicalReportChart
from db.models.technical.report_interpretation import TechnicalReportInterpretation
from db.models.technical.report_risk_note import TechnicalReportRiskNote
from db.models.technical.report_signal import TechnicalReportSignal
from db.models.technical.report_verification import TechnicalReportVerification
from db.models.technical.technical_report import TechnicalReport
from tests.fixtures.ai_output import TICKER, UNIQUE_INDICATORS

_REQ = {"ticker": TICKER, "query": "373220 기술적 흐름 분석", "client_session_id": "test-sess-1"}


async def _create(client) -> UUID:
    resp = await client.post("/technical/reports", json=_REQ)
    assert resp.status_code == 201, resp.text
    return UUID(resp.json()["report_id"])


async def _count(session, model, report_id) -> int:
    return await session.scalar(
        select(func.count()).select_from(model).where(model.report_id == report_id)
    )


# 1) POST → technical_reports 저장
async def test_create_persists_technical_report(client, db_session):
    rid = await _create(client)
    report = await db_session.get(TechnicalReport, rid)
    assert report is not None
    assert report.ticker == TICKER
    assert report.data_status == "normal"
    assert report.final_regime == "uptrend_intact"
    assert report.input_payload["request_id"] == report.request_id  # backend 생성 request_id
    assert report.output_payload["source"] == "KIS"                 # 원본 output 보존


# 2) child tables 저장 (charts/signals/interpretation/verification)
async def test_create_persists_children(client, db_session):
    rid = await _create(client)
    assert await _count(db_session, TechnicalReportChart, rid) == 1
    assert await _count(db_session, TechnicalReportSignal, rid) == len(UNIQUE_INDICATORS)
    assert await _count(db_session, TechnicalReportRiskNote, rid) == 1
    assert await _count(db_session, TechnicalReportInterpretation, rid) == 1
    assert await _count(db_session, TechnicalReportVerification, rid) == 1


# 3) agent_reports index 저장
async def test_create_persists_agent_report_index(client, db_session):
    rid = await _create(client)
    row = await db_session.scalar(
        select(AgentReport).where(AgentReport.agent_report_id == rid)
    )
    assert row is not None
    assert row.agent_type == "technical"
    assert row.stock_code == TICKER
    assert row.summary["final_regime"] == "uptrend_intact"


# 9) agent_reports 저장 전에 stocks upsert
async def test_create_upserts_stock(client, db_session):
    await _create(client)
    stock = await db_session.get(Stock, TICKER)
    assert stock is not None
    assert stock.stock_name == "LG에너지솔루션"  # allowlist 해소


# 10) 중복 indicator 가 unique 제약을 깨지 않고 dedup
async def test_signals_dedup_unique_indicator(client, db_session):
    rid = await _create(client)  # output 에 rsi 2개 → 1개만 저장돼야 함
    rows = await db_session.execute(
        select(TechnicalReportSignal.indicator).where(TechnicalReportSignal.report_id == rid)
    )
    indicators = [r[0] for r in rows]
    assert sorted(indicators) == sorted(UNIQUE_INDICATORS)
    assert len(indicators) == len(set(indicators))  # 중복 없음


# 4) GET 상세
async def test_get_detail(client):
    rid = await _create(client)
    resp = await client.get(f"/technical/reports/{rid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == TICKER
    assert len(body["signals"]) == len(UNIQUE_INDICATORS)
    assert len(body["charts"]) == 1
    assert body["interpretation"]["interpretation_source"] == "llm"
    assert body["verification"]["outcome"] == "passed"


# 5) GET /reports 목록
async def test_list_reports(client):
    rid = await _create(client)
    resp = await client.get("/reports", params={"agent_type": "technical"})
    assert resp.status_code == 200
    body = resp.json()
    assert any(item["agent_report_id"] == str(rid) for item in body["items"])
    assert body["items"][0]["agent_type"] == "technical"


# 6·7) DELETE → agent_reports + technical_reports 삭제, 자식 cascade
async def test_delete_cascades(client, db_session):
    rid = await _create(client)
    resp = await client.delete(f"/technical/reports/{rid}")
    assert resp.status_code == 204

    assert await db_session.get(TechnicalReport, rid) is None
    assert await _count(db_session, TechnicalReportSignal, rid) == 0
    assert await _count(db_session, TechnicalReportChart, rid) == 0
    assert await _count(db_session, TechnicalReportInterpretation, rid) == 0
    agent = await db_session.scalar(
        select(AgentReport).where(AgentReport.agent_report_id == rid)
    )
    assert agent is None
    # stocks 는 삭제하지 않음
    assert await db_session.get(Stock, TICKER) is not None


# 8) 없는 report_id 조회/삭제 → 404
async def test_get_missing_404(client):
    resp = await client.get("/technical/reports/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_delete_missing_404(client):
    resp = await client.delete("/technical/reports/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
