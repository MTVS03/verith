"""technical_report_interpretations — 해석 (통합 ERD Technical, 1:1)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import uuid_pk


class TechnicalReportInterpretation(Base):
    __tablename__ = "technical_report_interpretations"

    id: Mapped[uuid.UUID] = uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technical_reports.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # 정본 §9: LLM 실패 시에도 template_fallback 문장으로 안전착지 → NOT NULL.
    interpretation: Mapped[str] = mapped_column(Text, nullable=False)
    interpretation_source: Mapped[str] = mapped_column(String, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String, nullable=True)
    template_fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False)
    detail_source_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sections: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
