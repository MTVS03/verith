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


# ── Phase A hardening ─────────────────────────────────────────────────────────
def test_kissettings_repr_hides_secret():
    s = kc.KISSettings(api_key="APPKEY123", api_secret="SECRET456", base_url="https://x:9443")
    text = repr(s)
    assert "SECRET456" not in text and "APPKEY123" not in text
    assert "https://x:9443" in text  # base_url은 노출 OK


def test_to_iso_date_valid():
    assert kc._to_iso_date("20260703") == "2026-07-03"


@pytest.mark.parametrize("bad", ["20260231", "20261301", "2026731", "abcd1234", "20260700"])
def test_to_iso_date_invalid_calendar_raises(bad):
    with pytest.raises(KisFieldError):
        kc._to_iso_date(bad)


def _patch_fetch_deps(monkeypatch, chart_response):
    monkeypatch.setattr(kc, "load_kis_settings",
                        lambda: kc.KISSettings("k", "s", "https://x:9443"))
    monkeypatch.setattr(kc, "get_access_token", lambda **kw: "tok")
    monkeypatch.setattr(kc, "_call_chart", lambda *a, **kw: chart_response)


def test_fetch_ohlcv_output2_key_missing_raises(monkeypatch):
    _patch_fetch_deps(monkeypatch, {"rt_cd": "0"})  # output2 키 자체 없음
    with pytest.raises(KisFieldError):
        kc.fetch_ohlcv("373220", "D")


def test_fetch_ohlcv_output2_not_list_raises(monkeypatch):
    _patch_fetch_deps(monkeypatch, {"rt_cd": "0", "output2": "oops"})
    with pytest.raises(KisFieldError):
        kc.fetch_ohlcv("373220", "D")


def test_fetch_ohlcv_output2_empty_returns_empty(monkeypatch):
    _patch_fetch_deps(monkeypatch, {"rt_cd": "0", "output2": []})
    assert kc.fetch_ohlcv("373220", "D") == []


def test_fetch_ohlcv_output2_normal(monkeypatch):
    _patch_fetch_deps(monkeypatch, {"rt_cd": "0", "output2": [SAMPLE_ITEM]})
    result = kc.fetch_ohlcv("373220", "D")
    assert len(result) == 1 and result[0].date == "2026-07-03"


# ── KIS pagination (PAGE-*, mock 전용) ────────────────────────────────────────
from datetime import date, datetime, timedelta  # noqa: E402

from src.agents.technical.config import (  # noqa: E402
    KIS_FETCH_LOOKBACK_DAYS,
    KIS_MAX_CHUNKS,
)


def _d(ymd: str) -> date:
    return date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))


def _item(ymd: str) -> dict:
    return {**SAMPLE_ITEM, "stck_bsop_date": ymd}


def _mock_market(available_ymd, *, recorder=None, ignore_from=False):
    """KIS mock: 요청 [date_from, date_to] 창의 available date를 최신순 100건 반환."""
    dset = sorted(set(available_ymd))

    def _mock(settings, token, ticker, period, date_from, date_to, client):
        if recorder is not None:
            recorder.append((date_from, date_to))
        lo = "00000000" if ignore_from else date_from
        got = sorted((x for x in dset if lo <= x <= date_to), reverse=True)[:100]
        return {"rt_cd": "0", "output2": [_item(x) for x in got]}
    return _mock


def _mock_fixed(fixed_ymd, *, recorder=None):
    """창과 무관하게 항상 같은 date 1건 반환 (정체 시나리오)."""
    def _mock(settings, token, ticker, period, date_from, date_to, client):
        if recorder is not None:
            recorder.append((date_from, date_to))
        return {"rt_cd": "0", "output2": [_item(fixed_ymd)]}
    return _mock


def _mock_endpoint(*, recorder=None):
    """창의 date_to(최신)만 1건 반환 — 매 청크 과거로 이동(무한 진행 시나리오)."""
    def _mock(settings, token, ticker, period, date_from, date_to, client):
        if recorder is not None:
            recorder.append((date_from, date_to))
        return {"rt_cd": "0", "output2": [_item(date_to)]}
    return _mock


def _patch(monkeypatch, mock):
    monkeypatch.setattr(kc, "load_kis_settings", lambda: kc.KISSettings("k", "s", "https://x:9443"))
    monkeypatch.setattr(kc, "get_access_token", lambda **kw: "tok")
    monkeypatch.setattr(kc, "_call_chart", mock)


def _dates_every(end: date, days: int, step: int = 10) -> list[str]:
    return [(end - timedelta(days=k)).strftime("%Y%m%d") for k in range(0, days + 1, step)]


# PAGE-01 / PAGE-10: period별 기본 lookback을 range 조회에 사용
@pytest.mark.parametrize("period", ["D", "W", "M"])
def test_fetch_ohlcv_uses_period_lookback(monkeypatch, period):
    today = datetime.now().date()
    rec = []
    _patch(monkeypatch, _mock_market(_dates_every(today, KIS_FETCH_LOOKBACK_DAYS[period] + 20), recorder=rec))
    kc.fetch_ohlcv("373220", period)
    expected_start = (today - timedelta(days=KIS_FETCH_LOOKBACK_DAYS[period])).strftime("%Y%m%d")
    assert min(f for f, _ in rec) == expected_start   # start까지 확보
    assert max(t for _, t in rec) == today.strftime("%Y%m%d")  # end=오늘


# PAGE-02 / PAGE-03: 여러 청크 + 과거 방향 진행
def test_multiple_chunks_walk_backward(monkeypatch):
    end = date(2026, 7, 4)
    avail = _dates_every(end, 300, step=15)
    rec = []
    _patch(monkeypatch, _mock_market(avail, recorder=rec))
    kc.fetch_ohlcv_range("373220", "D", (end - timedelta(days=300)).strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    assert len(rec) >= 3                                   # 여러 청크
    date_tos = [t for _, t in rec]
    assert date_tos == sorted(date_tos, reverse=True)      # date_to 감소(과거 방향)


# PAGE-04 / PAGE-05: 경계 dedup + 오름차순
def test_dedup_and_ascending(monkeypatch):
    end = date(2026, 7, 4)
    avail = _dates_every(end, 250, step=5)
    _patch(monkeypatch, _mock_market(avail))
    result = kc.fetch_ohlcv_range("373220", "D",
                                  (end - timedelta(days=250)).strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    dates = [b.date for b in result]
    assert dates == sorted(dates)                          # 과거→최신
    assert len(dates) == len(set(dates))                   # date dedup(경계 중복 제거)


# PAGE-06: 범위 밖 date 제거
def test_range_filter_drops_out_of_range(monkeypatch):
    end = date(2026, 7, 4)
    avail = _dates_every(end, 400, step=10)   # start보다 과거 date도 포함
    # ignore_from=True → 청크가 date_from 아래 date도 반환 → 최종 filter가 제거해야 함
    _patch(monkeypatch, _mock_market(avail, ignore_from=True))
    start = end - timedelta(days=120)
    result = kc.fetch_ohlcv_range("373220", "D", start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    assert result and all(start.isoformat() <= b.date <= end.isoformat() for b in result)


# PAGE-07: 빈 청크 시 중단
def test_empty_chunk_stops(monkeypatch):
    end = date(2026, 7, 4)
    avail = _dates_every(end, 40, step=5)      # 최근 40일에만 데이터
    rec = []
    _patch(monkeypatch, _mock_market(avail, recorder=rec))
    result = kc.fetch_ohlcv_range("373220", "D",
                                  (end - timedelta(days=300)).strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    assert len(rec) == 2                        # 1청크 데이터 + 2청크 빈 배열 → 중단
    assert result and all(b.date >= (end - timedelta(days=40)).isoformat() for b in result)


# PAGE-08: 가장 오래된 date 정체 시 중단
def test_stops_when_oldest_not_progressing(monkeypatch):
    end = date(2026, 7, 4)
    rec = []
    _patch(monkeypatch, _mock_fixed("20260601", recorder=rec))
    kc.fetch_ohlcv_range("373220", "D",
                         (end - timedelta(days=300)).strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    assert len(rec) == 2                        # 2청크째 같은 date → 중단


# PAGE-09 / PAGE-12: MAX_CHUNKS 소진 + start 미달 → 예외(partial 반환 금지)
def test_max_chunks_incomplete_raises(monkeypatch):
    end = date(2026, 7, 4)
    rec = []
    _patch(monkeypatch, _mock_endpoint(recorder=rec))
    # 매우 넓은 범위 + 작은 청크 → 정상 종료 전에 상한 도달
    with pytest.raises(kc.KisRangeIncompleteError) as ei:
        kc.fetch_ohlcv_range("373220", "D",
                             (end - timedelta(days=5000)).strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    msg = str(ei.value)
    assert "373220" in msg and "requested_start" in msg and "oldest_fetched" in msg
    assert len(rec) == KIS_MAX_CHUNKS      # 상한만큼 호출 후 중단


# PAGE-11: MAX_CHUNKS 전에 start 도달 → 정상 반환
def test_reaches_start_within_max_chunks_returns(monkeypatch):
    end = date(2026, 7, 4)
    avail = _dates_every(end, 150, step=10)   # 150일 ÷ chunk 100 → 2청크 < MAX
    _patch(monkeypatch, _mock_market(avail))
    result = kc.fetch_ohlcv_range("373220", "D",
                                  (end - timedelta(days=150)).strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    assert result and [b.date for b in result] == sorted(b.date for b in result)


# PAGE-13: 역전 범위는 토큰/네트워크 전에 fail-fast
def test_reversed_range_fail_fast_before_network(monkeypatch):
    called = {"token": 0, "call": 0}
    monkeypatch.setattr(kc, "load_kis_settings", lambda: kc.KISSettings("k", "s", "https://x"))
    monkeypatch.setattr(kc, "get_access_token",
                        lambda **kw: called.__setitem__("token", called["token"] + 1))
    monkeypatch.setattr(kc, "_call_chart",
                        lambda *a, **k: called.__setitem__("call", called["call"] + 1))
    with pytest.raises(ValueError):
        kc.fetch_ohlcv_range("373220", "D", "20260710", "20260704")
    assert called["token"] == 0 and called["call"] == 0   # 토큰/호출 없음


# PAGE-14: 날짜 입력 형식 엄격화
def test_normalize_date_accepts_two_formats():
    assert kc._normalize_to_date("20260704").isoformat() == "2026-07-04"
    assert kc._normalize_to_date("2026-07-04").isoformat() == "2026-07-04"


@pytest.mark.parametrize("bad", ["2026--07-04", "20-2607-04", "2026/07/04", "2026074", "20261301", "20260231"])
def test_normalize_date_rejects_bad_format(bad):
    with pytest.raises(KisFieldError):
        kc._normalize_to_date(bad)


# PAGE-11: allowlist/period는 pagination에서도 KIS 호출 전 거부
def test_pagination_rejects_out_of_scope(monkeypatch):
    _patch(monkeypatch, _mock_fixed("20260601"))
    with pytest.raises(OutOfScopeTickerError):
        kc.fetch_ohlcv_range("005930", "D", "20260101", "20260704")
    with pytest.raises(InvalidPeriodError):
        kc.fetch_ohlcv_range("373220", "Y", "20260101", "20260704")


# ── inf/nan fail-fast (_to_price) ─────────────────────────────────────────────
@pytest.mark.parametrize("bad", ["Infinity", "-Infinity", "NaN", "nan", "inf", "-inf"])
def test_to_price_rejects_non_finite(bad):
    with pytest.raises(KisFieldError):
        kc._to_price(bad, "stck_clpr")


def test_to_price_accepts_normal():
    assert kc._to_price("359500", "x") == 359500
    assert kc._to_price("1000.5", "x") == 1000.5


def test_parse_item_rejects_infinity_price():
    with pytest.raises(KisFieldError):
        kc.parse_kis_ohlcv_item({**SAMPLE_ITEM, "stck_hgpr": "Infinity"})
