"""technical_reports — 기술적 분석 리포트 root (통합 ERD Technical)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import created_at, uuid_pk


class TechnicalReport(Base):
    __tablename__ = "technical_reports"

    id: Mapped[uuid.UUID] = uuid_pk()
    # 항상 존재하는 실행 메타데이터 → NOT NULL.
    request_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    client_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    stock_name: Mapped[str | None] = mapped_column(String, nullable=True)
    original_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_focus: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 정본 §9: degraded 에도 sentinel(unavailable/neutral)로 항상 채움 → NOT NULL.
    final_regime: Mapped[str] = mapped_column(String, nullable=False)
    daily_regime: Mapped[str] = mapped_column(String, nullable=False)
    weekly_trend: Mapped[str | None] = mapped_column(String, nullable=True)
    monthly_trend: Mapped[str | None] = mapped_column(String, nullable=True)
    alignment_flag: Mapped[str] = mapped_column(String, nullable=False)
    regime_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 정본 §9: data_limited B / regime_unavailable 에서 NULL 가능 → nullable 유지.
    consensus: Mapped[str | None] = mapped_column(String, nullable=True)
    signal_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_basis: Mapped[str | None] = mapped_column(String, nullable=True)
    data_status: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    trace_id: Mapped[str] = mapped_column(String, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String, nullable=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at()
    input_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        Index(
            "ix_technical_reports_client_session_id_created_at",
            "client_session_id",
            text("created_at DESC"),
        ),
        Index("ix_technical_reports_ticker_as_of", "ticker", text("as_of DESC")),
        Index("ix_technical_reports_trace_id", "trace_id"),
    )
