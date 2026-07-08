"""stock_aliases DB 제약 + alias seed 테스트 (PG rollback 격리)."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from db.models.common.stock import Stock
from db.models.common.stock_alias import StockAlias
from scripts.seed_stock_aliases import AliasSeedError
from scripts.seed_stock_aliases import seed as seed_aliases
from scripts.seed_stocks import seed as seed_stocks


async def _count_aliases(session) -> int:
    return await session.scalar(select(func.count()).select_from(StockAlias))


# 18. composite UNIQUE(normalized_alias, stock_code)
async def test_alias_unique_rejects_duplicate(db_session):
    await seed_stocks(db_session)
    await db_session.execute(
        pg_insert(StockAlias).values(
            stock_code="051910", alias="테스트", normalized_alias="테스트", alias_type="english"
        )
    )
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                pg_insert(StockAlias).values(
                    stock_code="051910", alias="테스트2", normalized_alias="테스트", alias_type="korean_variant"
                )
            )


async def test_alias_same_text_different_code_allowed(db_session):
    await seed_stocks(db_session)
    # 같은 normalized_alias, 다른 stock_code → 허용(ambiguous 후보 표현)
    await db_session.execute(
        pg_insert(StockAlias).values(
            [
                {"stock_code": "051910", "alias": "그룹", "normalized_alias": "그룹", "alias_type": "ambiguous_group"},
                {"stock_code": "373220", "alias": "그룹", "normalized_alias": "그룹", "alias_type": "ambiguous_group"},
            ]
        )
    )
    await db_session.flush()
    cnt = await db_session.scalar(
        select(func.count()).select_from(StockAlias).where(StockAlias.normalized_alias == "그룹")
    )
    assert cnt == 2


# 19. FK CASCADE (종목 삭제 → alias 삭제)
async def test_alias_fk_cascade(db_session):
    code = "999001"  # 다른 테이블이 참조하지 않는 신규 코드
    await db_session.execute(
        pg_insert(Stock).values(stock_code=code, stock_name="테스트종목").on_conflict_do_nothing()
    )
    await db_session.execute(
        pg_insert(StockAlias).values(
            stock_code=code, alias="테스트별칭", normalized_alias="테스트별칭", alias_type="english"
        )
    )
    await db_session.flush()
    await db_session.execute(delete(Stock).where(Stock.stock_code == code))
    await db_session.flush()
    cnt = await db_session.scalar(
        select(func.count()).select_from(StockAlias).where(StockAlias.stock_code == code)
    )
    assert cnt == 0


# 20. alias seed idempotency
async def test_alias_seed_idempotent(db_session):
    await seed_stocks(db_session)
    await seed_aliases(db_session)
    cnt1 = await _count_aliases(db_session)
    second = await seed_aliases(db_session)
    cnt2 = await _count_aliases(db_session)
    assert second["inserted"] == 0 and cnt1 == cnt2


# 21. stocks 미seed 상태에서 alias seed fail-fast (부분 seed 금지)
async def test_alias_seed_fail_fast_without_stocks(db_session):
    await db_session.execute(delete(Stock))  # 참조 대상 제거(in-tx)
    await db_session.flush()
    before = await _count_aliases(db_session)
    with pytest.raises(AliasSeedError):
        await seed_aliases(db_session)
    after = await _count_aliases(db_session)
    assert after == before  # 부분 삽입 없음
