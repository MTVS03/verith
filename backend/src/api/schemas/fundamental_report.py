"""fundamental report API 스키마."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from src.api.schemas.agent_report import AgentReportListItem


class FundamentalReportCreateRequest(BaseModel):
    """POST /api/fundamental/reports 요청. request_id/trace_id 는 backend 가 생성한다."""

    ticker: str = Field(pattern=r"^\d{6}$")
    query: str = Field(min_length=1)
    client_session_id: str | None = None
    stock_name: str | None = None


class FundamentalReportEnvelope(BaseModel):
    """POST/GET 응답 wrapper — { report_id, report }."""

    report_id: UUID
    report: dict[str, Any]


class FundamentalReportListResponse(BaseModel):
    """GET /api/fundamental/reports 목록 응답."""

    items: list[AgentReportListItem]
    limit: int
    offset: int
    count: int
