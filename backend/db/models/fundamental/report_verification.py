"""fundamental_report_verifications — 검증 결과 (통합 ERD Fundamental, 1:1)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import uuid_pk


class FundamentalReportVerification(Base):
    __tablename__ = "fundamental_report_verifications"

    id: Mapped[uuid.UUID] = uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fundamental_reports.id"), nullable=False, unique=True
    )
    binding_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    consistency_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    verdict_stable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    regen_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guard_violations: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
