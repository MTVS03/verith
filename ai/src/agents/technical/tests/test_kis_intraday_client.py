"""주식당일분봉조회 fetcher 테스트 (mock 기반, 실제 KIS 호출 없음).

output2→IntradayCandle 매핑·timestamp 결합·숫자 정규화·output1 메타데이터·역방향 페이징·
dedupe/sort·limit·빈 응답·high<low 거부, 그리고 헤더 tr_id·필수 FID 파라미터를 확인한다.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agents.technical.schemas.intraday import IntradayCandle
from src.agents.technical.services import kis_client as kc
from src.agents.technical.services.kis_client import (
    KisFieldError,
    fetch_minute_ohlcv,
    parse_kis_intraday_item,
    parse_kis_intraday_output,
)

# kis_mapping §12.4 output2 원소(필드명 확정). 부가 필드가 있어도 무시한다.
def _out2(hour: str, close: str = "100000", *, high: str = "100500", low: str = "099500",
          vol: str = "120", date: str = "20260706") -> dict:
    return {
        "stck_bsop_date": date, "stck_cntg_hour": hour,
        "stck_oprc": "099900", "stck_hgpr": high, "stck_lwpr": low,
        "stck_prpr": close, "cntg_vol": vol,
        "acml_tr_pbmn": "123456789",  # 누적 — candle에 매핑되면 안 됨
    }


_OUT1 = {
    "stck_prdy_clpr": "99000", "stck_prpr": "100000",
    "acml_vol": "500000", "acml_tr_pbmn": "987654321",
    "hts_kor_isnm": "LG에너지솔루션",
}


def _resp(output2: list[dict], output1: dict | None = None) -> dict:
    return {"rt_cd": "0", "output1": output1 if output1 is not None else _OUT1, "output2": output2}


def _patch(monkeypatch, responses):
    """load_kis_settings·get_access_token·_call_minute_chart를 mock. responses는 호출순 응답."""
    monkeypatch.setattr(kc, "load_kis_settings", lambda: kc.KISSettings("k", "s", "https://x:9443"))
    monkeypatch.setattr(kc, "get_access_token", lambda **kw: "tok")
    calls = {"hours": []}
    seq = list(responses)

    def fake_call(settings, token, ticker, input_hour, client):
        calls["hours"].append(input_hour)
        return seq.pop(0) if seq else _resp([])

    monkeypatch.setattr(kc, "_call_minute_chart", fake_call)
    return calls


# ── 단건 파싱 ────────────────────────────────────────────────────────────────
def test_parse_item_maps_fields_and_timestamp():
    c = parse_kis_intraday_item(_out2("090500", close="100000"))
    assert isinstance(c, IntradayCandle)
    assert c.timestamp == "2026-07-06T09:05:00"  # bsop_date + cntg_hour 결합
    assert c.close == 100000 and c.high == 100500 and c.low == 99500
    assert c.volume == 120
    assert c.interval == "1min"


def test_parse_item_trading_value_is_none_not_acml():
    c = parse_kis_intraday_item(_out2("090500"))
    assert c.trading_value is None  # acml_tr_pbmn(누적)을 개별 분봉 값으로 매핑하지 않음


def test_parse_item_numeric_strings_normalized():
    c = parse_kis_intraday_item(_out2("090500", close="100250", vol="1500"))
    assert c.close == 100250 and isinstance(c.close, int)
    assert c.volume == 1500 and isinstance(c.volume, int)


def test_parse_item_high_lt_low_rejected():
    with pytest.raises(KisFieldError):  # 스키마 위반 → fail-fast(row skip 아님)
        parse_kis_intraday_item(_out2("090500", high="099000", low="100000"))


def test_parse_item_missing_field_rejected():
    bad = _out2("090500")
    del bad["stck_prpr"]
    with pytest.raises(KisFieldError):
        parse_kis_intraday_item(bad)


def test_parse_item_bad_hour_rejected():
    with pytest.raises(KisFieldError):
        parse_kis_intraday_item(_out2("256000"))  # 존재하지 않는 시각


def test_parse_output_empty():
    assert parse_kis_intraday_output([]) == []


# ── fetch: 단일 페이지 ────────────────────────────────────────────────────────
def test_fetch_single_page_sorted_and_metadata(monkeypatch):
    # 한 배치(역순 반환 흉내: 09:03, 09:01) → 오름차순 정규화
    _patch(monkeypatch, [_resp([_out2("090300", close="102"), _out2("090100", close="101")])])
    result = fetch_minute_ohlcv("373220", input_hour="093000")
    assert [c.timestamp for c in result.candles] == ["2026-07-06T09:01:00", "2026-07-06T09:03:00"]
    assert result.previous_close == 99000.0
    assert result.latest_price == 100000.0
    assert result.cumulative_volume == 500000
    assert result.cumulative_trading_value == 987654321


def test_fetch_empty_output2_returns_empty(monkeypatch):
    _patch(monkeypatch, [_resp([])])
    result = fetch_minute_ohlcv("373220", input_hour="093000")
    assert result.candles == []
    # output1 메타데이터는 여전히 채워짐(첫 응답)
    assert result.previous_close == 99000.0


# ── fetch: 역방향 페이징 · dedupe ─────────────────────────────────────────────
def test_fetch_reverse_paging_dedupe(monkeypatch):
    page1 = _resp([_out2("091000", close="110"), _out2("090900", close="109")])
    page2 = _resp([_out2("090900", close="109"), _out2("090800", close="108")])  # 09:09 중복
    page3 = _resp([])  # 더 없음 → 종료
    calls = _patch(monkeypatch, [page1, page2, page3])
    result = fetch_minute_ohlcv("373220", input_hour="093000")
    ts = [c.timestamp for c in result.candles]
    assert ts == ["2026-07-06T09:08:00", "2026-07-06T09:09:00", "2026-07-06T09:10:00"]  # dedupe
    # 커서가 역방향으로 이동: 첫 호출 093000, 이후 배치 최고(最古) 시각-1분
    assert calls["hours"][0] == "093000"
    assert calls["hours"][1] == "090800"  # 09:09 - 1min


def test_fetch_stops_on_stagnation(monkeypatch):
    # 같은 배치를 계속 주면 정체 감지로 무한 루프 없이 종료
    same = _resp([_out2("091000", close="110")])
    calls = _patch(monkeypatch, [same, same, same, same, same])
    result = fetch_minute_ohlcv("373220", input_hour="093000")
    assert len(result.candles) == 1
    assert len(calls["hours"]) <= kc.INTRADAY_MINUTE_MAX_CALLS  # 페이징 상한 정본 = config §14


def test_fetch_limit_returns_most_recent(monkeypatch):
    page1 = _resp([_out2("091000", close="110"), _out2("090900", close="109"),
                   _out2("090800", close="108")])
    _patch(monkeypatch, [page1, _resp([])])
    result = fetch_minute_ohlcv("373220", input_hour="093000", limit=2)
    ts = [c.timestamp for c in result.candles]
    assert ts == ["2026-07-06T09:09:00", "2026-07-06T09:10:00"]  # 최신 2개


def test_fetch_limit_zero_short_circuits(monkeypatch):
    calls = _patch(monkeypatch, [_resp([_out2("091000")])])
    result = fetch_minute_ohlcv("373220", input_hour="093000", limit=0)
    assert result.candles == []
    assert calls["hours"] == []  # 호출 자체를 하지 않음


# ── 단일 거래일 가드 (역방향 페이징이 직전 영업일로 넘어가지 않게) ────────────────
def test_fetch_same_date_multi_batch_all_returned(monkeypatch):
    # 모든 batch가 같은 날(20260706) → 전부 반환·오름차순·dup 없음(기존 동작 유지)
    b1 = _resp([_out2("093000", close="101"), _out2("092900", close="100")])
    b2 = _resp([_out2("092800", close="99"), _out2("092700", close="98")])
    _patch(monkeypatch, [b1, b2])
    result = fetch_minute_ohlcv("373220", input_hour="093000")
    ts = [c.timestamp for c in result.candles]
    assert {t[:10] for t in ts} == {"2026-07-06"}
    assert ts == sorted(ts) and len(ts) == len(set(ts))
    assert ts[0] == "2026-07-06T09:27:00" and ts[-1] == "2026-07-06T09:30:00"


def test_fetch_stops_when_batch_crosses_to_prev_date(monkeypatch):
    # batch3이 통째로 직전 영업일(20260703) → 07-03 버리고 페이징 중단(추가 호출 없음)
    b1 = _resp([_out2("153000", close="102"), _out2("152900", close="101")])   # 20260706
    b2 = _resp([_out2("152800", close="100"), _out2("152700", close="99")])    # 20260706
    b3 = _resp([_out2("153000", close="90", date="20260703"),                  # 직전 영업일
                _out2("152900", close="89", date="20260703")])
    extra = _resp([_out2("151000", date="20260703")])  # 절대 소비되면 안 됨
    calls = _patch(monkeypatch, [b1, b2, b3, extra])
    result = fetch_minute_ohlcv("373220", input_hour="153000")
    assert {c.timestamp[:10] for c in result.candles} == {"2026-07-06"}  # 07-03 없음
    assert len(calls["hours"]) == 3  # b1·b2·b3까지만 호출(extra 미소비 = paging stop)


def test_fetch_mixed_date_within_batch_keeps_target_only(monkeypatch):
    # 한 batch에 07-06·07-03이 섞임 → 07-06만 keep, 07-03 drop, stop(fail-safe)
    b1 = _resp([_out2("091000", close="100")])                    # 07-06 → target 확정
    b2 = _resp([_out2("090100", close="99"),                      # 07-06
                _out2("153000", close="80", date="20260703")])    # 07-03 섞임
    extra = _resp([_out2("152900", date="20260703")])  # 소비 금지
    calls = _patch(monkeypatch, [b1, b2, extra])
    result = fetch_minute_ohlcv("373220", input_hour="091000")
    assert [c.timestamp for c in result.candles] == ["2026-07-06T09:01:00", "2026-07-06T09:10:00"]
    assert len(calls["hours"]) == 2  # b2에서 stop, extra 미소비


def test_fetch_first_batch_prev_date_returns_single_date(monkeypatch):
    # 첫 non-empty batch가 직전 영업일만 → 그 날짜를 target으로 단일 날짜 결과 허용
    # (fetcher는 single-date만 보장; as_of.date() 불일치 생략은 supervisor 몫)
    b1 = _resp([_out2("153000", close="100", date="20260703"),
                _out2("152900", close="99", date="20260703")])
    _patch(monkeypatch, [b1])  # 이후 empty
    result = fetch_minute_ohlcv("373220", input_hour="153000")
    assert {c.timestamp[:10] for c in result.candles} == {"2026-07-03"}  # 단일 날짜(허용)
    assert len(result.candles) == 2


def test_fetch_input_hour_153000_smoke_single_date(monkeypatch):
    # 실측 smoke 재현: 07-06 15:30 시작 → 페이징이 07-03으로 넘어가려 하면 07-06만 남김.
    # normalized first/last timestamp가 모두 07-06이어야 한다(날짜 혼입 회귀).
    b1 = _resp([_out2("153000", close="102"), _out2("150100", close="101")])   # 07-06
    b2 = _resp([_out2("150000", close="100"), _out2("143100", close="99")])    # 07-06
    b3 = _resp([_out2("153000", close="90", date="20260703")])                 # 07-03 진입 시도
    _patch(monkeypatch, [b1, b2, b3])
    result = fetch_minute_ohlcv("373220", input_hour="153000")
    ts = [c.timestamp for c in result.candles]
    assert ts, "07-06 candles present"
    assert ts[0][:10] == "2026-07-06" and ts[-1][:10] == "2026-07-06"  # first·last 모두 07-06
    assert all(t[:10] == "2026-07-06" for t in ts)


# ── input_hour 검증 (네트워크 호출 전 fail-fast) ──────────────────────────────
@pytest.mark.parametrize("hh", ["083000", "153000", "235959", "000000"])
def test_input_hour_valid_accepted(monkeypatch, hh):
    calls = _patch(monkeypatch, [_resp([_out2("090100", close="101")])])
    result = fetch_minute_ohlcv("373220", input_hour=hh)
    assert result.candles  # 정상 진행
    assert calls["hours"][0] == hh  # 검증 통과 후 그대로 전달


@pytest.mark.parametrize("hh", ["240000", "256000", "126099", "12:30:00", "abc123", "", "09300", "0930000"])
def test_input_hour_invalid_rejected_before_network(monkeypatch, hh):
    calls = _patch(monkeypatch, [_resp([_out2("090100")])])
    with pytest.raises(KisFieldError):
        fetch_minute_ohlcv("373220", input_hour=hh)
    assert calls["hours"] == []  # 네트워크(_call_minute_chart) 호출 전에 거부


def test_input_hour_none_uses_as_of_or_now(monkeypatch):
    # 기존 동작 유지: input_hour=None이면 as_of 시각(있으면)으로 진행, 예외 없음.
    calls = _patch(monkeypatch, [_resp([_out2("143000", close="101")])])
    result = fetch_minute_ohlcv("373220", as_of=datetime(2026, 7, 6, 14, 30, 0), input_hour=None)
    assert result.candles
    assert calls["hours"][0] == "143000"  # as_of 시각에서 커서 시작


def test_validate_hhmmss_helper():
    assert kc._validate_hhmmss("093000", field="input_hour") == "093000"
    assert kc._validate_hhmmss(" 235959 ", field="input_hour") == "235959"  # strip
    for bad in ["240000", "256000", "126099", "12:30:00", "abc123", "", "1230"]:
        with pytest.raises(KisFieldError):
            kc._validate_hhmmss(bad, field="input_hour")


# ── 요청 헤더/파라미터 (실제 _call_minute_chart 경유, fake httpx client) ────────
class _FakeResp:
    status_code = 200
    text = ""

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _FakeClient:
    def __init__(self, data):
        self._data = data
        self.calls = []

    def get(self, url, headers=None, params=None):
        self.calls.append({"url": url, "headers": headers, "params": params})
        return _FakeResp(self._data)

    def close(self):
        pass


def test_request_header_tr_id_and_fid_params(monkeypatch):
    monkeypatch.setattr(kc, "load_kis_settings", lambda: kc.KISSettings("k", "s", "https://x:9443"))
    monkeypatch.setattr(kc, "get_access_token", lambda **kw: "tok")
    fake = _FakeClient(_resp([_out2("091000")]))
    fetch_minute_ohlcv("373220", input_hour="093000", client=fake)

    req = fake.calls[0]
    assert req["headers"]["tr_id"] == "FHKST03010200"
    assert req["url"].endswith("/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice")
    for key in ("FID_COND_MRKT_DIV_CODE", "FID_INPUT_ISCD", "FID_INPUT_HOUR_1",
                "FID_PW_DATA_INCU_YN", "FID_ETC_CLS_CODE"):
        assert key in req["params"]
    assert req["params"]["FID_INPUT_ISCD"] == "373220"
    assert req["params"]["FID_INPUT_HOUR_1"] == "093000"
    # 계좌번호는 요청에 없음(env 추가 없이 token/header 흐름 재사용)
    assert not any("ACCOUNT" in k.upper() for k in req["params"])
    assert not any("ACCOUNT" in k.upper() for k in req["headers"])


# ── as_of(UTC) → KST 조회시각 변환 (1d intraday 실패 회귀) ──────────────────────
def test_resolve_input_hour_converts_utc_to_kst():
    """백엔드가 UTC(tz-aware) as_of를 넘기면 KIS 조회시각(HHMMSS)은 KST여야 한다.

    회귀: 예전엔 UTC 시각을 그대로 넣어(12:15 KST→03:15) 장전 조회→전일 봉→날짜 가드 탈락으로
    모든 리포트에서 1d가 사라졌다."""
    utc_noon_kst = datetime(2026, 7, 9, 3, 15, 18, tzinfo=timezone.utc)  # = 12:15:18 KST
    assert kc._resolve_input_hour(utc_noon_kst, None) == "121518"


def test_resolve_input_hour_naive_datetime_unchanged():
    """naive datetime 은 이미 KST로 간주 — 기존 동작 유지(변환 안 함)."""
    assert kc._resolve_input_hour(datetime(2026, 7, 9, 12, 15, 18), None) == "121518"


def test_resolve_input_hour_explicit_overrides_as_of():
    """명시 input_hour 는 as_of/타임존과 무관하게 우선."""
    utc_dt = datetime(2026, 7, 9, 3, 15, 18, tzinfo=timezone.utc)
    assert kc._resolve_input_hour(utc_dt, "093000") == "093000"
