"""news 배치 저장 API 테스트 — POST /news/batch/save.

DB: docker PostgreSQL(트랜잭션 롤백 격리, conftest `db_session`).
Neo4j: FakeGraphSession 으로 mock(라이브 Neo4j 불필요 — execute_write 의 Cypher 호출을 기록).
검증: 기사 upsert(PostgreSQL) + GraphBatch 의 NewsRef(url 키)가 PG news_id 로 해소되는지.
(실 Neo4j 왕복은 별도 수동 e2e 로 확인함.)
"""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from db.graph.driver import get_graph_session
from db.models.news.news import News
from db.session import get_session
from src.api.main import app

EVENT_ID = "11111111-1111-1111-1111-111111111111"
URL1 = "https://unit.test/news/1"
URL2 = "https://unit.test/news/2"

_POST = "/news/batch/save"

_PAYLOAD = {
    "articles": [
        {"title": "기사1", "url": URL1, "publisher": "언론", "summary": "요약1",
         "sentiment": "긍정", "sentiment_score": 0.9,
         "published_at": "2026-07-06T09:00:00+09:00", "event_id": EVENT_ID},
        {"title": "기사2", "url": URL2, "summary": "요약2",
         "sentiment": "중립", "event_id": EVENT_ID},
    ],
    "graph_batch": {
        "nodes": [
            {"label": "Event", "key": EVENT_ID,
             "properties": {"canonical_title": "이벤트", "importance": 2.0}},
            {"label": "Company", "key": "회사A", "properties": {"name": "회사A"}},
            {"label": "NewsRef", "key": URL1, "properties": {}},
            {"label": "NewsRef", "key": URL2, "properties": {}},
        ],
        "relationships": [
            {"type": "PARTICIPATES_IN", "start_label": "Company", "start_key": "회사A",
             "end_label": "Event", "end_key": EVENT_ID},
            {"type": "HAS_NEWS", "start_label": "Event", "start_key": EVENT_ID,
             "end_label": "NewsRef", "end_key": URL1},
        ],
    },
}


class _FakeTx:
    """merge_graph 가 호출하는 tx.run 을 기록만 한다(결과 미소비)."""

    def __init__(self, calls: list) -> None:
        self._calls = calls

    async def run(self, query: str, **params):
        self._calls.append((query, params))
        return None


class FakeGraphSession:
    """neo4j AsyncSession 대역. execute_write 로 넘어온 work 를 _FakeTx 로 실행."""

    def __init__(self) -> None:
        self.calls: list = []

    async def execute_write(self, work):
        return await work(_FakeTx(self.calls))


@pytest_asyncio.fixture
async def fake_graph() -> FakeGraphSession:
    return FakeGraphSession()


@pytest_asyncio.fixture
async def news_client(db_session, fake_graph):
    """get_session 은 롤백 세션, get_graph_session 은 FakeGraphSession 으로 override."""

    async def _override_session():
        yield db_session

    async def _override_graph():
        yield fake_graph

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_graph_session] = _override_graph
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _news_id_by_url(session) -> dict[str, int]:
    rows = await session.execute(
        select(News.url, News.id).where(News.url.in_([URL1, URL2]))
    )
    return {url: nid for url, nid in rows.all()}


# 1) 저장 성공 + 기사 upsert(PostgreSQL)
async def test_save_persists_articles(news_client, db_session):
    resp = await news_client.post(_POST, json=_PAYLOAD)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True and body["saved"] == 2

    rows = await db_session.execute(
        select(News).where(News.url.in_([URL1, URL2]))
    )
    news = {n.url: n for n in rows.scalars().all()}
    assert set(news) == {URL1, URL2}
    assert news[URL1].sentiment == "긍정"          # AI 값 그대로 저장(가이드 §3.2)
    assert str(news[URL1].event_id) == EVENT_ID     # event_id(str) → uuid 저장


# 2) NewsRef(url 키)가 PG news_id 로 해소돼 그래프에 전달됨(핵심 계약)
async def test_newsref_resolved_to_news_id(news_client, db_session, fake_graph):
    resp = await news_client.post(_POST, json=_PAYLOAD)
    assert resp.status_code == 200
    id_by_url = await _news_id_by_url(db_session)

    # FakeGraphSession 이 기록한 NewsRef 노드 MERGE 호출에서 news_id 가 PG id 와 일치하는지
    # (HAS_NEWS 관계 MERGE 도 :NewsRef 를 언급하므로 노드 MERGE 만 정확히 집는다)
    newsref_calls = [
        params for query, params in fake_graph.calls
        if query.startswith("MERGE (n:NewsRef")
    ]
    resolved = {c["props"]["url"]: c["val"] for c in newsref_calls}
    assert resolved == {URL1: id_by_url[URL1], URL2: id_by_url[URL2]}


# 3) 멱등: 같은 배치 재저장해도 news 중복 없음(url UNIQUE upsert)
async def test_save_is_idempotent(news_client, db_session):
    await news_client.post(_POST, json=_PAYLOAD)
    await news_client.post(_POST, json=_PAYLOAD)
    id_by_url = await _news_id_by_url(db_session)
    assert len(id_by_url) == 2


# 4) 빈 배치도 정상(0건 저장)
async def test_save_empty_batch(news_client):
    resp = await news_client.post(_POST, json={"articles": [], "graph_batch": {"nodes": [], "relationships": []}})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "saved": 0, "message": None}


# 5) 잘못된 감성 라벨 → 422(Pydantic 검증, 가이드 §8.1)
async def test_invalid_sentiment_rejected(news_client):
    bad = {"articles": [{"title": "t", "url": "https://x.test/1", "sentiment": "행복"}],
           "graph_batch": {"nodes": [], "relationships": []}}
    resp = await news_client.post(_POST, json=bad)
    assert resp.status_code == 422
