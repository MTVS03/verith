"""stock / stock_aliases 조회 repository (DB 접근만).

resolver 는 종목/별칭 테이블이 작으므로(지원 종목 + 별칭 수십 행) 전체를 로드해 메모리에서
longest-match 판정한다. 별칭 substring 매칭은 인덱스로 가속되지 않으므로 전체 로드가 단순·안전.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.common.stock import Stock
from db.models.common.stock_alias import StockAlias


async def get_all_stocks(session: AsyncSession) -> list[Stock]:
    rows = await session.execute(select(Stock))
    return list(rows.scalars().all())


async def get_all_aliases(session: AsyncSession) -> list[StockAlias]:
    rows = await session.execute(select(StockAlias))
    return list(rows.scalars().all())
