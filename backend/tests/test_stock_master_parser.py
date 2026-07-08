"""KIS 마스터 파서 단위 테스트 (fixture bytes, 네트워크 없음)."""

from __future__ import annotations

import pytest

from src.api.constants.kis_master import (
    FLAG_VALUE_SEMANTICS_VERIFIED,
    MARKET_KOSDAQ,
    MARKET_KOSPI,
)
from src.api.services.stock_master_parser import inspect_rows, parse_master
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
    # 그룹은 ST 이지만 SPAC 플래그가 추정값(Y)이면 제외(공식 필드 우선).
    line = mst_line("900001", "무늬만주권스팩", market=MARKET_KOSPI, group="ST", spac="Y")
    result = parse_master(mst_bytes([line]), MARKET_KOSPI)
    assert result.records == [] and result.excluded["spac"] == 1


# ── 값 semantics 상태: 검산 전 임시 추정(PROVISIONAL) ────────────────────────
def test_flag_value_semantics_marked_provisional():
    assert FLAG_VALUE_SEMANTICS_VERIFIED is False


def test_spac_flag_fail_open_on_unverified_value():
    # 추정값({Y,1}) 밖의 값은 '미설정'으로 보아 **제외하지 않는다**(fail-open — 실제 주권 배제 방지).
    line = mst_line("900002", "추정밖스팩", market=MARKET_KOSPI, group="ST", spac="X")
    result = parse_master(mst_bytes([line]), MARKET_KOSPI)
    assert len(result.records) == 1 and result.excluded["spac"] == 0


# ── --inspect 코어(순수): KOSDAQ 포함 앵커 + 제외 자동 검출 ─────────────────
def test_inspect_rows_kosdaq_inclusion_and_exclusion():
    rows = inspect_rows(KOSDAQ_MST.decode("cp949"), MARKET_KOSDAQ, ["086520", "247540"])
    by_code = {r["code"]: r for r in rows}
    assert by_code["086520"]["group"].strip() == "ST"   # 주권 포함 앵커
    assert by_code["247540"]["group"].strip() == "ST"
    exclusions = [r for r in rows if r["code"] not in ("086520", "247540")]
    assert any(r["group"].strip() == "EN" for r in exclusions)  # ETN(580000) 자동 검출


def test_inspect_rows_kospi_anchors():
    rows = inspect_rows(KOSPI_MST.decode("cp949"), MARKET_KOSPI, ["005930", "069500"])
    by_code = {r["code"]: r for r in rows}
    assert by_code["005930"]["group"].strip() == "ST"
    assert by_code["069500"]["group"].strip() == "EF"   # ETF 앵커(제외 대상)
