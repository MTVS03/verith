"""KIS 마스터 파서 단위 테스트 (fixture bytes, 네트워크 없음)."""

from __future__ import annotations

import pytest

from src.api.constants.kis_master import MARKET_KOSDAQ, MARKET_KOSPI
from src.api.services.stock_master_parser import parse_master
from tests.fixtures.kis_master import (
    EXPECTED_KOSDAQ,
    EXPECTED_KOSPI,
    KOSDAQ_MST,
    KOSPI_MST,
    mst_bytes,
    mst_line,
)


def test_kospi_includes_only_stock_group():
    result = parse_master(KOSPI_MST, MARKET_KOSPI)
    got = {r.stock_code: (r.stock_name, r.market) for r in result.records}
    assert got == EXPECTED_KOSPI                       # ST(보통주+우선주)만, ETF/REIT/SPAC/bad 제외
    assert result.excluded["non_stock_group"] == 2     # EF, RT
    assert result.excluded["spac"] == 1
    assert result.excluded["bad_code"] == 1


def test_kosdaq_excludes_etn():
    result = parse_master(KOSDAQ_MST, MARKET_KOSDAQ)
    got = {r.stock_code: (r.stock_name, r.market) for r in result.records}
    assert got == EXPECTED_KOSDAQ
    assert result.excluded["non_stock_group"] == 1     # EN


def test_leading_zero_and_market_preserved():
    result = parse_master(KOSPI_MST, MARKET_KOSPI)
    codes = {r.stock_code for r in result.records}
    assert "005930" in codes and "005935" in codes     # 앞자리 0 문자열 보존
    assert all(r.market == "KOSPI" for r in result.records)


def test_preferred_flag_detected_but_included():
    result = parse_master(KOSPI_MST, MARKET_KOSPI)
    by_code = {r.stock_code: r for r in result.records}
    assert by_code["005935"].is_preferred is True      # 우선주 = 포함(제거 안 함)
    assert by_code["005930"].is_preferred is False


def test_empty_input_yields_no_records():
    assert parse_master(mst_bytes([]), MARKET_KOSPI).records == []


def test_unknown_market_raises():
    with pytest.raises(ValueError):
        parse_master(KOSPI_MST, "NASDAQ")


def test_spac_flag_excludes_even_if_stock_group():
    # 그룹은 ST 이지만 SPAC 플래그가 있으면 제외(공식 필드 우선).
    line = mst_line("900001", "무늬만주권스팩", market=MARKET_KOSPI, group="ST", spac="Y")
    result = parse_master(mst_bytes([line]), MARKET_KOSPI)
    assert result.records == [] and result.excluded["spac"] == 1
