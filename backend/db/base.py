"""SQLAlchemy 선언적 Base.

모든 ORM 모델은 이 `Base` 를 상속한다. Alembic autogenerate/비교가 안정적으로
동작하도록 제약/인덱스 **네이밍 컨벤션**을 metadata 에 고정한다.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# 제약/인덱스 이름을 결정적으로 생성 → 마이그레이션 diff/rename 안정화.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
