"""stock_corp_codes — DART 법인식별 정본 계층 (stock_code → corp_code).

출처는 DART OpenAPI `corpCode.xml`(상장사만). `stocks`(KIS/KRX 종목 마스터)와 **책임이 다른
별도 계층**이다 — 서로의 정본을 덮지 않는다. `corp_name_from_dart` 는 DART 공시명 원문 보관용이며
`stocks.stock_name` 정본을 대체하지 않는다.

`stock_code → stocks.stock_code` **FK 는 걸지 않는다**(no-FK 논리 링크). DART 상장 전체를 stocks
적재 상태와 무관하게 선반영할 수 있도록 결합을 끊는다(fundamental/industry/news 공용 식별자 계층).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import created_at


class StockCorpCode(Base):
    __tablename__ = "stock_corp_codes"

    # 상장 종목코드(varchar, 앞자리 0 보존). stocks 와 논리 링크지만 물리 FK 는 없음.
    stock_code: Mapped[str] = mapped_column(String, primary_key=True)
    # DART 법인코드(8자리). 종목당 유일해야 함 → UNIQUE.
    corp_code: Mapped[str] = mapped_column(String, nullable=False)
    # DART 공시명 원문(정본 아님 — stocks.stock_name 을 덮지 않음).
    corp_name_from_dart: Mapped[str] = mapped_column(Text, nullable=False)
    # DART modify_date 원문(YYYYMMDD). 형식 이상/부재 시 NULL.
    modify_date: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("corp_code", name="uq_stock_corp_codes_corp_code"),
    )
