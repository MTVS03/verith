"""technical_report_risk_notes — 리스크 노트 (통합 ERD Technical)."""

from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import uuid_pk


class TechnicalReportRiskNote(Base):
    __tablename__ = "technical_report_risk_notes"

    id: Mapped[uuid.UUID] = uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technical_reports.id", ondelete="CASCADE"), nullable=False
    )
    flag: Mapped[str | None] = mapped_column(String, nullable=True)
    severity: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 'metadata' 는 SQLAlchemy Declarative 예약어 → 컬럼명은 metadata 로 두되 속성명만 회피.
    note_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_technical_report_risk_notes_report_id_severity", "report_id", "severity"),
    )
