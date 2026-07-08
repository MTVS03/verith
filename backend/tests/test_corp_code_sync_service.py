"""corp_code sync 서비스 테스트 (fake fetch, DB rollback, 네트워크 없음)."""

from __future__ import annotations

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models.common.stock_corp_code import StockCorpCode
from src.api.services.corp_code_sync_service import (
    CorpCodeSyncError,
    sync_corp_codes,
)
from tests.fixtures.dart_corp_code import CORP_XML, EXPECTED, corp_xml


def _fake_fetch(xml: bytes = CORP_XML):
    return lambda: xml


async def test_sync_applies_listed_only(db_session):
    summary = await sync_corp_codes(db_session, fetch_corp_code=_fake_fetch(), min_count=1)
    for code, (corp_code, name, modify_date) in EXPECTED.items():
        s = await db_session.get(StockCorpCode, code)
        assert s is not None
        assert s.corp_code == corp_code
        assert s.corp_name_from_dart == name
        assert s.modify_date == modify_date       # 형식 이상은 NULL
    assert summary.total_desired == 3             # 상장 3건(비상장 1건 제외)
    assert summary.non_listed == 1
    assert summary.invalid_modify_date == 1
    assert summary.inserted == 3


async def test_sync_idempotent(db_session):
    await sync_corp_codes(db_session, fetch_corp_code=_fake_fetch(), min_count=1)
    second = await sync_corp_codes(db_session, fetch_corp_code=_fake_fetch(), min_count=1)
    assert second.inserted == 0 and second.updated == 0
    assert second.unchanged == second.total_desired


async def test_sync_updates_changed_fields(db_session):
    # 기존 매핑의 corp_name/ modify_date 를 옛 값으로 넣어두고, DART 최신으로 갱신되는지.
    await db_session.execute(
        pg_insert(StockCorpCode)
        .values(
            stock_code="005930",
            corp_code="00126380",
            corp_name_from_dart="옛이름",
            modify_date="20200101",
        )
        .on_conflict_do_update(
            index_elements=[StockCorpCode.stock_code],
            set_={"corp_name_from_dart": "옛이름", "modify_date": "20200101"},
        )
    )
    await db_session.flush()
    summary = await sync_corp_codes(db_session, fetch_corp_code=_fake_fetch(), min_count=1)
    s = await db_session.get(StockCorpCode, "005930")
    await db_session.refresh(s)
    assert s.corp_name_from_dart == "삼성전자" and s.modify_date == "20230101"
    assert s.updated_at is not None
    assert summary.updated >= 1


async def test_sync_does_not_delete_missing(db_session):
    await db_session.execute(
        pg_insert(StockCorpCode)
        .values(
            stock_code="999999",
            corp_code="09999999",
            corp_name_from_dart="DART에없는매핑",
            modify_date=None,
        )
        .on_conflict_do_nothing(index_elements=[StockCorpCode.stock_code])
    )
    await db_session.flush()
    summary = await sync_corp_codes(db_session, fetch_corp_code=_fake_fetch(), min_count=1)
    assert await db_session.get(StockCorpCode, "999999") is not None   # 삭제/비활성화 안 함
    assert summary.missing >= 1


async def test_sync_fail_fast_empty(db_session):
    with pytest.raises(CorpCodeSyncError):
        await sync_corp_codes(db_session, fetch_corp_code=_fake_fetch(corp_xml([])), min_count=1)


async def test_sync_fail_fast_below_min(db_session):
    with pytest.raises(CorpCodeSyncError):
        await sync_corp_codes(db_session, fetch_corp_code=_fake_fetch(), min_count=1000)
