"""Neo4j 제약 부트스트랩.

DATA_MODEL.md §2.1 "권장 유니크 제약" 을 반영해 노드 정체성 키에 uniqueness constraint 를
생성한다. MERGE(upsert) 정합성과 조회 성능의 전제다.

- Event/Company/Keyword/Person/Country : 정체성 키 = `key`
- NewsRef : 정체성 키 = `news_id`(저장 시 url→news_id 로 해소된 값)

`IF NOT EXISTS` 라 여러 번 실행해도 안전(멱등). 앱 시작(lifespan)에서 1회 호출한다.
스키마 정본은 backend 앱 소유이며 Alembic 마이그레이션 대상이 아니다(schema.md §8).
"""

from __future__ import annotations

from neo4j import AsyncDriver

from db.graph.driver import get_driver

# (label, 정체성 속성) — DATA_MODEL.md §2.1.
_KEY_CONSTRAINTS: tuple[tuple[str, str], ...] = (
    ("Event", "key"),
    ("Company", "key"),
    ("Keyword", "key"),
    ("Person", "key"),
    ("Country", "key"),
    ("NewsRef", "news_id"),
)


async def ensure_constraints(driver: AsyncDriver | None = None) -> None:
    """노드 정체성 키 유니크 제약을 생성(멱등)."""
    drv = driver or get_driver()
    async with drv.session() as session:
        for label, prop in _KEY_CONSTRAINTS:
            # 제약 이름을 결정적으로 지정 → 중복 생성/추적 안정화.
            name = f"uq_{label.lower()}_{prop}"
            await session.run(
                f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
            )
