"""news 질의(subject/shared) 오케스트레이션 — Neo4j 순회 + PostgreSQL 집계.

Neo4j 에서 회사→이벤트(single/multi-hop)를 얻고, PostgreSQL 로 감성 게이지·기사수·recency 를
집계해 합친다. 감성 분포는 저장하지 않고 조회 시 실시간 집계한다(SCHEMA_SPEC §6, 절대규칙 4).
importance 내림차순 정렬, `within_days` 로 최신 기사 없는 이벤트는 제외한다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from neo4j import AsyncSession as GraphSession
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.repositories import news_graph_repository as graph_repo
from src.api.repositories import news_repository as news_repo
from src.api.schemas.news import (
    ArticleRef,
    Event,
    EventWithArticles,
    SentimentGauge,
    SubjectQueryResponse,
)

# 이벤트별 화면 노출 대표 기사 소수(전체 아님 — 깊은 근거는 /events/{id}/articles on-demand).
_REP_ARTICLE_LIMIT = 3


def _as_uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except (ValueError, TypeError):
        return None


class NewsGraphQueryService:
    def __init__(self, session: AsyncSession, graph_session: GraphSession) -> None:
        self._session = session
        self._graph = graph_session

    async def get_events_by_subject(
        self, companies: list[str], within_days: int
    ) -> SubjectQueryResponse:
        events_raw = await graph_repo.get_events_by_companies(self._graph, companies)
        subject_found = await graph_repo.companies_exist(self._graph, companies)
        response = await self._assemble(events_raw, within_days)
        return SubjectQueryResponse(
            subject=", ".join(companies),
            subject_found=subject_found,
            events=response[0],
            overall_gauge=response[1],
        )

    async def get_shared_events(
        self, company_a: str, company_b: str, within_days: int
    ) -> SubjectQueryResponse:
        events_raw = await graph_repo.get_shared_events(self._graph, company_a, company_b)
        subject_found = await graph_repo.companies_exist(self._graph, [company_a, company_b])
        events, overall = await self._assemble(events_raw, within_days)
        return SubjectQueryResponse(
            subject=f"{company_a} & {company_b}",
            subject_found=subject_found,
            events=events,
            overall_gauge=overall,
        )

    async def _assemble(
        self, events_raw: list[dict], within_days: int
    ) -> tuple[list[EventWithArticles], SentimentGauge]:
        """그래프 이벤트 + PG 집계를 합쳐 (EventWithArticles[], overall_gauge) 로.

        within_days 내 최신 기사가 있는 이벤트만 포함, importance 내림차순 정렬.
        """
        # canonical_id → uuid 파싱(불량 id 는 제외).
        by_uuid: dict[uuid.UUID, dict] = {}
        for e in events_raw:
            eid = _as_uuid(e.get("canonical_id"))
            if eid is not None:
                by_uuid[eid] = e

        aggregates = await news_repo.get_event_aggregates(self._session, list(by_uuid))
        cutoff = datetime.now(UTC) - timedelta(days=within_days)

        items: list[EventWithArticles] = []
        pos = neu = neg = 0
        for eid, raw in by_uuid.items():
            agg = aggregates.get(eid)
            if agg is None or agg.recency is None or agg.recency < cutoff:
                continue  # within_days 내 기사 없음 → 제외
            gauge = SentimentGauge(
                positive=agg.positive, neutral=agg.neutral, negative=agg.negative
            )
            pos += agg.positive
            neu += agg.neutral
            neg += agg.negative
            rows = await news_repo.get_articles_by_event(
                self._session, eid, _REP_ARTICLE_LIMIT
            )
            items.append(
                EventWithArticles(
                    event=Event(
                        canonical_id=raw.get("canonical_id"),
                        canonical_title=raw.get("canonical_title") or "",
                        importance=raw.get("importance"),
                        companies=list(raw.get("companies") or []),
                    ),
                    article_count=agg.article_count,
                    articles=[
                        ArticleRef(news_id=r.id, summary=r.summary or "", url=r.url)
                        for r in rows
                    ],
                    gauge=gauge,
                )
            )

        # importance 내림차순(없으면 뒤로).
        items.sort(key=lambda x: (x.event.importance is not None, x.event.importance or 0.0), reverse=True)
        overall = SentimentGauge(positive=pos, neutral=neu, negative=neg)
        return items, overall
