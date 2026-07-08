"""news cleanup API 테스트 — POST /news/cleanup.

PostgreSQL 삭제는 실제(conftest db_session), Neo4j 정리는 graph_repo.cleanup_graph 를 monkeypatch 로
가로채 '무엇이 전달됐는지'(삭제 news_id·빈 이벤트·importance 재계산)를 검증한다.
실 Neo4j 그래프 정리는 별도 e2e 로 확인.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from db.graph.driver import get_graph_session
from db.models.news.news import News
from db.session import get_session
from src.api.main import app
from src.api.repositories import news_graph_repository as graph_repo

EVENT_X = uuid.UUID("aaaa1111-0000-0000-0000-000000000000")  # old 1 + recent 1 → 재계산
EVENT_Y = uuid.UUID("bbbb2222-0000-0000-0000-000000000000")  # old 2 → 빈 이벤트(삭제)
EVENT_Z = uuid.UUID("cccc3333-0000-0000-0000-000000000000")  # recent 1 → 영향 없음


def _ago(hours: int) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


@pytest_asyncio.fixture
async def cleanup_client(db_session, monkeypatch):
    db_session.add_all([
        News(title="x-old", url="https://c.test/x-old", event_id=EVENT_X,
             publisher="한국경제", sentiment="긍정", sentiment_score=0.8, published_at=_ago(200)),
        News(title="x-new", url="https://c.test/x-new", event_id=EVENT_X,
             publisher="매일경제", sentiment="부정", sentiment_score=0.6, published_at=_ago(1)),
        News(title="y-old1", url="https://c.test/y1", event_id=EVENT_Y,
             publisher="한겨레", sentiment="중립", published_at=_ago(200)),
        News(title="y-old2", url="https://c.test/y2", event_id=EVENT_Y,
             publisher="조선일보", sentiment="긍정", sentiment_score=0.5, published_at=_ago(300)),
        News(title="z-new", url="https://c.test/z", event_id=EVENT_Z,
             publisher="세계일보", sentiment="긍정", sentiment_score=0.9, published_at=_ago(1)),
    ])
    await db_session.flush()

    captured: dict = {}

    async def _fake_cleanup_graph(session, deleted_news_ids, empty_event_keys, importance_updates):
        captured["deleted_news_ids"] = deleted_news_ids
        captured["empty_event_keys"] = empty_event_keys
        captured["importance_updates"] = importance_updates
        return len(empty_event_keys)

    monkeypatch.setattr(graph_repo, "cleanup_graph", _fake_cleanup_graph)

    async def _override_session():
        yield db_session

    async def _override_graph():
        yield object()

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_graph_session] = _override_graph
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._captured = captured  # type: ignore[attr-defined]
        yield ac
    app.dependency_overrides.clear()


async def _count(session, event_id) -> int:
    return await session.scalar(
        select(func.count()).select_from(News).where(News.event_id == event_id)
    )


async def test_cleanup_deletes_old_and_reports(cleanup_client, db_session):
    resp = await cleanup_client.post("/news/cleanup")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["deleted_articles"] == 3          # x-old + y1 + y2
    assert body["deleted_events"] == 1            # Y (빈 이벤트)

    # PG 상태: X 1건 남음, Y 0건, Z 1건(영향 없음)
    assert await _count(db_session, EVENT_X) == 1
    assert await _count(db_session, EVENT_Y) == 0
    assert await _count(db_session, EVENT_Z) == 1


async def test_cleanup_graph_payload(cleanup_client):
    await cleanup_client.post("/news/cleanup")
    cap = cleanup_client._captured
    assert len(cap["deleted_news_ids"]) == 3
    # Y 는 빈 이벤트, X 는 재계산 대상, Z 는 영향 없음(둘 다 아님)
    assert str(EVENT_Y) in cap["empty_event_keys"]
    assert str(EVENT_X) not in cap["empty_event_keys"]
    assert str(EVENT_X) in cap["importance_updates"]
    assert str(EVENT_Y) not in cap["importance_updates"]
    assert str(EVENT_Z) not in cap["importance_updates"]  # 삭제 영향 없는 이벤트는 손대지 않음
    assert cap["importance_updates"][str(EVENT_X)] > 0     # 재계산된 점수
