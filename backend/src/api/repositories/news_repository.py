"""news(기사 원본) 영속화 — PostgreSQL.

순수 DB 접근만 담당한다. ai Article → row dict 매핑은 service 가 한다.
저장은 `url` UNIQUE 기준 upsert 라 재실행에도 중복이 생기지 않는다(멱등, SCHEMA_SPEC §7.1).
분석 결과 컬럼(요약·감성·임베딩·event_id)은 재실행 시 최신값으로 갱신한다.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Row, delete, distinct, func, select
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


async def get_existing_urls(session: AsyncSession, urls: list[str]) -> set[str]:
    """입력 url 중 이미 news 에 저장된 것들의 집합을 돌려준다(신규 기사 선별용).

    ai 배치가 수집한 url 중 **이미 저장된 것을 비싼 LLM 처리 전에 건너뛰게** 하려는 조회다.
    없으면 빈 집합. url 은 UNIQUE 라 IN 조회로 충분하다(SCHEMA_SPEC §7.1).
    """
    if not urls:
        return set()
    result = await session.execute(select(News.url).where(News.url.in_(urls)))
    return {row[0] for row in result.all()}


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


async def get_event_aggregates(
    session: AsyncSession, event_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Row]:
    """이벤트별 감성 게이지 카운트·기사수·최신 발행시각을 한 번에 집계.

    반환 `{event_id: Row(article_count, positive, neutral, negative, recency)}`.
    감성 라벨은 한글 계약값(긍정/중립/부정), sentiment=None 은 게이지에서 제외된다.
    recency 는 `within_days` 필터(최신 발행시각)용.
    """
    if not event_ids:
        return {}
    stmt = (
        select(
            News.event_id.label("event_id"),
            func.count().label("article_count"),
            func.count().filter(News.sentiment == "긍정").label("positive"),
            func.count().filter(News.sentiment == "중립").label("neutral"),
            func.count().filter(News.sentiment == "부정").label("negative"),
            func.max(News.published_at).label("recency"),
        )
        .where(News.event_id.in_(event_ids))
        .group_by(News.event_id)
    )
    rows = (await session.execute(stmt)).all()
    return {r.event_id: r for r in rows}


async def delete_articles_before(
    session: AsyncSession, cutoff: datetime
) -> Sequence[Row]:
    """published_at 이 cutoff 이전인 기사를 삭제하고 (id, event_id) 목록 반환(commit 은 호출자).

    published_at 이 NULL 인 기사는 나이를 알 수 없어 삭제하지 않는다(NULL < cutoff = false).
    반환값으로 Neo4j NewsRef 삭제(news_id)와 영향 이벤트(event_id) 재계산을 이어간다.
    """
    stmt = (
        delete(News)
        .where(News.published_at < cutoff)
        .returning(News.id, News.event_id)
    )
    result = await session.execute(stmt)
    return result.all()


async def get_articles_for_importance(
    session: AsyncSession, event_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Row]]:
    """이벤트별 남은 기사(publisher, sentiment, sentiment_score)를 그룹으로.

    importance 재계산 입력. 반환에 없는 event_id 는 남은 기사가 0건(이벤트 삭제 대상).
    """
    if not event_ids:
        return {}
    stmt = select(
        News.event_id, News.publisher, News.sentiment, News.sentiment_score
    ).where(News.event_id.in_(event_ids))
    grouped: dict[uuid.UUID, list[Row]] = {}
    for r in (await session.execute(stmt)).all():
        grouped.setdefault(r.event_id, []).append(r)
    return grouped


async def get_event_centroid_inputs(
    session: AsyncSession, event_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Sequence[Row]]:
    """이벤트별 (embedding, published_at) 행. centroid 평균·event_time 계산 입력.

    embedding 이 NULL 인 행도 published_at(event_time)에는 기여하므로 함께 가져온다.
    """
    if not event_ids:
        return {}
    stmt = select(News.event_id, News.embedding, News.published_at).where(
        News.event_id.in_(event_ids)
    )
    grouped: dict[uuid.UUID, list[Row]] = {}
    for r in (await session.execute(stmt)).all():
        grouped.setdefault(r.event_id, []).append(r)
    return grouped
