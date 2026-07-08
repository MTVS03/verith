"""stock_aliases seed (idempotent, fail-fast).

`constants/stock_aliases.ALIAS_SEED`(정의 단일 출처)를 읽어 stock_aliases 를 채운다.
normalized_alias 는 `normalize_stock_text` 로 생성한다(직접 작성 금지).

정책:
- 참조하는 stock_code 가 모두 stocks 에 있어야 한다. 하나라도 없으면 **부분 seed 없이 fail-fast**.
- 전체를 **하나의 트랜잭션**으로 처리한다.
- `ON CONFLICT(normalized_alias, stock_code) DO NOTHING` — 기존 alias 를 덮지 않고, 두 번 실행해도
  row 가 증가하지 않는다.

실행(순서 중요 — stocks 먼저):
    cd backend
    uv run python -m scripts.seed_stocks
    uv run python -m scripts.seed_stock_aliases
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
from src.api.constants.stock_aliases import ALIAS_SEED  # noqa: E402
from src.api.text_normalize import normalize_stock_text  # noqa: E402


class AliasSeedError(RuntimeError):
    """seed 전제 위반(정규화 빈값·참조 종목 누락 등) — 부분 seed 대신 즉시 중단."""


def _prepare_rows() -> list[dict]:
    """ALIAS_SEED → 삽입 행(normalized 포함). 정규화 결과가 비면 오류."""
    rows: list[dict] = []
    for a in ALIAS_SEED:
        norm = normalize_stock_text(a["alias"])
        if not norm:
            raise AliasSeedError(f"alias 가 빈 문자열로 정규화됨: {a['alias']!r}")
        rows.append(
            {
                "stock_code": a["stock_code"],
                "alias": a["alias"],
                "normalized_alias": norm,
                "alias_type": a["alias_type"],
            }
        )
    return rows


async def seed(session: AsyncSession) -> dict:
    """alias 를 idempotent 하게 seed. commit 은 호출자 몫. 반환 요약 dict."""
    rows = _prepare_rows()

    referenced = {r["stock_code"] for r in rows}
    existing = set(
        (await session.execute(select(Stock.stock_code).where(Stock.stock_code.in_(referenced)))).scalars()
    )
    missing = sorted(referenced - existing)
    if missing:
        raise AliasSeedError(
            f"stocks 에 없는 종목코드 {len(missing)}개: {missing}. "
            "먼저 scripts.seed_stocks 를 실행하세요(부분 seed 금지)."
        )

    stmt = (
        pg_insert(StockAlias)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=[StockAlias.normalized_alias, StockAlias.stock_code]
        )
        .returning(StockAlias.id)
    )
    result = await session.execute(stmt)
    inserted = len(list(result))
    await session.flush()
    return {"requested": len(rows), "inserted": inserted, "skipped": len(rows) - inserted}


async def main() -> None:
    async with async_session_factory() as session:
        summary = await seed(session)
        await session.commit()
    await engine.dispose()
    print(
        f"[seed_stock_aliases] requested={summary['requested']} "
        f"inserted={summary['inserted']} skipped(existing)={summary['skipped']}"
    )


if __name__ == "__main__":
    asyncio.run(main())
