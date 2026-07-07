"""fundamental_reports — 재무 분석 리포트 root (통합 ERD Fundamental)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import created_at, uuid_pk


class FundamentalReport(Base):
    __tablename__ = "fundamental_reports"

    id: Mapped[uuid.UUID] = uuid_pk()
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stock_code: Mapped[str | None] = mapped_column(
        String, ForeignKey("stocks.stock_code"), nullable=True
    )
    corp_code: Mapped[str | None] = mapped_column(String, nullable=True)
    bsns_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fs_div: Mapped[str | None] = mapped_column(String, nullable=True)
    report_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    reprt_code: Mapped[str | None] = mapped_column(String, nullable=True)
    reprt_name: Mapped[str | None] = mapped_column(String, nullable=True)
    period_label: Mapped[str | None] = mapped_column(String, nullable=True)
    verdict_label: Mapped[str | None] = mapped_column(String, nullable=True)
    verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    fin_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_status: Mapped[str | None] = mapped_column(String, nullable=True)
    risk_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    score_breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    report_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dart_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at()
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_fundamental_reports_request_id", "request_id"),
        Index("ix_fundamental_reports_stock_code_as_of", "stock_code", text("as_of DESC")),
        Index("ix_fundamental_reports_trace_id", "trace_id"),
    )
