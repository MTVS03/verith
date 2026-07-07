"""stock_aliases — 종목 별칭(변형/영문/약칭/구명/모호그룹).

resolver 가 자연어에서 종목을 식별하는 근거. 공식 이름은 여기 두지 않고 `stocks.stock_name` 정본을
쓴다. 같은 alias 가 여러 stock_code 에 연결될 수 있고(= ambiguous 후보 표현), 이를 위해 UNIQUE 는
`(normalized_alias, stock_code)` 복합이다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import created_at, uuid_pk


class StockAlias(Base):
    __tablename__ = "stock_aliases"

    id: Mapped[uuid.UUID] = uuid_pk()
    stock_code: Mapped[str] = mapped_column(
        String, ForeignKey("stocks.stock_code", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(Text, nullable=False)          # 원문 별칭(표시용)
    normalized_alias: Mapped[str] = mapped_column(Text, nullable=False)  # normalize_stock_text 결과
    alias_type: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        # 같은 alias 가 여러 종목에 연결되는 것은 허용(모호 후보). (normalized_alias, stock_code) 만 유일.
        UniqueConstraint(
            "normalized_alias", "stock_code", name="uq_stock_aliases_normalized_alias_stock_code"
        ),
        CheckConstraint("normalized_alias <> ''", name="ck_stock_aliases_normalized_alias_not_empty"),
        # 위 복합 UNIQUE 가 normalized_alias 선두 검색을 이미 지원하므로 단독 index 는 두지 않는다.
        Index("idx_stock_aliases_stock_code", "stock_code"),
    )
