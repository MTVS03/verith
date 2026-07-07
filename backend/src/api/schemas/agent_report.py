"""공통 리포트 목록(agent_reports) API 스키마."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AgentReportListItem(BaseModel):
    """agent_reports row → 목록 항목."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_type: str
    agent_report_id: UUID
    request_id: str | None
    client_session_id: str | None
    stock_code: str | None
    stock_name: str | None
    question: str | None
    answer_text: str | None
    data_status: str | None
    trace_id: str | None
    as_of: datetime | None
    created_at: datetime
    summary: Any | None


class ReportsListResponse(BaseModel):
    """GET /reports 응답 — agent_reports 기준 목록."""

    items: list[AgentReportListItem]
    limit: int
    offset: int
    count: int  # 이번 페이지 반환 개수
