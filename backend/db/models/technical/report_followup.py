"""technical_report_followups — 후속 질의 (통합 ERD Technical)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import created_at, uuid_pk


class TechnicalReportFollowup(Base):
    __tablename__ = "technical_report_followups"

    id: Mapped[uuid.UUID] = uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technical_reports.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    client_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    context_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        # created_at ASC (기본 오름차순).
        Index("ix_technical_report_followups_report_id_created_at", "report_id", "created_at"),
    )
