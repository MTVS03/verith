"""report_evidence — 비율/주장의 원천 근거 (통합 ERD Fundamental)."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import uuid_pk


class ReportEvidence(Base):
    __tablename__ = "report_evidence"

    id: Mapped[uuid.UUID] = uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fundamental_reports.id"), nullable=False
    )
    # 원문 스니펫 evidence 대비 nullable.
    ratio_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("report_ratios.id"), nullable=True
    )
    metric: Mapped[str | None] = mapped_column(String, nullable=True)
    claim: Mapped[str | None] = mapped_column(String, nullable=True)
    rcept_no: Mapped[str | None] = mapped_column(String, nullable=True)
    bsns_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_period: Mapped[str | None] = mapped_column(String, nullable=True)
    sj_div: Mapped[str | None] = mapped_column(String, nullable=True)
    account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    account_nm: Mapped[str | None] = mapped_column(String, nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    display_value: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
