"""technical_report_charts — 차트 페이로드 (통합 ERD Technical)."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import uuid_pk


class TechnicalReportChart(Base):
    __tablename__ = "technical_report_charts"

    id: Mapped[uuid.UUID] = uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technical_reports.id"), nullable=False
    )
    period: Mapped[str | None] = mapped_column(String, nullable=True)
    candle_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    chart_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    annotations: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    chart_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_technical_report_charts_report_id_period", "report_id", "period"),
    )
