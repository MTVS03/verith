"""technical_report_signals — 지표 신호 (통합 ERD Technical)."""

from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import uuid_pk


class TechnicalReportSignal(Base):
    __tablename__ = "technical_report_signals"

    id: Mapped[uuid.UUID] = uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technical_reports.id", ondelete="CASCADE"), nullable=False
    )
    # signals row 가 생성되면 indicator/signal/weight 는 항상 존재(정본 §5.2).
    indicator: Mapped[str] = mapped_column(String, nullable=False)
    # timeframe 은 통합 ERD 신규 필드 — 보장 근거 부족으로 nullable 유지.
    timeframe: Mapped[str | None] = mapped_column(String, nullable=True)
    signal: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail_source: Mapped[str | None] = mapped_column(String, nullable=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        # 리포트당 indicator 1개 보장(정본 §7 ux_report_signals_report_indicator).
        UniqueConstraint("report_id", "indicator", name="uq_technical_report_signals_report_id_indicator"),
    )
