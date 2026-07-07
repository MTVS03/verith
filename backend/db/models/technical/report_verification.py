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
        ForeignKey("technical_reports.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # 정본 §5.6: verification row 생성 시 gate 결과·outcome·regen_count 는 항상 존재.
    calc_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    regime_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    label_matched: Mapped[bool] = mapped_column(Boolean, nullable=False)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    regen_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_indicators: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    validation_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
