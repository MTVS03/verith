"""news 라우트 (SCHEMA_SPEC §7.2).

라우터는 얇게(가이드 §4.2): 요청 검증 → service 위임 → 응답 스키마 반환.
저장/조회 로직은 service·repository 소관.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Path, Query

from src.api.deps import (
    get_news_graph_query_service,
    get_news_query_service,
    get_news_service,
)
from src.api.schemas.news import (
    ArticleRef,
    EventArticleStats,
    NewsBatchSaveRequest,
    SaveResponse,
    SubjectQueryResponse,
)
from src.api.services.news_graph_query_service import NewsGraphQueryService
from src.api.services.news_query_service import NewsQueryService
from src.api.services.news_service import NewsService

router = APIRouter(prefix="/news", tags=["news"])


@router.post("/batch/save", response_model=SaveResponse)
async def save_batch(
    req: NewsBatchSaveRequest,
    service: NewsService = Depends(get_news_service),
) -> SaveResponse:
    """기사(PostgreSQL) + GraphBatch(Neo4j MERGE)를 한 배치로 저장."""
    return await service.save_batch(req)


@router.get("/events/stats", response_model=EventArticleStats | None)
async def get_event_stats(
    event_id: uuid.UUID = Query(..., description="Event.canonical_id"),
    service: NewsQueryService = Depends(get_news_query_service),
) -> EventArticleStats | None:
    """이벤트 누적 기사 통계(중요도 입력). 기사 없으면 null."""
    return await service.get_event_stats(event_id)


@router.get("/events/{event_id}/articles", response_model=list[ArticleRef])
async def get_event_articles(
    event_id: uuid.UUID = Path(..., description="Event.canonical_id"),
    limit: int = Query(20, ge=1, le=100, description="최대 기사 수(최신순)"),
    service: NewsQueryService = Depends(get_news_query_service),
) -> list[ArticleRef]:
    """이벤트별 근거 기사(ArticleRef) 최신순 조회(on-demand, limit 로 개수 조절)."""
    return await service.get_articles_by_event(event_id, limit)


@router.get("/query/subject", response_model=SubjectQueryResponse)
async def query_subject(
    companies: list[str] = Query(..., description="종목/회사명(정규화). 별칭이면 여러 개"),
    within_days: int = Query(7, ge=1, le=90, description="최근 N일 기사 있는 이벤트만"),
    service: NewsGraphQueryService = Depends(get_news_graph_query_service),
) -> SubjectQueryResponse:
    """single-hop: 종목 이벤트를 importance순으로(실시간 감성 게이지 포함)."""
    return await service.get_events_by_subject(companies, within_days)


@router.get("/query/shared", response_model=SubjectQueryResponse)
async def query_shared(
    company_a: str = Query(..., description="회사 A(정규화)"),
    company_b: str = Query(..., description="회사 B(정규화)"),
    within_days: int = Query(7, ge=1, le=90, description="최근 N일 기사 있는 이벤트만"),
    service: NewsGraphQueryService = Depends(get_news_graph_query_service),
) -> SubjectQueryResponse:
    """multi-hop: 두 회사가 함께 참여한 공유 이벤트를 importance순으로."""
    return await service.get_shared_events(company_a, company_b, within_days)
