"""flow report API 스키마 — save-only(payload 그대로 저장)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from src.api.schemas.agent_report import AgentReportListItem


class FlowReportSaveRequest(BaseModel):
    """POST /api/flow/reports/save 요청 — save-only.

    supervisor 가 만든 flow AgentOutput.payload(storage-spec v1)를 받아 그대로 저장한다.
    backend 는 AI 를 다시 호출하지 않는다(news·fundamental save-only 와 같은 방식).
    """

    payload: dict[str, Any] = Field(description="flow AgentOutput.payload (storage-spec v1)")
    question: str = Field(min_length=1)
    client_session_id: str | None = None


class FlowReportEnvelope(BaseModel):
    """POST/GET 응답 wrapper — { report_id, report }. report 는 payload 형태(재구성)."""

    report_id: UUID
    report: dict[str, Any]


class FlowReportListResponse(BaseModel):
    items: list[AgentReportListItem]
    limit: int
    offset: int
    count: int
