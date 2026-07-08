"""news 배치 저장 오케스트레이션.

저장 흐름(SCHEMA_SPEC §2.4): articles 를 `news.url` upsert → `url→news_id` 맵 확보 →
같은 요청의 GraphBatch(NewsRef=url 키)를 그 맵으로 news_id 해소해 Neo4j MERGE.
두 저장소를 걸치므로 단일 DB 트랜잭션은 불가하나, url UNIQUE + 그래프 MERGE 로 **멱등**이라
재실행에 안전하다(SCHEMA_SPEC §7.1). backend 는 AI 분석값을 바꾸지 않고 저장만 한다(가이드 §3.2).
"""

from __future__ import annotations

import logging
import uuid

from neo4j import AsyncSession as GraphSession
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.repositories import news_graph_repository as graph_repo
from src.api.repositories import news_repository as news_repo
from src.api.schemas.news import ArticleIn, NewsBatchSaveRequest, SaveResponse

logger = logging.getLogger(__name__)


def _to_row(article: ArticleIn) -> dict:
    """ArticleIn → news 테이블 row dict. event_id(str UUID) → uuid.UUID 변환."""
    event_id = uuid.UUID(article.event_id) if article.event_id else None
    return {
        "title": article.title,
        "url": article.url,
        "publisher": article.publisher,
        "content": article.content,
        "summary": article.summary,
        "sentiment": article.sentiment,
        "sentiment_score": article.sentiment_score,
        "embedding": article.embedding,
        "published_at": article.published_at,
        "event_id": event_id,
    }


class NewsService:
    def __init__(self, session: AsyncSession, graph_session: GraphSession) -> None:
        self._session = session
        self._graph = graph_session

    async def save_batch(self, req: NewsBatchSaveRequest) -> SaveResponse:
        """기사 upsert(PostgreSQL) + GraphBatch MERGE(Neo4j). SaveResponse 반환."""
        rows = [_to_row(a) for a in req.articles]

        # 1) PostgreSQL: url upsert → url→news_id 맵. (그래프 해소의 선행)
        url_to_news_id = await news_repo.upsert_articles(self._session, rows)
        await self._session.commit()

        # 2) Neo4j: GraphBatch MERGE (NewsRef url→news_id 해소).
        await graph_repo.merge_graph(self._graph, req.graph_batch, url_to_news_id)

        saved = len(url_to_news_id)
        logger.info(
            "news_batch_saved",
            extra={
                "saved": saved,
                "nodes": len(req.graph_batch.nodes),
                "relationships": len(req.graph_batch.relationships),
            },
        )
        return SaveResponse(ok=True, saved=saved)
