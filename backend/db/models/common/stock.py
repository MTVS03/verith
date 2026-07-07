"""stocks — 종목 마스터 (통합 ERD Common)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import created_at


class Stock(Base):
    __tablename__ = "stocks"

    # 종목코드는 varchar(앞자리 0 보존). 숫자 타입 금지.
    stock_code: Mapped[str] = mapped_column(String, primary_key=True)
    stock_name: Mapped[str] = mapped_column(String, nullable=False)
    market: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
