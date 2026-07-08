"""flow_reports — 수급/자금흐름 리포트 root (통합 ERD Flow)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import created_at, uuid_pk


class FlowReport(Base):
    __tablename__ = "flow_reports"

    id: Mapped[uuid.UUID] = uuid_pk()
    ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    stock_code: Mapped[str] = mapped_column(
        String, ForeignKey("stocks.stock_code"), nullable=False
    )
    stock_name: Mapped[str | None] = mapped_column(String, nullable=True)
    market: Mapped[str | None] = mapped_column(String, nullable=True)
    base_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    alignment: Mapped[str | None] = mapped_column(String, nullable=True)
    data_status: Mapped[str | None] = mapped_column(String, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    signals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        Index("ix_flow_reports_stock_code_base_date", "stock_code", text("base_date DESC")),
        Index("ix_flow_reports_ticker_base_date", "ticker", text("base_date DESC")),
        Index("ix_flow_reports_trace_id", "trace_id"),
    )
