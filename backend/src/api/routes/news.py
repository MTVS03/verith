"""news 라우트 — POST /news/batch/save (SCHEMA_SPEC §7.2).

라우터는 얇게(가이드 §4.2): 요청 검증 → service 위임 → SaveResponse 반환.
저장/조회 로직은 service·repository 소관.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_news_service
from src.api.schemas.news import NewsBatchSaveRequest, SaveResponse
from src.api.services.news_service import NewsService

router = APIRouter(prefix="/news", tags=["news"])


@router.post("/batch/save", response_model=SaveResponse)
async def save_batch(
    req: NewsBatchSaveRequest,
    service: NewsService = Depends(get_news_service),
) -> SaveResponse:
    """기사(PostgreSQL) + GraphBatch(Neo4j MERGE)를 한 배치로 저장."""
    return await service.save_batch(req)
