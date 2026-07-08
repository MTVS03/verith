"""news 조회 오케스트레이션 (순수 PostgreSQL).

이벤트별 기사(근거)·중요도 통계 조회. Neo4j 순회가 필요한 조회(query/subject 등)는 별도.
row → 응답 스키마 매핑만 하고, 값을 재해석/재계산하지 않는다(가이드 §3.2).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.repositories import news_repository as news_repo
from src.api.schemas.news import ArticleRef, EventArticleStats


class NewsQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_existing_urls(self, urls: list[str]) -> list[str]:
        """입력 url 중 이미 저장된 것만 정렬해 돌려준다(ai 가 신규 기사 선별에 사용)."""
        return sorted(await news_repo.get_existing_urls(self._session, urls))

    async def get_articles_by_event(
        self, event_id: uuid.UUID, limit: int
    ) -> list[ArticleRef]:
        """이벤트별 근거 기사(ArticleRef) 최신순 limit 건. summary 없으면 빈 문자열."""
        rows = await news_repo.get_articles_by_event(self._session, event_id, limit)
        return [
            ArticleRef(news_id=r.id, summary=r.summary or "", url=r.url) for r in rows
        ]

    async def get_event_stats(
        self, event_id: uuid.UUID
    ) -> EventArticleStats | None:
        """이벤트 누적 기사 통계. 기사가 없으면 None(ai provider 는 이를 degrade 처리)."""
        row = await news_repo.get_event_article_stats(self._session, event_id)
        if row is None:
            return None
        return EventArticleStats(
            article_count=row.article_count,
            publishers=list(row.publishers or []),
            sentiment_magnitude_sum=float(row.sentiment_magnitude_sum or 0.0),
            sentiment_count=row.sentiment_count,
            updated_at=row.updated_at,
        )
