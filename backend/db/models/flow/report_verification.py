"""flow_report_verifications — 검증 (통합 ERD Flow, 1:1)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import uuid_pk


class FlowReportVerification(Base):
    __tablename__ = "flow_report_verifications"

    id: Mapped[uuid.UUID] = uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("flow_reports.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    gate1_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gate2_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gate3_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    checks: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    regen_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
