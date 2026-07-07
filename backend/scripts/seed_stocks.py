"""stocks 종목 마스터 seed (idempotent).

Technical Agent 지원 10종을 `stocks` 에 미리 넣어, 이후 Stock Resolver 가 첫 리포트 생성 전에도
이름↔코드↔시장을 조회할 수 있게 한다. `stocks` 는 공통 종목 마스터이므로 seed 는 **기존 row 를
덮어쓰지 않는다**(`INSERT ... ON CONFLICT(stock_code) DO NOTHING`). 여러 번 실행해도 안전.

실행:
    cd backend
    uv run python -m scripts.seed_stocks
    # 또는
    uv run python scripts/seed_stocks.py

전제: PostgreSQL 실행 중 + `DATABASE_URL`(backend/.env, 포트 5433) 설정. DB URL/비밀번호는
코드에 하드코딩하지 않고 기존 backend config/session 을 재사용한다.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

# `python scripts/seed_stocks.py` 직접 실행도 되도록 backend 루트를 import path 에 올린다.
_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from db.models.common.stock import Stock  # noqa: E402
from db.session import async_session_factory, engine  # noqa: E402

# 종목 정본은 backend 단일 정의(constants)에서 읽는다 — seed 는 별도 목록을 두지 않는다.
from src.api.constants.stocks import SUPPORTED_STOCKS  # noqa: E402


async def seed(session: AsyncSession) -> dict:
    """SUPPORTED_STOCKS 를 idempotent 하게 insert(DO NOTHING). commit 은 호출자 몫.

    반환: {"requested", "inserted", "skipped", "inserted_codes"}.
    RETURNING 으로 이번에 실제 insert 된 코드만 집계한다(기존 row 는 건드리지 않음).
    """
    stmt = (
        pg_insert(Stock)
        .values(SUPPORTED_STOCKS)
        .on_conflict_do_nothing(index_elements=[Stock.stock_code])
        .returning(Stock.stock_code)
    )
    result = await session.execute(stmt)
    inserted_codes = [row[0] for row in result]
    await session.flush()
    return {
        "requested": len(SUPPORTED_STOCKS),
        "inserted": len(inserted_codes),
        "skipped": len(SUPPORTED_STOCKS) - len(inserted_codes),
        "inserted_codes": inserted_codes,
    }


async def main() -> None:
    async with async_session_factory() as session:
        summary = await seed(session)
        await session.commit()
    await engine.dispose()

    print(
        f"[seed_stocks] requested={summary['requested']} "
        f"inserted={summary['inserted']} skipped(existing)={summary['skipped']}"
    )
    inserted = set(summary["inserted_codes"])
    for s in SUPPORTED_STOCKS:
        mark = "NEW " if s["stock_code"] in inserted else "skip"
        print(f"  [{mark}] {s['stock_code']} {s['market']:6} {s['stock_name']}")


if __name__ == "__main__":
    asyncio.run(main())
