"""테스트 공통 fixture.

- DB: docker PostgreSQL(5433) 실제 사용. 테스트별 트랜잭션 + savepoint 롤백으로 격리
  (schema 는 이미 alembic 로 적용돼 있다고 가정 — 테스트에서 migration 실행하지 않음).
- DB URL: `TEST_DATABASE_URL` 우선, 없으면 `settings.DATABASE_URL`(= backend/.env 로드).
  둘 다 없거나 접속 불가면 **명확히 fail**(조용한 skip 아님) — "docker compose up postgres" 안내.
- AI: FakeAIClient 로 mock(실제 AI 서버 호출 없음). `ai_output` 을 indirect 로 바꿔 계약위반 등 검증.
"""

from __future__ import annotations

import copy
import os
import warnings

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from db.session import get_session
from src.api.config import settings
from src.api.deps import get_ai_client
from src.api.main import app
from tests.fixtures.ai_output import (
    DUP_OUTPUT,
    MALFORMED_OUTPUT,
    MISMATCH_TICKER_OUTPUT,
    NORMAL_OUTPUT,
)

# 테스트 전용 DB 경계. pytest 는 **전용 test DB(TEST_DATABASE_URL, 예: verith_test)** 를 써야 한다 —
# 공유 dev/smoke DB(DATABASE_URL=verith)에 붙으면 운영 --apply/seed(대량 corp_codes·전체 master) 커밋이
# 테스트 전제를 오염시킨다(DB 역할: docs/db_boundaries.md). TEST_DATABASE_URL 미설정/앱 DB 와 동일하면
# **경고**해 오염 위험을 드러낸다(하드 fail 은 아님 — 기존 로컬 실행 호환).
# os 환경변수(CI) 우선, 없으면 backend/.env(settings) — pydantic 이 로드한 .env 값도 반영된다.
_TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL") or settings.TEST_DATABASE_URL
_TEST_DB_URL = _TEST_DATABASE_URL or settings.DATABASE_URL
if not _TEST_DATABASE_URL:
    warnings.warn(
        "TEST_DATABASE_URL 미설정 — 공유 앱 DB(DATABASE_URL)로 테스트합니다. 운영 데이터 오염 위험. "
        "backend/.env 에 전용 test DB(verith_test)를 두세요.",
        stacklevel=2,
    )
elif _TEST_DATABASE_URL == settings.DATABASE_URL:
    warnings.warn(
        "TEST_DATABASE_URL 이 앱 DATABASE_URL 과 동일합니다 — 테스트가 앱/운영 DB 상태에 오염됩니다. "
        "전용 test DB(verith_test)로 분리하세요.",
        stacklevel=2,
    )

_AI_OUTPUTS: dict[str, dict] = {
    "NORMAL": NORMAL_OUTPUT,
    "DUP": DUP_OUTPUT,
    "MISMATCH": MISMATCH_TICKER_OUTPUT,
    "MALFORMED": MALFORMED_OUTPUT,
}


class FakeAIClient:
    """analyze_technical 이 미리 지정한 output(dict)을 반환. 실제 네트워크 없음."""

    def __init__(self, output: dict) -> None:
        self._output = output

    async def analyze_technical(self, payload: dict) -> dict:
        # 실제 AI 처럼 요청 request_id 를 응답에 echo(placeholder 치환). 매 호출 deepcopy.
        out = copy.deepcopy(self._output)
        if out.get("request_id") == "__REQUEST_ID__":
            out["request_id"] = payload["request_id"]
        return out


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """트랜잭션 안에서 세션 제공 → 종료 시 롤백(테스트 데이터 비영속)."""
    if not _TEST_DB_URL:
        pytest.fail(
            "TEST_DATABASE_URL 또는 DATABASE_URL 이 필요합니다. backend/.env 에 5433 DSN 을 두거나 "
            "TEST_DATABASE_URL 을 설정하세요."
        )
    engine = create_async_engine(_TEST_DB_URL)
    try:
        conn = await engine.connect()
    except Exception as exc:  # noqa: BLE001 — 접속 불가를 명확한 안내로 전환
        await engine.dispose()
        pytest.fail(
            f"테스트 DB 접속 실패({type(exc).__name__}). docker compose up -d postgres 로 "
            "PostgreSQL(5433)을 먼저 띄우세요."
        )
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


@pytest.fixture
def ai_output(request) -> dict:
    """기본 AI output(정상). indirect parametrize 키(DUP/MISMATCH/MALFORMED)로 교체."""
    return _AI_OUTPUTS[getattr(request, "param", "NORMAL")]


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
