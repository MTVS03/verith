"""kis_client 매핑·검증 단위테스트 (mock 기반, 실제 KIS 호출 없음).

검증 ①(계산 정확성)의 KIS 응답 변환 축(test_plan.md §3 CALC-04)과, allowlist·period 검증을 다룬다.
실호출 검증은 이미 완료된 단계(kis_mapping §11)이므로 여기서는 재호출하지 않는다.
"""

from __future__ import annotations

import pytest

from src.agents.technical.schemas.ohlcv import OHLCV
from src.agents.technical.services import kis_client as kc
from src.agents.technical.services.kis_client import (
    InvalidPeriodError,
    KisFieldError,
    OutOfScopeTickerError,
    fetch_multi_timeframe_ohlcv,
    parse_kis_ohlcv_item,
    parse_kis_ohlcv_output,
    validate_period,
    validate_ticker,
)

# kis_mapping §11.3 실측 output2 원소(373220 D, 최신). 매핑 외 부가 필드도 그대로 포함.
SAMPLE_ITEM = {
    "stck_bsop_date": "20260703",
    "stck_clpr": "362500",
    "stck_oprc": "359500",
    "stck_hgpr": "363500",
    "stck_lwpr": "342500",
    "acml_vol": "397490",
    "acml_tr_pbmn": "141122636250",
    "flng_cls_code": "00",
    "prtt_rate": "0.00",
    "mod_yn": "N",
    "prdy_vrss_sign": "2",
    "prdy_vrss": "8500",
    "revl_issu_reas": "",
}

ALLOWED_TICKER = "373220"   # LG에너지솔루션 (allowlist)
OUT_OF_SCOPE_TICKER = "005930"  # 삼성전자 (allowlist 밖)


# ── 1. output2 1건 정상 변환 ──────────────────────────────────────────────────
def test_parse_item_returns_ohlcv():
    bar = parse_kis_ohlcv_item(SAMPLE_ITEM)
    assert isinstance(bar, OHLCV)


# ── 2. stck_bsop_date → date (ISO 정규화) ────────────────────────────────────
def test_date_normalized_to_iso():
    bar = parse_kis_ohlcv_item(SAMPLE_ITEM)
    assert bar.date == "2026-07-03"


# ── 3. stck_oprc/hgpr/lwpr/clpr → open/high/low/close ────────────────────────
def test_price_fields_mapped():
    bar = parse_kis_ohlcv_item(SAMPLE_ITEM)
    assert bar.open == 359500
    assert bar.high == 363500
    assert bar.low == 342500
    assert bar.close == 362500


# ── 4. acml_vol → volume ─────────────────────────────────────────────────────
def test_volume_mapped():
    bar = parse_kis_ohlcv_item(SAMPLE_ITEM)
    assert bar.volume == 397490 and isinstance(bar.volume, int)


# ── 5. acml_tr_pbmn → trading_value ──────────────────────────────────────────
def test_trading_value_mapped():
    bar = parse_kis_ohlcv_item(SAMPLE_ITEM)
    assert bar.trading_value == 141122636250 and isinstance(bar.trading_value, int)


# ── 6. 숫자 문자열 → int/float 안전 변환 ──────────────────────────────────────
def test_numeric_string_conversion_int_and_float():
    int_bar = parse_kis_ohlcv_item(SAMPLE_ITEM)
    assert isinstance(int_bar.open, int)  # 정수 문자열 → int

    float_item = {**SAMPLE_ITEM, "stck_oprc": "1000.5"}
    float_bar = parse_kis_ohlcv_item(float_item)
    assert float_bar.open == 1000.5 and isinstance(float_bar.open, float)


# ── 7. 필수 필드 누락 → KisFieldError ─────────────────────────────────────────
def test_missing_required_field_raises():
    broken = {k: v for k, v in SAMPLE_ITEM.items() if k != "acml_tr_pbmn"}
    with pytest.raises(KisFieldError):
        parse_kis_ohlcv_item(broken)


def test_empty_numeric_string_raises():
    broken = {**SAMPLE_ITEM, "acml_vol": ""}
    with pytest.raises(KisFieldError):
        parse_kis_ohlcv_item(broken)


# ── 8·9. allowlist 통과 / 거부 ────────────────────────────────────────────────
def test_allowed_ticker_passes():
    validate_ticker(ALLOWED_TICKER)  # 예외 없어야 정상


def test_out_of_scope_ticker_rejected():
    with pytest.raises(OutOfScopeTickerError):
        validate_ticker(OUT_OF_SCOPE_TICKER)


# ── 10·11. period 통과 / 거부 ─────────────────────────────────────────────────
@pytest.mark.parametrize("period", ["D", "W", "M"])
def test_valid_period_passes(period):
    validate_period(period)  # 예외 없어야 정상


@pytest.mark.parametrize("period", ["Y", "d", "1d", "", "DD"])
def test_invalid_period_rejected(period):
    with pytest.raises(InvalidPeriodError):
        validate_period(period)


# ── 정렬: KIS 최신→과거 입력을 과거→최신(ascending)으로 정규화 ────────────────
def test_output_sorted_ascending():
    newest = {**SAMPLE_ITEM, "stck_bsop_date": "20260703"}
    older = {**SAMPLE_ITEM, "stck_bsop_date": "20260702"}
    oldest = {**SAMPLE_ITEM, "stck_bsop_date": "20260701"}
    bars = parse_kis_ohlcv_output([newest, older, oldest])  # KIS 순서(최신 우선)
    assert [b.date for b in bars] == ["2026-07-01", "2026-07-02", "2026-07-03"]


# ── 빈 output2 → 빈 리스트 정책 ───────────────────────────────────────────────
def test_empty_output_returns_empty_list():
    assert parse_kis_ohlcv_output([]) == []


# ── 12. fetch_multi_timeframe_ohlcv 가 D/W/M 세 period를 사용하는지 (mock) ─────
def test_multi_timeframe_uses_dwm(monkeypatch):
    called = []

    def fake_fetch_ohlcv(ticker, period, **kwargs):
        called.append(period)
        return [parse_kis_ohlcv_item(SAMPLE_ITEM)]

    monkeypatch.setattr(kc, "fetch_ohlcv", fake_fetch_ohlcv)
    result = fetch_multi_timeframe_ohlcv(ALLOWED_TICKER)

    assert called == ["D", "W", "M"]          # 세 타임프레임 직접 호출
    assert set(result.keys()) == {"D", "W", "M"}
    assert all(isinstance(bars, list) for bars in result.values())


def test_multi_timeframe_rejects_out_of_scope(monkeypatch):
    monkeypatch.setattr(kc, "fetch_ohlcv", lambda *a, **k: [])
    with pytest.raises(OutOfScopeTickerError):
        fetch_multi_timeframe_ohlcv(OUT_OF_SCOPE_TICKER)


# ── 13. 리샘플 관련 함수·상수가 존재하지 않음 (일봉→주/월 리샘플 금지) ────────
def test_no_resample_symbols():
    names = [n for n in dir(kc) if "resample" in n.lower()]
    assert names == []
