"""비동기 Neo4j 드라이버/세션.

async neo4j 드라이버 기반. PostgreSQL 의 `db/session.py`(engine + get_session)와 동형으로,
모듈 레벨 단일 드라이버를 두고 요청 스코프 세션을 의존성으로 제공한다.
실제 저장/조회 Cypher(repository)는 이 브랜치 범위가 아니며, 후속 담당자가 `get_graph_session`
의존성으로 세션을 주입받아 구현한다.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession

from src.api.config import settings

# 모듈 레벨 단일 드라이버(커넥션 풀 포함). PostgreSQL `engine` 과 동형.
driver: AsyncDriver = AsyncGraphDatabase.driver(
    settings.NEO4J_URI,
    auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
)


def get_driver() -> AsyncDriver:
    """모듈 레벨 드라이버 반환(부트스트랩·repository 공용)."""
    return driver


async def get_graph_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 의존성용 Neo4j 세션 제공자(PG `get_session` 과 동형)."""
    async with driver.session() as session:
        yield session


async def close_driver() -> None:
    """드라이버 커넥션 풀 정리. 앱 종료(lifespan shutdown)에서 호출."""
    await driver.close()
