"""테스트용 KIS 종목마스터 .mst bytes 빌더 (실 네트워크 없음).

공식 offset(constants.kis_master)에 맞춰 front+tail 을 조립하고 cp949 로 인코딩한다.
parser 가 이 bytes 를 decode→slice 하면 실제 파일과 동일하게 동작한다.
"""

from __future__ import annotations

from src.api.constants.kis_master import (
    KOSDAQ_FIELDS,
    KOSDAQ_TAIL,
    KOSPI_FIELDS,
    KOSPI_TAIL,
    MARKET_KOSPI,
)


def mst_line(
    code: str,
    name: str,
    *,
    market: str,
    group: str = "ST",
    spac: str = " ",
    etp: str = " ",
    pref: str = "0",
) -> str:
    """한 종목 레코드(문자열). front[0:9]=code, [9:21]=표준코드, [21:]=name; tail=고정폭."""
    tail_len, fields = (KOSPI_TAIL, KOSPI_FIELDS) if market == MARKET_KOSPI else (KOSDAQ_TAIL, KOSDAQ_FIELDS)
    front = code.ljust(9) + (" " * 12) + name
    tail = [" "] * tail_len
    for key, val in (("group", group), ("spac", spac), ("etp", etp), ("pref", pref)):
        off, width = fields[key]
        for k, ch in enumerate(val.ljust(width)[:width]):
            tail[off + k] = ch
    return front + "".join(tail)


def mst_bytes(lines: list[str]) -> bytes:
    return ("\r\n".join(lines) + "\r\n").encode("cp949")


# ── 샘플: KOSPI (보통주·우선주 포함 / ETF·REIT·SPAC 제외 대상) ────────────────
KOSPI_LINES = [
    mst_line("005930", "삼성전자", market=MARKET_KOSPI, group="ST"),
    mst_line("005935", "삼성전자우", market=MARKET_KOSPI, group="ST", pref="1"),
    mst_line("051910", "LG화학", market=MARKET_KOSPI, group="ST"),
    mst_line("069500", "KODEX 200", market=MARKET_KOSPI, group="EF", etp="Y"),   # ETF → 제외
    mst_line("293940", "신한알파리츠", market=MARKET_KOSPI, group="RT"),          # REIT → 제외
    mst_line("400000", "테스트스팩1호", market=MARKET_KOSPI, group="ST", spac="Y"),  # SPAC → 제외
    mst_line("ABC123", "펀드류", market=MARKET_KOSPI, group="ST"),               # 코드 6자리 아님 → 제외
]
KOSDAQ_LINES = [
    mst_line("247540", "에코프로비엠", market="KOSDAQ", group="ST"),
    mst_line("086520", "에코프로", market="KOSDAQ", group="ST"),
    mst_line("580000", "코스닥ETN", market="KOSDAQ", group="EN"),                 # ETN → 제외
]

KOSPI_MST = mst_bytes(KOSPI_LINES)
KOSDAQ_MST = mst_bytes(KOSDAQ_LINES)

# 포함 기대 종목(코드→(이름, market))
EXPECTED_KOSPI = {"005930": ("삼성전자", "KOSPI"), "005935": ("삼성전자우", "KOSPI"), "051910": ("LG화학", "KOSPI")}
EXPECTED_KOSDAQ = {"247540": ("에코프로비엠", "KOSDAQ"), "086520": ("에코프로", "KOSDAQ")}
