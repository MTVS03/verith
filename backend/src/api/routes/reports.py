"""공통 리포트 목록 라우트 — GET /reports (agent_reports 기준)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.api.deps import get_technical_report_service
from src.api.schemas.agent_report import ReportsListResponse
from src.api.schemas.report_archive import ArchiveListResponse
from src.api.services.technical_report_service import TechnicalReportService

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/archive", response_model=ArchiveListResponse)
async def list_report_archive(
    agent_type: str | None = None,
    client_session_id: str | None = None,
    stock_code: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: TechnicalReportService = Depends(get_technical_report_service),
) -> ArchiveListResponse:
    """리포트 보관함 공통 카드 목록(agent_type 필터, created_at DESC). agent 상세와 분리된 프론트 view model."""
    return await service.list_report_archive(
        agent_type=agent_type, client_session_id=client_session_id,
        stock_code=stock_code, limit=limit, offset=offset,
    )


@router.get("", response_model=ReportsListResponse)
async def list_reports(
    agent_type: str | None = None,
    client_session_id: str | None = None,
    stock_code: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: TechnicalReportService = Depends(get_technical_report_service),
) -> ReportsListResponse:
    items = await service.list_reports(
        agent_type=agent_type,
        client_session_id=client_session_id,
        stock_code=stock_code,
        limit=limit,
        offset=offset,
    )
    return ReportsListResponse(items=items, limit=limit, offset=offset, count=len(items))
