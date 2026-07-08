"""news 조회 API 테스트 — GET /news/events/stats · /news/events/{id}/articles.

순수 PostgreSQL 조회. conftest `db_session`(트랜잭션 롤백)에 기사를 직접 심고 엔드포인트를 호출.
Neo4j 불필요(get_session 만 override).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from db.models.news.news import News
from db.session import get_session
from src.api.main import app

EVENT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_EVENT = "33333333-3333-3333-3333-333333333333"


def _dt(hour: int) -> datetime:
    return datetime.fromisoformat(f"2026-07-06T{hour:02d}:00:00+09:00")


@pytest_asyncio.fixture
async def seeded_client(db_session):
    """같은 event_id 기사 3건을 심고, get_session 을 그 세션으로 override 한 클라이언트."""
    db_session.add_all([
        News(title="a1", url="https://q.test/1", event_id=EVENT_ID, publisher="A",
             summary="요약1", sentiment="긍정", sentiment_score=0.8, published_at=_dt(9)),
        News(title="a2", url="https://q.test/2", event_id=EVENT_ID, publisher="A",
             summary="요약2", sentiment="부정", sentiment_score=0.6, published_at=_dt(11)),
        News(title="a3", url="https://q.test/3", event_id=EVENT_ID, publisher="B",
             summary=None, sentiment=None, sentiment_score=None, published_at=_dt(10)),
    ])
    await db_session.flush()

    async def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── /news/events/{event_id}/articles ────────────────────────────────────────
async def test_articles_ordered_and_limited(seeded_client):
    resp = await seeded_client.get(f"/news/events/{EVENT_ID}/articles", params={"limit": 2})
    assert resp.status_code == 200
    body = resp.json()
    # published_at desc: a2(11) → a3(10). limit=2.
    assert [a["url"] for a in body] == ["https://q.test/2", "https://q.test/3"]
    assert all({"news_id", "summary", "url"} == set(a) for a in body)
    # summary 없는 기사(a3)는 빈 문자열
    assert body[1]["summary"] == ""


async def test_articles_empty_for_unknown_event(seeded_client):
    resp = await seeded_client.get(f"/news/events/{OTHER_EVENT}/articles")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_articles_invalid_uuid_422(seeded_client):
    resp = await seeded_client.get("/news/events/not-a-uuid/articles")
    assert resp.status_code == 422


# ── /news/events/stats ──────────────────────────────────────────────────────
async def test_stats_aggregation(seeded_client):
    resp = await seeded_client.get("/news/events/stats", params={"event_id": str(EVENT_ID)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["article_count"] == 3
    assert sorted(body["publishers"]) == ["A", "B"]        # distinct, NULL 제외
    assert body["sentiment_count"] == 2                    # 감성 있는 기사만
    assert body["sentiment_magnitude_sum"] == 1.4          # 0.8 + 0.6


async def test_stats_null_for_unknown_event(seeded_client):
    resp = await seeded_client.get("/news/events/stats", params={"event_id": OTHER_EVENT})
    assert resp.status_code == 200
    assert resp.json() is None                             # 기사 없으면 null


# ── /news/exists (중복 재처리 방지: 이미 저장된 url 선별) ─────────────────────
async def test_exists_returns_only_saved(seeded_client):
    resp = await seeded_client.post("/news/exists", json={"urls": [
        "https://q.test/1", "https://q.test/9", "https://q.test/3",
    ]})
    assert resp.status_code == 200
    # 저장된 것(/1,/3)만, 미저장(/9) 제외
    assert sorted(resp.json()["existing"]) == ["https://q.test/1", "https://q.test/3"]


async def test_exists_empty_input(seeded_client):
    resp = await seeded_client.post("/news/exists", json={"urls": []})
    assert resp.status_code == 200
    assert resp.json()["existing"] == []
