"""모델 공통 컬럼 헬퍼.

타입 규칙(통합 ERD):
- uuid PK = postgres uuid, 기본값 gen_random_uuid()
- created_at/as_of = timestamptz
- base_date = date, JSON = jsonb, 종목코드/ticker = varchar(숫자 금지)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


def uuid_pk() -> Mapped[uuid.UUID]:
    """uuid PK, 서버 기본값 gen_random_uuid() (pgcrypto)."""
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


def created_at() -> Mapped[datetime]:
    """timestamptz, 서버 기본값 now()."""
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
