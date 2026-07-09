"""news 질의 API 테스트 — GET /news/query/subject · /news/query/shared.

Neo4j 순회는 monkeypatch 로 canned(그래프 결과 고정), PostgreSQL 집계는 실제(conftest db_session).
검증: importance 정렬, within_days 필터, 실시간 감성 게이지·overall_gauge, subject_found.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio

from db.graph.driver import get_graph_session
from db.models.news.news import News
from db.session import get_session
from src.api.repositories import news_graph_repository as graph_repo
from src.api.main import app

EVENT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000000")
EVENT_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000000")  # 오래된 기사(within_days 밖)
EVENT_C = uuid.UUID("cccccccc-0000-0000-0000-000000000000")


def _ago(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


@pytest_asyncio.fixture
async def subject_client(db_session, monkeypatch):
    # PG: A(긍2·부1, 최근), C(중1, 최근), B(긍1, 30일 전 → 필터로 제외)
    db_session.add_all([
        News(title="a1", url="https://s.test/a1", event_id=EVENT_A, sentiment="긍정",
             sentiment_score=0.8, summary="A1", published_at=_ago(1)),
        News(title="a2", url="https://s.test/a2", event_id=EVENT_A, sentiment="긍정",
             sentiment_score=0.7, summary="A2", published_at=_ago(1)),
        News(title="a3", url="https://s.test/a3", event_id=EVENT_A, sentiment="부정",
             sentiment_score=0.6, summary="A3", published_at=_ago(2)),
        News(title="c1", url="https://s.test/c1", event_id=EVENT_C, sentiment="중립",
             summary="C1", published_at=_ago(2)),
        News(title="b1", url="https://s.test/b1", event_id=EVENT_B, sentiment="긍정",
             summary="B1", published_at=_ago(30)),
    ])
    await db_session.flush()

    # Neo4j 순회 결과를 고정(그래프는 세 이벤트를 importance 5/3/1 로 반환).
    graph_events = [
        {"canonical_id": str(EVENT_A), "canonical_title": "A 이벤트", "importance": 5.0,
         "companies": ["삼성", "SK"]},
        {"canonical_id": str(EVENT_B), "canonical_title": "B 이벤트", "importance": 3.0,
         "companies": ["삼성"]},
        {"canonical_id": str(EVENT_C), "canonical_title": "C 이벤트", "importance": 1.0,
         "companies": ["삼성"]},
    ]

    async def _fake_by_companies(session, companies):
        return graph_events

    async def _fake_shared(session, a, b):
        return [graph_events[0]]  # A 이벤트만 공유

    async def _fake_exist(session, companies):
        return True

    monkeypatch.setattr(graph_repo, "get_events_by_companies", _fake_by_companies)
    monkeypatch.setattr(graph_repo, "get_shared_events", _fake_shared)
    monkeypatch.setattr(graph_repo, "companies_exist", _fake_exist)

    async def _override_session():
        yield db_session

    async def _override_graph():
        yield object()  # graph_repo 가 monkeypatch 돼 실제로 쓰이지 않음

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_graph_session] = _override_graph
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_subject_importance_order_and_within_days(subject_client):
    resp = await subject_client.get("/news/query/subject", params={"companies": ["삼성"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["subject_found"] is True
    # B(30일 전)는 제외, A·C 만. importance 내림차순 → A(5) 먼저, C(1) 다음.
    titles = [e["event"]["canonical_title"] for e in body["events"]]
    assert titles == ["A 이벤트", "C 이벤트"]


async def test_subject_gauge_and_overall(subject_client):
    resp = await subject_client.get("/news/query/subject", params={"companies": ["삼성"]})
    body = resp.json()
    a = body["events"][0]
    assert a["article_count"] == 3
    assert (a["gauge"]["positive"], a["gauge"]["neutral"], a["gauge"]["negative"]) == (2, 0, 1)
    assert a["gauge"]["total"] == 3                      # computed_field 직렬화
    assert len(a["articles"]) == 3                       # 대표 기사(news_id 포함)
    # overall = A(긍2·부1) + C(중1)
    og = body["overall_gauge"]
    assert (og["positive"], og["neutral"], og["negative"]) == (2, 1, 1)


async def test_subject_daily_counts(subject_client):
    # 포함된 이벤트(A·C)만 발행일별 집계. B(30일 전)는 within_days 밖이라 제외.
    # A: 1일전 2건 + 2일전 1건, C: 2일전 1건 → 1일전 2건, 2일전 2건.
    resp = await subject_client.get("/news/query/subject", params={"companies": ["삼성"]})
    body = resp.json()
    counts = {row["date"]: row["count"] for row in body["daily_counts"]}
    # 합은 포함된 이벤트들의 기사 총계(A 3 + C 1 = 4)와 같다.
    assert sum(counts.values()) == 4
    # 날짜별로 2·2 로 갈린다(1일전 A2건, 2일전 A1+C1건).
    assert sorted(counts.values()) == [2, 2]
    # 발행일 오름차순 정렬.
    dates = [row["date"] for row in body["daily_counts"]]
    assert dates == sorted(dates)


async def test_subject_companies_query_param_repeat(subject_client):
    # 별칭 여러 개(?companies=삼성&companies=삼성전자)
    resp = await subject_client.get(
        "/news/query/subject", params=[("companies", "삼성"), ("companies", "삼성전자")]
    )
    assert resp.status_code == 200
    assert resp.json()["subject"] == "삼성, 삼성전자"


async def test_shared_events(subject_client):
    resp = await subject_client.get(
        "/news/query/shared", params={"company_a": "삼성", "company_b": "SK"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["subject"] == "삼성 & SK"
    assert [e["event"]["canonical_title"] for e in body["events"]] == ["A 이벤트"]


async def test_subject_missing_companies_422(subject_client):
    resp = await subject_client.get("/news/query/subject")  # companies 필수
    assert resp.status_code == 422
