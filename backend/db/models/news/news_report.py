"""news_reports — 뉴스 질의 결과 리포트 (통합 ERD News, PostgreSQL).

evidence(근거 news_id 목록)는 jsonb 이며 FK 를 걸지 않는다.
owner_user_id/owner_session_id 는 external 논리 링크 — FK 없음.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import created_at


class NewsReport(Base):
    __tablename__ = "news_reports"

    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent: Mapped[str | None] = mapped_column(String, nullable=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    report_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    owner_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        Index("ix_news_reports_created_at", text("created_at DESC")),
    )
