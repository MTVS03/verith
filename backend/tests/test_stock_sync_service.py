"""stock 마스터 sync 서비스 테스트 (fake fetch, DB rollback, 네트워크 없음)."""

from __future__ import annotations

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models.common.stock import Stock
from src.api.constants.kis_master import MARKET_KOSDAQ, MARKET_KOSPI
from src.api.services.stock_sync_service import StockSyncError, sync_stocks
from tests.fixtures.kis_master import (
    EXPECTED_KOSDAQ,
    EXPECTED_KOSPI,
    KOSDAQ_MST,
    KOSPI_MST,
    mst_bytes,
)

_LOW_MIN = {MARKET_KOSPI: 1, MARKET_KOSDAQ: 1}


def _fake_fetch(kospi: bytes = KOSPI_MST, kosdaq: bytes = KOSDAQ_MST):
    return lambda market: kospi if market == MARKET_KOSPI else kosdaq


async def test_sync_applies_master(db_session):
    summary = await sync_stocks(db_session, fetch_mst=_fake_fetch(), min_counts=_LOW_MIN)
    for code, (name, market) in {**EXPECTED_KOSPI, **EXPECTED_KOSDAQ}.items():
        s = await db_session.get(Stock, code)
        assert s is not None and s.stock_name == name and s.market == market
    assert summary.total_desired == 5
    assert summary.excluded[MARKET_KOSPI]["spac"] == 1
    assert summary.excluded[MARKET_KOSPI]["non_stock_group"] == 2


async def test_sync_idempotent(db_session):
    await sync_stocks(db_session, fetch_mst=_fake_fetch(), min_counts=_LOW_MIN)
    second = await sync_stocks(db_session, fetch_mst=_fake_fetch(), min_counts=_LOW_MIN)
    assert second.inserted == 0 and second.updated == 0
    assert second.unchanged == second.total_desired


async def test_sync_updates_changed_name(db_session):
    await db_session.execute(
        pg_insert(Stock)
        .values(stock_code="051910", stock_name="옛이름", market="KOSPI")
        .on_conflict_do_update(index_elements=[Stock.stock_code], set_={"stock_name": "옛이름"})
    )
    await db_session.flush()
    summary = await sync_stocks(db_session, fetch_mst=_fake_fetch(), min_counts=_LOW_MIN)
    s = await db_session.get(Stock, "051910")
    await db_session.refresh(s)
    assert s.stock_name == "LG화학" and s.updated_at is not None
    assert summary.updated >= 1


async def test_sync_does_not_delete_missing(db_session):
    await db_session.execute(
        pg_insert(Stock)
        .values(stock_code="999999", stock_name="마스터에없는회사", market="KOSPI")
        .on_conflict_do_nothing(index_elements=[Stock.stock_code])
    )
    await db_session.flush()
    summary = await sync_stocks(db_session, fetch_mst=_fake_fetch(), min_counts=_LOW_MIN)
    assert await db_session.get(Stock, "999999") is not None   # 삭제/비활성화 안 함
    assert summary.missing >= 1


async def test_sync_fail_fast_empty_market(db_session):
    with pytest.raises(StockSyncError):
        await sync_stocks(db_session, fetch_mst=_fake_fetch(kospi=mst_bytes([])), min_counts=_LOW_MIN)


async def test_sync_fail_fast_below_min(db_session):
    with pytest.raises(StockSyncError):
        await sync_stocks(db_session, fetch_mst=_fake_fetch(), min_counts={MARKET_KOSPI: 1000, MARKET_KOSDAQ: 1})
