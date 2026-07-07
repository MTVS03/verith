"""agent_reports — 에이전트 리포트 통합 인덱스 (통합 ERD Common).

agent_report_id 는 각 에이전트 root report 의 id 를 담지만 **DB FK 를 걸지 않는다**
(agent_type 에 따라 앱 레벨에서 technical/fundamental/news/flow/industry 리포트를 참조).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import created_at, uuid_pk


class AgentReport(Base):
    __tablename__ = "agent_reports"

    id: Mapped[uuid.UUID] = uuid_pk()
    agent_type: Mapped[str] = mapped_column(String, nullable=False)
    # 각 agent root report id — app-level reference (FK 아님).
    agent_report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    client_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # external users/sessions 의 id — 논리 링크, FK 걸지 않음.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    owner_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # 뉴스/거시는 종목이 없을 수 있어 nullable.
    stock_code: Mapped[str | None] = mapped_column(
        String, ForeignKey("stocks.stock_code"), nullable=True
    )
    stock_name: Mapped[str | None] = mapped_column(String, nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_status: Mapped[str | None] = mapped_column(String, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at()
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_agent_reports_agent_type_created_at", "agent_type", text("created_at DESC")),
        Index(
            "ix_agent_reports_client_session_id_created_at",
            "client_session_id",
            text("created_at DESC"),
        ),
        Index("ix_agent_reports_stock_code_created_at", "stock_code", text("created_at DESC")),
        Index("ix_agent_reports_trace_id", "trace_id"),
    )
