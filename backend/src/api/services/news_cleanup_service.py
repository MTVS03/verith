"""news 7일 롤링 cleanup 오케스트레이션 (SCHEMA_SPEC §5).

published_at 이 168h 경과한 기사 삭제(PostgreSQL) → 대응 NewsRef 삭제(Neo4j) →
기사수 0 이벤트 삭제 + 고아 Keyword/Person/Country 삭제(Company 유지) →
삭제로 기사 집합이 바뀐(살아남은) 이벤트의 importance 재계산(ai 공식 복제, §4.2).

두 저장소를 걸치므로 단일 트랜잭션은 불가. PG 삭제를 먼저 commit 한 뒤 Neo4j 정리를 반영한다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from neo4j import AsyncSession as GraphSession
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.repositories import news_graph_repository as graph_repo
from src.api.repositories import news_repository as news_repo
from src.api.schemas.news import CleanupResponse
from src.api.services.importance import compute_importance

logger = logging.getLogger(__name__)

_ROLLING_HOURS = 168  # 7일


class NewsCleanupService:
    def __init__(self, session: AsyncSession, graph_session: GraphSession) -> None:
        self._session = session
        self._graph = graph_session

    async def cleanup(self, older_than_hours: int = _ROLLING_HOURS) -> CleanupResponse:
        cutoff = datetime.now(UTC) - timedelta(hours=older_than_hours)

        # 1) PostgreSQL: 경과 기사 삭제 → (id, event_id) 확보.
        deleted = await news_repo.delete_articles_before(self._session, cutoff)
        deleted_news_ids = [r.id for r in deleted]
        affected_event_ids = list({r.event_id for r in deleted if r.event_id is not None})

        # 2) 삭제 반영된 상태에서 영향 이벤트의 남은 기사 조회 → 재계산/삭제 판정.
        remaining = await news_repo.get_articles_for_importance(
            self._session, affected_event_ids
        )
        empty_event_keys: list[str] = []
        importance_updates: dict[str, float] = {}
        for eid in affected_event_ids:
            rows = remaining.get(eid)
            if rows:  # 남은 기사 있음 → 현재 집합으로 importance 재계산
                importance_updates[str(eid)] = compute_importance(rows)
            else:  # 남은 기사 0건 → 이벤트 삭제 대상
                empty_event_keys.append(str(eid))

        await self._session.commit()  # PG 삭제 확정(그래프 정리 전)

        # 3) Neo4j: NewsRef 삭제 + 빈 이벤트 삭제 + 고아 정리 + importance 갱신.
        deleted_events = await graph_repo.cleanup_graph(
            self._graph,
            deleted_news_ids=deleted_news_ids,
            empty_event_keys=empty_event_keys,
            importance_updates=importance_updates,
        )

        logger.info(
            "news_cleanup_done",
            extra={
                "deleted_articles": len(deleted_news_ids),
                "deleted_events": deleted_events,
                "recomputed_events": len(importance_updates),
            },
        )
        return CleanupResponse(
            ok=True,
            deleted_articles=len(deleted_news_ids),
            deleted_events=deleted_events,
        )
