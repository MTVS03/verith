"""주식당일분봉조회 fetcher 테스트 (mock 기반, 실제 KIS 호출 없음).

output2→IntradayCandle 매핑·timestamp 결합·숫자 정규화·output1 메타데이터·역방향 페이징·
dedupe/sort·limit·빈 응답·high<low 거부, 그리고 헤더 tr_id·필수 FID 파라미터를 확인한다.
"""

from __future__ import annotations

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
          vol: str = "120") -> dict:
    return {
        "stck_bsop_date": "20260706", "stck_cntg_hour": hour,
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
    assert len(calls["hours"]) <= kc.MINUTE_MAX_CALLS


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
