"""report_filing_snippets — 공시 원문 스니펫 (통합 ERD Fundamental)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import uuid_pk


class ReportFilingSnippet(Base):
    __tablename__ = "report_filing_snippets"

    id: Mapped[uuid.UUID] = uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fundamental_reports.id"), nullable=False
    )
    rcept_no: Mapped[str | None] = mapped_column(String, nullable=True)
    section_name: Mapped[str | None] = mapped_column(String, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
