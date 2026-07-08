"""technical report 저장/조회/삭제 통합 테스트.

DB: docker PostgreSQL(트랜잭션 롤백 격리). AI: FakeAIClient(conftest) mock.
계약(api_spec §6) + 응답 검증(계약 위반 거부) + stocks 마스터 보호를 커버한다.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models.common.agent_report import AgentReport
from db.models.common.stock import Stock
from db.models.technical.report_chart import TechnicalReportChart
from db.models.technical.report_interpretation import TechnicalReportInterpretation
from db.models.technical.report_signal import TechnicalReportSignal
from db.models.technical.report_verification import TechnicalReportVerification
from db.models.technical.technical_report import TechnicalReport
from tests.fixtures.ai_output import INDICATORS, TICKER

_POST = "/api/technical/reports"
_REQ = {"ticker": TICKER, "query": "373220 기술적 흐름 분석", "client_session_id": "test-sess-1"}


async def _create(client) -> UUID:
    resp = await client.post(_POST, json=_REQ)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert set(body.keys()) == {"report_id", "report"}          # api_spec §6 wrapper
    assert body["report"]["ticker"] == TICKER                   # report = AI 원본
    return UUID(body["report_id"])


async def _count(session, model, report_id) -> int:
    return await session.scalar(
        select(func.count()).select_from(model).where(model.report_id == report_id)
    )


# 1) POST → technical_reports 저장 + 원본 보존
async def test_create_persists_technical_report(client, db_session):
    rid = await _create(client)
    report = await db_session.get(TechnicalReport, rid)
    assert report is not None
    assert report.ticker == TICKER
    assert report.stock_code == TICKER
    assert report.data_status == "normal"
    assert report.final_regime == "uptrend_intact"
    assert report.input_payload["request_id"] == report.request_id  # backend 생성 request_id 저장
    assert report.output_payload["source"] == "KIS"                 # AI 원본 보존


# 2) child tables 저장
async def test_create_persists_children(client, db_session):
    rid = await _create(client)
    assert await _count(db_session, TechnicalReportChart, rid) == 1
    assert await _count(db_session, TechnicalReportSignal, rid) == len(INDICATORS)
    assert await _count(db_session, TechnicalReportInterpretation, rid) == 1
    assert await _count(db_session, TechnicalReportVerification, rid) == 1


# 3) agent_reports index 저장
async def test_create_persists_agent_report_index(client, db_session):
    rid = await _create(client)
    row = await db_session.scalar(select(AgentReport).where(AgentReport.agent_report_id == rid))
    assert row is not None
    assert row.agent_type == "technical"
    assert row.stock_code == TICKER
    assert row.summary["final_regime"] == "uptrend_intact"


# 9) stocks upsert (allowlist 이름)
async def test_create_upserts_stock(client, db_session):
    await _create(client)
    stock = await db_session.get(Stock, TICKER)
    assert stock is not None
    assert stock.stock_name == "LG에너지솔루션"


# stocks 마스터 보호: 요청 stock_name 이 기존 마스터를 덮지 못한다
async def test_stock_master_not_overwritten_by_request(client, db_session):
    # 기존 마스터를 다른 이름으로 강제(seed 된 DB에서도 견고하도록 upsert — raw add 금지).
    await db_session.execute(
        pg_insert(Stock)
        .values(stock_code=TICKER, stock_name="정상마스터명")
        .on_conflict_do_update(
            index_elements=[Stock.stock_code], set_={"stock_name": "정상마스터명"}
        )
    )
    await db_session.flush()
    resp = await client.post(_POST, json={**_REQ, "stock_name": "가짜회사명"})
    assert resp.status_code == 201
    stock = await db_session.get(Stock, TICKER)
    await db_session.refresh(stock)
    assert stock.stock_name == "정상마스터명"  # 요청값으로 덮이지 않음


# 4) GET 상세 = { report_id, report }
async def test_get_report_envelope(client):
    rid = await _create(client)
    resp = await client.get(f"{_POST}/{rid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["report_id"] == str(rid)
    assert body["report"]["ticker"] == TICKER
    assert body["report"]["verification"]["outcome"] == "passed"


# 5) GET /api/reports 목록
async def test_list_reports(client):
    rid = await _create(client)
    resp = await client.get("/api/reports", params={"agent_type": "technical"})
    assert resp.status_code == 200
    body = resp.json()
    assert any(item["agent_report_id"] == str(rid) for item in body["items"])


# 6·7) DELETE → agent_reports + technical_reports 삭제, 자식 cascade, stocks 유지
async def test_delete_cascades(client, db_session):
    rid = await _create(client)
    resp = await client.delete(f"{_POST}/{rid}")
    assert resp.status_code == 204
    assert await db_session.get(TechnicalReport, rid) is None
    assert await _count(db_session, TechnicalReportSignal, rid) == 0
    assert await _count(db_session, TechnicalReportChart, rid) == 0
    agent = await db_session.scalar(select(AgentReport).where(AgentReport.agent_report_id == rid))
    assert agent is None
    assert await db_session.get(Stock, TICKER) is not None  # 마스터 유지


# 8) 없는 report_id → 404
async def test_get_missing_404(client):
    resp = await client.get(f"{_POST}/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_delete_missing_404(client):
    resp = await client.delete(f"{_POST}/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


# ── AI 응답 계약 검증(위반 시 502, 저장 안 함) ────────────────────────────────
async def _assert_rejected_and_not_saved(client, db_session):
    before = await db_session.scalar(select(func.count()).select_from(TechnicalReport))
    resp = await client.post(_POST, json=_REQ)
    assert resp.status_code == 502, resp.text
    after = await db_session.scalar(select(func.count()).select_from(TechnicalReport))
    assert after == before  # 위반 응답은 저장되지 않음


# 10) 중복 indicator → 502, 미저장
@pytest.mark.parametrize("ai_output", ["DUP"], indirect=True)
async def test_duplicate_indicator_rejected(client, db_session):
    await _assert_rejected_and_not_saved(client, db_session)


# 요청↔응답 ticker 불일치 → 502
@pytest.mark.parametrize("ai_output", ["MISMATCH"], indirect=True)
async def test_ticker_mismatch_rejected(client, db_session):
    await _assert_rejected_and_not_saved(client, db_session)


# 구조 누락(regime 없음) → 502
@pytest.mark.parametrize("ai_output", ["MALFORMED"], indirect=True)
async def test_malformed_output_rejected(client, db_session):
    await _assert_rejected_and_not_saved(client, db_session)
