"""stock_corp_codes 조회 repository (DB 접근만).

DART 법인식별 정본(stock_code → corp_code)을 읽는 accessor. 이번 브랜치에서는 조회 endpoint 나
AI wiring 을 붙이지 않는다 — 다음 브랜치에서 fundamental 이 이 accessor(또는 그 위 endpoint)를 통해
내부 CORP_CODE_MAP 대신 backend 정본을 소비할 진입점이다.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.common.stock_corp_code import StockCorpCode


async def get_corp_code(session: AsyncSession, stock_code: str) -> StockCorpCode | None:
    """stock_code 의 corp_code 매핑 1건. 없으면 None(예외 아님)."""
    return await session.get(StockCorpCode, stock_code)


async def get_all_corp_codes(session: AsyncSession) -> list[StockCorpCode]:
    rows = await session.execute(select(StockCorpCode))
    return list(rows.scalars().all())
