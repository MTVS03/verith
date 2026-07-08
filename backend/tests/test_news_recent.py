"""news 병합 후보 API 테스트 — GET /news/events/recent.

centroid(임베딩 평균)은 실 PostgreSQL(pgvector) 값으로 계산, 그래프 순회는 monkeypatch.
검증: centroid 평균, event_time(최신), 임베딩 없는 이벤트 제외, within_days 필터.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from db.graph.driver import get_graph_session
from db.models.news.news import News
from db.session import get_session
from src.api.main import app
from src.api.repositories import news_graph_repository as graph_repo

EVENT_A = uuid.UUID("a1a1a1a1-0000-0000-0000-000000000000")  # 임베딩 2건 → centroid
EVENT_B = uuid.UUID("b2b2b2b2-0000-0000-0000-000000000000")  # 임베딩 없음 → 제외
EVENT_C = uuid.UUID("c3c3c3c3-0000-0000-0000-000000000000")  # 30일 전 → within_days 제외


def _ago(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


@pytest_asyncio.fixture
async def recent_client(db_session, monkeypatch):
    db_session.add_all([
        News(title="a1", url="https://r.test/a1", event_id=EVENT_A,
             embedding=[1.0, 2.0], published_at=_ago(1)),
        News(title="a2", url="https://r.test/a2", event_id=EVENT_A,
             embedding=[3.0, 4.0], published_at=_ago(2)),
        News(title="b1", url="https://r.test/b1", event_id=EVENT_B,
             embedding=None, published_at=_ago(1)),
        News(title="c1", url="https://r.test/c1", event_id=EVENT_C,
             embedding=[5.0, 6.0], published_at=_ago(30)),
    ])
    await db_session.flush()

    graph_events = [
        {"canonical_id": str(EVENT_A), "canonical_title": "A", "importance": 1.0, "companies": ["삼성"]},
        {"canonical_id": str(EVENT_B), "canonical_title": "B", "importance": 1.0, "companies": ["삼성"]},
        {"canonical_id": str(EVENT_C), "canonical_title": "C", "importance": 1.0, "companies": ["삼성"]},
    ]

    async def _fake_by_companies(session, companies):
        return graph_events

    monkeypatch.setattr(graph_repo, "get_events_by_companies", _fake_by_companies)

    async def _override_session():
        yield db_session

    async def _override_graph():
        yield object()

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_graph_session] = _override_graph
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_recent_centroid_and_filters(recent_client):
    resp = await recent_client.get("/news/events/recent", params={"companies": ["삼성"]})
    assert resp.status_code == 200
    body = resp.json()
    # A 만 후보: B(임베딩 없음)·C(30일 전) 제외
    assert [c["canonical_id"] for c in body] == [str(EVENT_A)]
    cand = body[0]
    assert cand["embedding"] == [2.0, 3.0]        # ([1,2]+[3,4])/2
    assert cand["event_time"] is not None          # 최신 published_at
    assert cand["companies"] == ["삼성"]


async def test_recent_missing_companies_422(recent_client):
    resp = await recent_client.get("/news/events/recent")
    assert resp.status_code == 422
