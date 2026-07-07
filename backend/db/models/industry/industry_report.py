"""industry_reports — 산업/섹터 리포트 placeholder (통합 ERD 5번째 에이전트).

아직 세부 ERD 미정. request/answer 중심의 최소 컬럼만 둔다.
(초기 스캐폴드의 industry 폴더 자리에 대응 — 5번째 에이전트를 industry 로 확정.)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import created_at, uuid_pk


class IndustryReport(Base):
    __tablename__ = "industry_reports"

    id: Mapped[uuid.UUID] = uuid_pk()
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    client_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_status: Mapped[str | None] = mapped_column(String, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at()
    input_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
