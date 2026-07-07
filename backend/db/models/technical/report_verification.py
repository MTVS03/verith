"""technical_report_verifications — 검증 (통합 ERD Technical, 1:1)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import uuid_pk


class TechnicalReportVerification(Base):
    __tablename__ = "technical_report_verifications"

    id: Mapped[uuid.UUID] = uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technical_reports.id"), nullable=False, unique=True
    )
    calc_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    regime_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    label_matched: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    regen_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_indicators: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    validation_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
