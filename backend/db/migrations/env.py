"""Alembic 마이그레이션 환경 (async / asyncpg).

- DB URL 은 `src.api.config.settings.DATABASE_URL` (asyncpg DSN) 을 사용한다.
- online 마이그레이션은 create_async_engine + connection.run_sync 로 실행한다.
- target_metadata 는 전체 모델을 담은 `Base.metadata` (registry import 로 채운다).
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# backend 루트를 import path 에 추가 (db.*, src.* 절대 import).
_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from db.base import Base  # noqa: E402
from db.models import registry  # noqa: E402,F401  (import 부작용으로 metadata 채움)
from src.api.config import settings  # noqa: E402

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """offline 모드: DSN 문자열만으로 SQL 스크립트 생성."""
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """online 모드: async 엔진으로 접속 후 run_sync 로 마이그레이션 실행."""
    connectable = create_async_engine(settings.DATABASE_URL, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
