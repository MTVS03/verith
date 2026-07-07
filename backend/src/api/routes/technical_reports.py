"""technical report 라우트 — POST/GET/DELETE /technical/reports."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from src.api.clients.ai_client import (
    AITimeoutError,
    AIUnavailableError,
    AIValidationError,
)
from src.api.deps import get_technical_report_service
from src.api.schemas.technical_report import (
    TechnicalReportCreateRequest,
    TechnicalReportDetail,
    TechnicalReportSummary,
)
from src.api.services.technical_report_service import TechnicalReportService

router = APIRouter(prefix="/technical/reports", tags=["technical-reports"])


@router.post("", response_model=TechnicalReportSummary, status_code=status.HTTP_201_CREATED)
async def create_technical_report(
    req: TechnicalReportCreateRequest,
    service: TechnicalReportService = Depends(get_technical_report_service),
) -> TechnicalReportSummary:
    """AI 분석 호출 → 결과 저장 → 요약 반환. AI 실패는 상태코드로 매핑."""
    try:
        return await service.create_report(req)
    except AIValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except AITimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc
    except AIUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/{report_id}", response_model=TechnicalReportDetail)
async def get_technical_report(
    report_id: UUID,
    service: TechnicalReportService = Depends(get_technical_report_service),
) -> TechnicalReportDetail:
    detail = await service.get_report_detail(report_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return detail


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_technical_report(
    report_id: UUID,
    service: TechnicalReportService = Depends(get_technical_report_service),
) -> Response:
    deleted = await service.delete_report(report_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
