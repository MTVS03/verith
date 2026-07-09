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
    CandidateEvent,
    DailyCount,
    Event,
    EventWithArticles,
    SentimentGauge,
    SubjectQueryResponse,
)

# 이벤트별로 붙여줄 기사 상한. 리포트가 관련 기사를 '전부' 노출하도록 넉넉히 잡는다(실제 이벤트당
# 기사는 대개 수 건~수십 건). 초대형 이벤트 방어용 안전 상한이며, 이를 넘는 깊은 근거는 여전히
# /events/{id}/articles on-demand 로 조회 가능. (LLM 답변 근거는 별도로 소수만 사용 — 토큰 보호.)
_REP_ARTICLE_LIMIT = 100


def _centroid(embeddings: list[list[float]]) -> list[float] | None:
    """임베딩들의 원소별 평균(대표 벡터). 차원 무관 — 저장된 벡터를 그대로 평균한다.

    임베딩이 없으면 None. 차원이 어긋난 벡터는 방어적으로 제외(같은 모델이라 정상은 동일 차원).
    """
    if not embeddings:
        return None
    dim = len(embeddings[0])
    valid = [e for e in embeddings if len(e) == dim]
    if not valid:
        return None
    sums = [0.0] * dim
    for e in valid:
        for i, v in enumerate(e):
            sums[i] += v
    n = len(valid)
    return [s / n for s in sums]


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
        events, overall, daily_counts = await self._assemble(events_raw, within_days)
        return SubjectQueryResponse(
            subject=", ".join(companies),
            subject_found=subject_found,
            events=events,
            overall_gauge=overall,
            daily_counts=daily_counts,
        )

    async def get_recent_candidate_events(
        self, companies: list[str], within_days: int
    ) -> list[CandidateEvent]:
        """병합 후보 이벤트 조회. 이벤트별 centroid(임베딩 평균) + event_time 을 backend 가 계산.

        임베딩이 하나도 없는 이벤트는 유사도 후보가 될 수 없어 제외한다. within_days 내
        기사가 있는 이벤트만 포함.
        """
        events_raw = await graph_repo.get_events_by_companies(self._graph, companies)
        by_uuid: dict[uuid.UUID, dict] = {}
        for e in events_raw:
            eid = _as_uuid(e.get("canonical_id"))
            if eid is not None:
                by_uuid[eid] = e
        return await self._build_candidates(by_uuid, within_days)

    async def get_merge_candidates(
        self,
        companies: list[str],
        within_days: int,
        embedding: list[float] | None,
        top_k: int,
    ) -> list[CandidateEvent]:
        """병합 후보(A2): 회사 참여 이벤트 ∪ 임베딩 최근접 이벤트. 회사 없는 기사도 내용으로 후보를 얻는다.

        - 회사 경로: get_events_by_companies(기존).
        - 벡터 경로: get_events_near_embedding(pgvector 최근접) 로 event_id 를 얻고, 회사 목록은
          graph 에서 보강(get_events_by_ids). 두 경로 event 를 합집합해 centroid·event_time 을 계산.
        """
        by_uuid: dict[uuid.UUID, dict] = {}
        events_raw = await graph_repo.get_events_by_companies(self._graph, companies)
        for e in events_raw:
            eid = _as_uuid(e.get("canonical_id"))
            if eid is not None:
                by_uuid[eid] = e

        if embedding:
            near_ids = await news_repo.get_events_near_embedding(
                self._session, embedding, within_days, top_k
            )
            missing = [eid for eid in near_ids if eid is not None and eid not in by_uuid]
            if missing:
                vec_raw = await graph_repo.get_events_by_ids(
                    self._graph, [str(x) for x in missing]
                )
                for e in vec_raw:
                    eid = _as_uuid(e.get("canonical_id"))
                    if eid is not None:
                        by_uuid[eid] = e

        return await self._build_candidates(by_uuid, within_days)

    async def _build_candidates(
        self, by_uuid: dict[uuid.UUID, dict], within_days: int
    ) -> list[CandidateEvent]:
        """event(uuid→raw) 집합에 대해 centroid(임베딩 평균)·event_time 을 계산해 CandidateEvent[] 로.

        within_days 내 기사가 없거나 임베딩이 하나도 없는 이벤트는 유사도 후보가 될 수 없어 제외한다.
        """
        inputs = await news_repo.get_event_centroid_inputs(self._session, list(by_uuid))
        cutoff = datetime.now(UTC) - timedelta(days=within_days)

        result: list[CandidateEvent] = []
        for eid, raw in by_uuid.items():
            rows = inputs.get(eid)
            if not rows:
                continue
            times = [r.published_at for r in rows if r.published_at is not None]
            event_time = max(times) if times else None
            if event_time is None or event_time < cutoff:
                continue  # within_days 내 기사 없음 → 후보 제외
            embeddings = [
                [float(x) for x in r.embedding] for r in rows if r.embedding is not None
            ]
            centroid = _centroid(embeddings)
            if centroid is None:
                continue  # 임베딩 없는 이벤트는 유사도 후보 불가
            result.append(
                CandidateEvent(
                    canonical_id=raw.get("canonical_id"),
                    companies=list(raw.get("companies") or []),
                    embedding=centroid,
                    event_time=event_time,
                )
            )
        result.sort(key=lambda c: c.event_time or datetime.min.replace(tzinfo=UTC), reverse=True)
        return result

    async def get_shared_events(
        self, company_a: str, company_b: str, within_days: int
    ) -> SubjectQueryResponse:
        events_raw = await graph_repo.get_shared_events(self._graph, company_a, company_b)
        subject_found = await graph_repo.companies_exist(self._graph, [company_a, company_b])
        events, overall, daily_counts = await self._assemble(events_raw, within_days)
        return SubjectQueryResponse(
            subject=f"{company_a} & {company_b}",
            subject_found=subject_found,
            events=events,
            overall_gauge=overall,
            daily_counts=daily_counts,
        )

    async def _assemble(
        self, events_raw: list[dict], within_days: int
    ) -> tuple[list[EventWithArticles], SentimentGauge, list[DailyCount]]:
        """그래프 이벤트 + PG 집계를 합쳐 (EventWithArticles[], overall_gauge, daily_counts) 로.

        within_days 내 최신 기사가 있는 이벤트만 포함, importance 내림차순 정렬. daily_counts 는
        그 '포함된 이벤트'들의 기사만 발행일(KST)별로 세므로 게이지·기사수와 같은 모집단을 본다.
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
        included_ids: list[uuid.UUID] = []
        pos = neu = neg = 0
        for eid, raw in by_uuid.items():
            agg = aggregates.get(eid)
            if agg is None or agg.recency is None or agg.recency < cutoff:
                continue  # within_days 내 기사 없음 → 제외
            included_ids.append(eid)
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
                        ArticleRef(
                            news_id=r.id,
                            summary=r.summary or "",
                            url=r.url,
                            title=r.title or "",
                            publisher=r.publisher,
                            published_at=r.published_at,
                        )
                        for r in rows
                    ],
                    gauge=gauge,
                )
            )

        # importance 내림차순(없으면 뒤로).
        items.sort(key=lambda x: (x.event.importance is not None, x.event.importance or 0.0), reverse=True)
        overall = SentimentGauge(positive=pos, neutral=neu, negative=neg)

        # 포함된 이벤트들의 기사만 발행일(KST)별로 집계(오름차순). 게이지와 같은 모집단.
        count_rows = await news_repo.get_daily_article_counts(self._session, included_ids)
        daily_counts = [DailyCount(date=r.day, count=r.count) for r in count_rows]
        return items, overall, daily_counts
