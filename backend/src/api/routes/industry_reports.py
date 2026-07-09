"""industry report 라우트 — POST/GET/LIST/DELETE."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse
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
from src.api.schemas.industry_report import (
    IndustryReportCreateRequest,
    IndustryReportEnvelope,
    IndustryReportListResponse,
)
from src.api.services.industry_report_service import IndustryReportService

router = APIRouter(prefix="/api/industry/reports", tags=["industry-reports"])


async def get_industry_report_service(
    session: AsyncSession = Depends(get_session),
    ai_client: AIClient = Depends(get_ai_client),
) -> AsyncGenerator[IndustryReportService, None]:
    yield IndustryReportService(session=session, ai_client=ai_client)


@router.post("", response_model=IndustryReportEnvelope, status_code=status.HTTP_201_CREATED)
async def create_industry_report(
    req: IndustryReportCreateRequest,
    service: IndustryReportService = Depends(get_industry_report_service),
) -> IndustryReportEnvelope:
    try:
        return await service.create_report(req)
    except AIValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (AIContractError, AIUnavailableError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except AITimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc


@router.get("", response_model=IndustryReportListResponse)
async def list_industry_reports(
    client_session_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: IndustryReportService = Depends(get_industry_report_service),
) -> IndustryReportListResponse:
    return await service.list_reports(
        client_session_id=client_session_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{report_id}", response_model=IndustryReportEnvelope)
async def get_industry_report(
    report_id: UUID,
    service: IndustryReportService = Depends(get_industry_report_service),
) -> IndustryReportEnvelope:
    envelope = await service.get_report(report_id)
    if envelope is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return envelope


@router.get("/{report_id}/html", response_class=HTMLResponse)
async def get_industry_report_html(
    report_id: UUID,
    service: IndustryReportService = Depends(get_industry_report_service),
) -> HTMLResponse:
    """저장된 payload 를 AI 가 완결 HTML 로 렌더 → iframe 이 그대로 로드한다.

    payload 손상(422)은 빈 iframe 대신 422 로 드러낸다(handoff §5).
    """
    try:
        html = await service.get_report_html(report_id)
    except AIValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (AIContractError, AIUnavailableError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except AITimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc
    if html is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return HTMLResponse(content=html)


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_industry_report(
    report_id: UUID,
    service: IndustryReportService = Depends(get_industry_report_service),
) -> Response:
    deleted = await service.delete_report(report_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
