"""대표 확장 종목 seed (idempotent) — battery 밖 대형주로 stocks 확장.

`constants/stocks.REPRESENTATIVE_STOCKS`(1차 대표 3종: 삼성전자·삼성전자우·카카오)와
`constants/stock_aliases.REPRESENTATIVE_ALIAS_SEED`(변형 alias)를 읽어 stocks/stock_aliases 를 채운다.
battery bootstrap seed(`seed_stocks`/`seed_stock_aliases`)와 **분리된 경로**이며, 기존 정본을 덮지 않는다
(`INSERT ... ON CONFLICT DO NOTHING`). 여러 번 실행해도 안전.

목적: resolver/supervisor/technical 확장 smoke 를 battery 밖 종목으로 실제 검증 가능하게 만든다.
전체 KIS 종목 마스터 승격은 별도 운영 단계(`sync_stocks`).

실행:
    cd backend
    uv run python -m scripts.seed_representative_stocks

전제: PostgreSQL 실행 중 + `DATABASE_URL`(backend/.env, 포트 5433). DB 크리덴셜은 코드에 하드코딩하지
않고 기존 backend config/session 을 재사용한다.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from db.models.common.stock import Stock  # noqa: E402
from db.models.common.stock_alias import StockAlias  # noqa: E402
from db.session import async_session_factory, engine  # noqa: E402
from src.api.constants.stock_aliases import REPRESENTATIVE_ALIAS_SEED  # noqa: E402
from src.api.constants.stocks import REPRESENTATIVE_STOCKS  # noqa: E402
from src.api.text_normalize import normalize_stock_text  # noqa: E402


class RepresentativeSeedError(RuntimeError):
    """seed 전제 위반(정규화 빈값·참조 종목 누락 등) — 부분 seed 대신 즉시 중단."""


async def seed(session: AsyncSession) -> dict:
    """REPRESENTATIVE_STOCKS + REPRESENTATIVE_ALIAS_SEED 를 idempotent 하게 seed. commit 은 호출자 몫."""
    # 1) 대표 종목(stocks) — 기존 row 는 덮지 않는다.
    stock_stmt = (
        pg_insert(Stock)
        .values(REPRESENTATIVE_STOCKS)
        .on_conflict_do_nothing(index_elements=[Stock.stock_code])
        .returning(Stock.stock_code)
    )
    inserted_stocks = list((await session.execute(stock_stmt)).scalars())

    # 2) 대표 별칭(stock_aliases) — 정규화 후 삽입. 참조 종목이 stocks 에 있어야 한다(1에서 보장).
    alias_rows: list[dict] = []
    for a in REPRESENTATIVE_ALIAS_SEED:
        norm = normalize_stock_text(a["alias"])
        if not norm:
            raise RepresentativeSeedError(f"alias 가 빈 문자열로 정규화됨: {a['alias']!r}")
        alias_rows.append({
            "stock_code": a["stock_code"], "alias": a["alias"],
            "normalized_alias": norm, "alias_type": a["alias_type"],
        })

    referenced = {r["stock_code"] for r in alias_rows}
    present = set(
        (await session.execute(select(Stock.stock_code).where(Stock.stock_code.in_(referenced)))).scalars()
    )
    missing = sorted(referenced - present)
    if missing:
        raise RepresentativeSeedError(f"stocks 에 없는 대표 종목코드 {missing} — 부분 seed 금지")

    alias_stmt = (
        pg_insert(StockAlias)
        .values(alias_rows)
        .on_conflict_do_nothing(index_elements=[StockAlias.normalized_alias, StockAlias.stock_code])
        .returning(StockAlias.id)
    )
    inserted_aliases = len(list((await session.execute(alias_stmt)).scalars()))
    await session.flush()
    return {
        "stocks_requested": len(REPRESENTATIVE_STOCKS),
        "stocks_inserted": len(inserted_stocks),
        "aliases_requested": len(alias_rows),
        "aliases_inserted": inserted_aliases,
        "inserted_codes": inserted_stocks,
    }


async def main() -> None:
    async with async_session_factory() as session:
        summary = await seed(session)
        await session.commit()
    await engine.dispose()
    print(f"[seed_representative_stocks] {summary}")


if __name__ == "__main__":
    asyncio.run(main())
