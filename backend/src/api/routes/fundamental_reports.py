"""fundamental report 라우트 — POST/GET/LIST/DELETE."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session
from src.api.clients.ai_client import (
    AIClient,
    AIContractError,
    AITimeoutError,
    AIUnavailableError,
    AIValidationError,
)
from src.api.deps import get_ai_client
from src.api.schemas.fundamental_report import (
    FundamentalReportCreateRequest,
    FundamentalReportEnvelope,
    FundamentalReportListResponse,
)
from src.api.services.fundamental_report_service import FundamentalReportService

router = APIRouter(prefix="/api/fundamental/reports", tags=["fundamental-reports"])


async def get_fundamental_report_service(
    session: AsyncSession = Depends(get_session),
    ai_client: AIClient = Depends(get_ai_client),
) -> AsyncGenerator[FundamentalReportService, None]:
    yield FundamentalReportService(session=session, ai_client=ai_client)


@router.post("", response_model=FundamentalReportEnvelope, status_code=status.HTTP_201_CREATED)
async def create_fundamental_report(
    req: FundamentalReportCreateRequest,
    service: FundamentalReportService = Depends(get_fundamental_report_service),
) -> FundamentalReportEnvelope:
    try:
        return await service.create_report(req)
    except AIValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (AIContractError, AIUnavailableError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except AITimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc


@router.get("", response_model=FundamentalReportListResponse)
async def list_fundamental_reports(
    stock_code: str = Query(pattern=r"^\d{6}$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: FundamentalReportService = Depends(get_fundamental_report_service),
) -> FundamentalReportListResponse:
    return await service.list_reports(stock_code=stock_code, limit=limit, offset=offset)


@router.get("/{report_id}", response_model=FundamentalReportEnvelope)
async def get_fundamental_report(
    report_id: UUID,
    service: FundamentalReportService = Depends(get_fundamental_report_service),
) -> FundamentalReportEnvelope:
    envelope = await service.get_report(report_id)
    if envelope is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return envelope


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fundamental_report(
    report_id: UUID,
    service: FundamentalReportService = Depends(get_fundamental_report_service),
) -> Response:
    deleted = await service.delete_report(report_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
