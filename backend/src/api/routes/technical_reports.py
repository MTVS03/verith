"""technical report 라우트 — POST/GET/DELETE /api/technical/reports (api_spec §6)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from src.api.clients.ai_client import (
    AIContractError,
    AITimeoutError,
    AIUnavailableError,
    AIValidationError,
)
from src.api.deps import get_technical_report_service
from src.api.schemas.technical_report import (
    TechnicalReportCreateRequest,
    TechnicalReportReadModel,
)
from src.api.services.technical_report_service import TechnicalReportService

router = APIRouter(prefix="/api/technical/reports", tags=["technical-reports"])


@router.post("", response_model=TechnicalReportReadModel, status_code=status.HTTP_201_CREATED)
async def create_technical_report(
    req: TechnicalReportCreateRequest,
    service: TechnicalReportService = Depends(get_technical_report_service),
) -> TechnicalReportReadModel:
    """AI 분석 호출 → 응답 검증 → 저장 → **read model** 반환(프론트 친화, api_spec §6.1)."""
    try:
        return await service.create_report(req)
    except AIValidationError as exc:
        # AI 가 요청(ticker/query)을 거부(422) → 클라이언트 입력 문제
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (AIContractError, AIUnavailableError) as exc:
        # 응답 계약 위반·AI 사용 불가 = upstream 오류 → 502
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except AITimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc


@router.get("/{report_id}", response_model=TechnicalReportReadModel)
async def get_technical_report(
    report_id: UUID,
    service: TechnicalReportService = Depends(get_technical_report_service),
) -> TechnicalReportReadModel:
    """단건 조회 — 프론트 친화 read model(raw payload 는 DB 에 보존, 응답엔 구조화만)."""
    read_model = await service.get_report(report_id)
    if read_model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return read_model


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_technical_report(
    report_id: UUID,
    service: TechnicalReportService = Depends(get_technical_report_service),
) -> Response:
    deleted = await service.delete_report(report_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
