"""news — 기사 원본 (통합 ERD News, PostgreSQL).

embedding 은 pgvector `vector`. 차원(dimension)이 코드/문서에 확정 숫자로 없어
**dimensionless `Vector()`** 로 둔다(추후 ANN 인덱스 확정 시 별도 migration 에서 차원 부여).
event_id 는 Neo4j Event.canonical_id 논리 링크 — **DB FK 를 걸지 않는다**.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, Float, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import created_at


class News(Base):
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    publisher: Mapped[str | None] = mapped_column(String, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String, nullable=True)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Neo4j Event.canonical_id 논리 링크 (FK 아님).
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        Index("ix_news_event_id", "event_id"),
        Index("ix_news_published_at", "published_at"),
    )
