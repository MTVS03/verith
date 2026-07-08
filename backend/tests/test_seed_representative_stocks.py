"""대표 확장 종목 seed + resolver 확장 검증 (DB rollback 격리, 실 네트워크 없음).

representative seed 를 in-tx 로 적용해(commit 안 함), battery 밖 대표 종목(삼성전자·삼성전자우·카카오)이
resolver 에서 canonical row 기준으로 resolved 되는지 검증한다. dev DB 에 이미 commit 돼 있어도(멱등)
동일하게 통과한다.
"""

from __future__ import annotations

from db.models.common.stock import Stock
from scripts.seed_representative_stocks import seed as seed_repr
from src.api.constants.stocks import REPRESENTATIVE_STOCKS
from src.api.services.stock_resolver_service import StockResolverService


async def test_representative_rows_present_after_seed(db_session):
    await seed_repr(db_session)
    for expected in REPRESENTATIVE_STOCKS:
        row = await db_session.get(Stock, expected["stock_code"])
        assert row is not None, expected["stock_code"]
        assert row.stock_code == expected["stock_code"]          # 앞자리 0 문자열 보존
        assert row.stock_name == expected["stock_name"]
        assert row.market == expected["market"]


async def test_representative_seed_idempotent(db_session):
    await seed_repr(db_session)
    second = await seed_repr(db_session)
    assert second["stocks_inserted"] == 0 and second["aliases_inserted"] == 0


async def test_representative_official_names_resolve(db_session):
    await seed_repr(db_session)
    r = StockResolverService(db_session)
    assert (await r.resolve("삼성전자 차트 어때?")).stock.stock_code == "005930"
    assert (await r.resolve("삼성전자우 분석")).stock.stock_code == "005935"   # 우선주 longest-match
    assert (await r.resolve("카카오 수급 보여줘")).stock.stock_code == "035720"


async def test_representative_aliases_resolve(db_session):
    await seed_repr(db_session)
    r = StockResolverService(db_session)
    assert (await r.resolve("삼전 차트 보여줘")).stock.stock_code == "005930"    # 약칭
    assert (await r.resolve("Kakao 뉴스 정리해줘")).stock.stock_code == "035720"  # 영문
