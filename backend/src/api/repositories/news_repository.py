"""news(기사 원본) 영속화 — PostgreSQL.

순수 DB 접근만 담당한다. ai Article → row dict 매핑은 service 가 한다.
저장은 `url` UNIQUE 기준 upsert 라 재실행에도 중복이 생기지 않는다(멱등, SCHEMA_SPEC §7.1).
분석 결과 컬럼(요약·감성·임베딩·event_id)은 재실행 시 최신값으로 갱신한다.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import Row, distinct, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.news.news import News

# 충돌(같은 url) 시 갱신하는 컬럼 — url/id/created_at 은 보존.
_UPSERT_UPDATE_COLS = (
    "title",
    "content",
    "summary",
    "publisher",
    "sentiment",
    "sentiment_score",
    "embedding",
    "published_at",
    "event_id",
)


async def upsert_articles(
    session: AsyncSession, rows: list[dict]
) -> dict[str, int]:
    """기사들을 `url` upsert 하고 `{url: news_id}` 맵을 돌려준다(commit 은 호출자).

    맵은 GraphBatch 의 NewsRef(key=url)를 news_id 로 해소하는 데 쓰인다(SCHEMA_SPEC §3).
    """
    if not rows:
        return {}
    stmt = pg_insert(News).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[News.url],
        set_={col: stmt.excluded[col] for col in _UPSERT_UPDATE_COLS},
    ).returning(News.url, News.id)
    result = await session.execute(stmt)
    return {url: news_id for url, news_id in result.all()}


async def get_articles_by_event(
    session: AsyncSession, event_id: uuid.UUID, limit: int
) -> Sequence[Row]:
    """이벤트(event_id)에 속한 기사를 최신순으로 최대 limit 건 (id, summary, url)."""
    stmt = (
        select(News.id, News.summary, News.url)
        .where(News.event_id == event_id)
        .order_by(News.published_at.desc().nullslast())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.all()


async def get_event_article_stats(
    session: AsyncSession, event_id: uuid.UUID
) -> Row | None:
    """이벤트의 누적 기사 통계 1행. 기사가 없으면 None.

    - article_count: 기사 총 건수
    - sentiment_count / sentiment_magnitude_sum: 감성 있는(None 아님) 기사 개수/강도(score) 합
    - publishers: 언론사 distinct(원자료, NULL 제외)
    - updated_at: member 기사 created_at 최댓값(선택)
    """
    stmt = select(
        func.count().label("article_count"),
        func.count(News.sentiment).label("sentiment_count"),
        func.coalesce(
            func.sum(News.sentiment_score).filter(News.sentiment.isnot(None)),
            0.0,
        ).label("sentiment_magnitude_sum"),
        func.array_remove(
            func.array_agg(distinct(News.publisher)), None
        ).label("publishers"),
        func.max(News.created_at).label("updated_at"),
    ).where(News.event_id == event_id)
    row = (await session.execute(stmt)).one()
    return row if row.article_count > 0 else None
