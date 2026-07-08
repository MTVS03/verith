"""news report 저장/조회/삭제 통합 테스트.

DB: docker PostgreSQL(트랜잭션 롤백 격리, conftest). technical 과 달리 AI 호출이 없어
FakeAIClient 는 쓰지 않는다 — 완성된 ReportModel JSON 을 POST 로 넣고 저장/승격/삭제를 검증한다.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from db.models.common.agent_report import AgentReport
from db.models.news.news_report import NewsReport

_POST = "/news/reports"

# ai ReportModel.model_dump(mode="json") 형태의 최소 리포트(backend 는 구조를 재해석하지 않음).
_REPORT = {
    "subject": "삼성전자",
    "generated_at": "2026-07-08T00:00:00+00:00",
    "period_days": 7,
    "overall_gauge": {"positive": 3, "neutral": 1, "negative": 1},
    "top_events": [],
    "answer_text": "최근 삼성전자 뉴스는 대체로 긍정적입니다.",
    "cited_event_ids": ["evt-1", "evt-2"],
    "evidence_news_ids": [101, 102],
    "data_limited": False,
}
_REQ = {
    "report": _REPORT,
    "question": "삼성전자 뉴스 어때?",
    "intent": "stock_news",
    "client_session_id": "test-sess-news",
}


async def _create(client) -> UUID:
    resp = await client.post(_POST, json=_REQ)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert set(body.keys()) == {"report_id", "report"}   # wrapper 구조
    assert body["report"]["subject"] == "삼성전자"        # report = ai 원본
    return UUID(body["report_id"])


# 1) POST → news_reports 저장 + 승격 필드 + 원본 보존
async def test_create_persists_news_report(client, db_session):
    rid = await _create(client)
    row = await db_session.get(NewsReport, rid)
    assert row is not None
    assert row.question == "삼성전자 뉴스 어때?"
    assert row.intent == "stock_news"
    assert row.answer_text == _REPORT["answer_text"]              # 승격
    assert row.evidence["cited_event_ids"] == ["evt-1", "evt-2"]  # 근거 묶음
    assert row.evidence["evidence_news_ids"] == [101, 102]
    assert row.report_json["subject"] == "삼성전자"               # ai 원본 보존


# 2) agent_reports 목록 인덱스 저장 (stock_code 는 비움 — 종목 FK 회피)
async def test_create_persists_agent_index(client, db_session):
    rid = await _create(client)
    row = await db_session.scalar(select(AgentReport).where(AgentReport.agent_report_id == rid))
    assert row is not None
    assert row.agent_type == "news"
    assert row.stock_code is None            # 자유 subject → stocks FK 안 검
    assert row.stock_name == "삼성전자"       # 표시용 subject
    assert row.question == "삼성전자 뉴스 어때?"


# 3) GET 상세 = { report_id, report }
async def test_get_report_envelope(client):
    rid = await _create(client)
    resp = await client.get(f"{_POST}/{rid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["report_id"] == str(rid)
    assert body["report"]["answer_text"] == _REPORT["answer_text"]


# 4) GET /api/reports?agent_type=news 목록 연결
async def test_list_reports(client):
    rid = await _create(client)
    resp = await client.get("/api/reports", params={"agent_type": "news"})
    assert resp.status_code == 200
    body = resp.json()
    assert any(item["agent_report_id"] == str(rid) for item in body["items"])


# 5) DELETE → news_reports + agent_reports 인덱스 함께 삭제
async def test_delete_removes_both(client, db_session):
    rid = await _create(client)
    resp = await client.delete(f"{_POST}/{rid}")
    assert resp.status_code == 204
    assert await db_session.get(NewsReport, rid) is None
    agent = await db_session.scalar(select(AgentReport).where(AgentReport.agent_report_id == rid))
    assert agent is None


# 6) 없는 report_id → 404
async def test_get_missing_404(client):
    resp = await client.get(f"{_POST}/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_delete_missing_404(client):
    resp = await client.delete(f"{_POST}/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


# 7) question/intent 없이도 저장 (ReportModel 에 없는 필드 → nullable)
async def test_optional_question_intent_nullable(client, db_session):
    resp = await client.post(_POST, json={"report": _REPORT})
    assert resp.status_code == 201
    rid = UUID(resp.json()["report_id"])
    row = await db_session.get(NewsReport, rid)
    assert row.question is None
    assert row.intent is None
    assert row.answer_text == _REPORT["answer_text"]  # 승격은 그대로 동작
