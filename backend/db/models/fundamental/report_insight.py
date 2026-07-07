"""report_insights — 배당/주주/감사 등 맥락 인사이트 (통합 ERD Fundamental)."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import uuid_pk


class ReportInsight(Base):
    __tablename__ = "report_insights"

    id: Mapped[uuid.UUID] = uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fundamental_reports.id", ondelete="CASCADE"), nullable=False
    )
    insight_type: Mapped[str | None] = mapped_column(String, nullable=True)
    source_endpoint: Mapped[str | None] = mapped_column(String, nullable=True)
    rcept_no: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
