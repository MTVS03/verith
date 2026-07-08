"""technical report 라우트 — POST/GET/DELETE /api/technical/reports (api_spec §6)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from src.api.clients.ai_client import (
    AIContractError,
    AITimeoutError,
    AIUnavailableError,
    AIValidationError,
)
from src.api.deps import get_technical_report_service
from src.api.schemas.technical_report import (
    FollowupCreateRequest,
    FollowupItem,
    TechnicalChartsReadModel,
    TechnicalReportCreateRequest,
    TechnicalReportFollowupsReadModel,
    TechnicalReportListResponse,
    TechnicalReportReadModel,
    TechnicalTraceDetailReadModel,
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


@router.get("", response_model=TechnicalReportListResponse)
async def list_technical_reports(
    stock_code: str | None = None,
    client_session_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: TechnicalReportService = Depends(get_technical_report_service),
) -> TechnicalReportListResponse:
    """technical report 목록 index(created_at DESC) — 상세 진입 전 탐색/비교용 경량 read model."""
    return await service.list_technical_reports(
        stock_code=stock_code, client_session_id=client_session_id, limit=limit, offset=offset
    )


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


@router.get("/{report_id}/charts", response_model=TechnicalChartsReadModel)
async def get_technical_report_charts(
    report_id: UUID,
    service: TechnicalReportService = Depends(get_technical_report_service),
) -> TechnicalChartsReadModel:
    """차트 탭 렌더용 full payload(period 별 chart_data/annotations). detail 은 메타만."""
    charts = await service.get_report_charts(report_id)
    if charts is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return charts


@router.get("/{report_id}/trace", response_model=TechnicalTraceDetailReadModel)
async def get_technical_report_trace(
    report_id: UUID,
    service: TechnicalReportService = Depends(get_technical_report_service),
) -> TechnicalTraceDetailReadModel:
    """trace drawer 용 단계 재구성(저장값 기반, 단계별 duration 은 미측정 → null)."""
    trace = await service.get_report_trace(report_id)
    if trace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return trace


@router.post(
    "/{report_id}/followups", response_model=FollowupItem, status_code=status.HTTP_201_CREATED
)
async def create_technical_report_followup(
    report_id: UUID,
    req: FollowupCreateRequest,
    service: TechnicalReportService = Depends(get_technical_report_service),
) -> FollowupItem:
    """parent report 기준 후속 질문/답변 저장(answer 는 caller 제공). 응답 = FollowupItem(GET list item 동일)."""
    item = await service.create_followup(report_id, req)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return item


@router.get("/{report_id}/followups", response_model=TechnicalReportFollowupsReadModel)
async def get_technical_report_followups(
    report_id: UUID,
    service: TechnicalReportService = Depends(get_technical_report_service),
) -> TechnicalReportFollowupsReadModel:
    """parent report 기준 후속 질문 대화 흐름(read flow). report 없으면 404, follow-up 0이면 빈 배열."""
    flow = await service.get_report_followups(report_id)
    if flow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return flow


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_technical_report(
    report_id: UUID,
    service: TechnicalReportService = Depends(get_technical_report_service),
) -> Response:
    deleted = await service.delete_report(report_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
