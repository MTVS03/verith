"""news(기사 원본) 영속화 — PostgreSQL.

순수 DB 접근만 담당한다. ai Article → row dict 매핑은 service 가 한다.
저장은 `url` UNIQUE 기준 upsert 라 재실행에도 중복이 생기지 않는다(멱등, SCHEMA_SPEC §7.1).
분석 결과 컬럼(요약·감성·임베딩·event_id)은 재실행 시 최신값으로 갱신한다.
"""

from __future__ import annotations

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
