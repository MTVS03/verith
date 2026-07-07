"""stocks seed 스크립트 검증.

DB: docker PostgreSQL(트랜잭션 롤백 격리, conftest db_session). seed() 로직을 테스트 세션에서
직접 실행한다(스크립트 main() 의 실 commit 은 쓰지 않음). 공용/seed 된 DB 상태에도 견고하게 작성.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models.common.stock import Stock
from scripts.seed_stocks import SUPPORTED_STOCKS, seed


async def test_seed_matches_supported_exactly(db_session):
    """seed 후 10종의 stock_code·stock_name·market 이 SUPPORTED_STOCKS 와 완전 일치."""
    await seed(db_session)
    for expected in SUPPORTED_STOCKS:
        row = await db_session.get(Stock, expected["stock_code"])
        assert row is not None, expected["stock_code"]
        assert isinstance(row.stock_code, str)                     # 문자열(앞자리 0 보존)
        assert row.stock_code == expected["stock_code"]
        assert row.stock_name == expected["stock_name"]            # 이름 뒤바뀜 검출
        assert row.market == expected["market"]                    # 시장 뒤바뀜 검출


async def test_seed_is_idempotent(db_session):
    await seed(db_session)
    count1 = await db_session.scalar(select(func.count()).select_from(Stock))
    second = await seed(db_session)
    count2 = await db_session.scalar(select(func.count()).select_from(Stock))
    assert second["inserted"] == 0          # 두 번째엔 새로 안 들어감
    assert count1 == count2                  # row 수 중복 증가 없음


async def test_seed_does_not_overwrite_existing(db_session):
    code = SUPPORTED_STOCKS[0]["stock_code"]  # 051910 (seed 값=LG화학/KOSPI)
    # 기존 마스터가 다른 값을 갖도록 강제(존재/미존재 무관하게 sentinel 로 upsert).
    await db_session.execute(
        pg_insert(Stock)
        .values(stock_code=code, stock_name="사용자정의명", market="XX")
        .on_conflict_do_update(
            index_elements=[Stock.stock_code],
            set_={"stock_name": "사용자정의명", "market": "XX"},
        )
    )
    await db_session.flush()

    await seed(db_session)  # DO NOTHING → 기존 값 유지

    row = await db_session.get(Stock, code)
    assert row.stock_name == "사용자정의명"  # seed 가 덮어쓰지 않음
    assert row.market == "XX"
