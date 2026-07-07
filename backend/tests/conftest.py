"""테스트 공통 fixture.

- DB: docker PostgreSQL(5433) 실제 사용. 테스트별 트랜잭션 + savepoint 롤백으로 격리
  (schema 는 이미 alembic 로 적용돼 있다고 가정 — 테스트에서 migration 실행하지 않음).
- AI: FakeAIClient 로 mock(실제 AI 서버 호출 없음).
- TEST_DATABASE_URL 없으면 DATABASE_URL 사용.
"""

from __future__ import annotations

import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from db.session import get_session
from src.api.deps import get_ai_client
from src.api.main import app
from tests.fixtures.ai_output import NORMAL_OUTPUT

_TEST_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


class FakeAIClient:
    """analyze_technical 이 미리 지정한 output(dict)을 반환. 실제 네트워크 없음."""

    def __init__(self, output: dict) -> None:
        self._output = output

    async def analyze_technical(self, payload: dict) -> dict:
        return self._output


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """트랜잭션 안에서 세션 제공 → 종료 시 롤백(테스트 데이터 비영속)."""
    engine = create_async_engine(_TEST_DB_URL)
    conn = await engine.connect()
    trans = await conn.begin()
    session = AsyncSession(
        bind=conn,
        join_transaction_mode="create_savepoint",  # service 의 commit 을 savepoint 로 흡수
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()
        await engine.dispose()


@pytest_asyncio.fixture
def ai_output() -> dict:
    """기본 AI output(정상). 개별 테스트에서 override 가능."""
    return NORMAL_OUTPUT


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, ai_output: dict) -> AsyncClient:
    """앱 세션/AIClient 를 테스트용으로 교체한 httpx AsyncClient."""

    async def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_ai_client] = lambda: FakeAIClient(ai_output)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
