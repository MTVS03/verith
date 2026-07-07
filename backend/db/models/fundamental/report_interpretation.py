"""fundamental_report_interpretations — LLM/규칙 해석 (통합 ERD Fundamental, 1:1)."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import uuid_pk


class FundamentalReportInterpretation(Base):
    __tablename__ = "fundamental_report_interpretations"

    id: Mapped[uuid.UUID] = uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fundamental_reports.id"), nullable=False, unique=True
    )
    interpretation: Mapped[str | None] = mapped_column(Text, nullable=True)
    interpretation_source: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
