"""KIS 종목마스터 순수 파서 (DB·HTTP 의존 없음).

입력: raw .mst bytes(cp949) + market. 출력: 명시적 dataclass 목록 + 제외 사유별 count.
상품 분류는 문자열 offset 추측이 아니라 **공식 tail 필드 mapping**(constants.kis_master)으로만 한다.

포함: 증권그룹구분코드 == 주권(ST) 인 보통주·우선주. 제외: 그 외 그룹(EF/EN/RT/…)·SPAC·ETP.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.api.constants.kis_master import (
    FRONT_CODE,
    FRONT_NAME_START,
    GROUP_CODE_STOCK,
    KOSDAQ_FIELDS,
    KOSDAQ_TAIL,
    KOSPI_FIELDS,
    KOSPI_TAIL,
    MARKET_KOSDAQ,
    MARKET_KOSPI,
    etp_flag_set,
    spac_flag_set,
)

_CODE_RE = re.compile(r"\d{6}")


@dataclass(frozen=True)
class StockRecord:
    stock_code: str
    stock_name: str
    market: str
    is_preferred: bool  # 우선주 구분(참고용 — 이번 sync 는 저장 컬럼 없음, 로그/통계만)


@dataclass
class ParseResult:
    market: str
    records: list[StockRecord]
    excluded: dict[str, int] = field(default_factory=dict)


def _tail_field(tail: str, spec: tuple[int, int]) -> str:
    off, width = spec
    return tail[off : off + width]


def parse_master(raw: bytes, market: str) -> ParseResult:
    """raw .mst → 주권(보통주·우선주)만. market 은 MARKET_KOSPI / MARKET_KOSDAQ."""
    if market == MARKET_KOSPI:
        tail_len, fields = KOSPI_TAIL, KOSPI_FIELDS
    elif market == MARKET_KOSDAQ:
        tail_len, fields = KOSDAQ_TAIL, KOSDAQ_FIELDS
    else:
        raise ValueError(f"unknown market: {market!r}")

    text = raw.decode("cp949")
    records: list[StockRecord] = []
    excluded = {"too_short": 0, "bad_code": 0, "non_stock_group": 0, "spac": 0, "etp": 0, "empty_name": 0}

    for row in text.splitlines():
        if len(row) <= tail_len:
            excluded["too_short"] += 1
            continue
        front, tail = row[: len(row) - tail_len], row[-tail_len:]
        code = front[FRONT_CODE[0] : FRONT_CODE[1]].strip()
        name = front[FRONT_NAME_START:].strip()
        group = _tail_field(tail, fields["group"]).strip().upper()

        if not _CODE_RE.fullmatch(code):
            excluded["bad_code"] += 1
            continue
        if group != GROUP_CODE_STOCK:            # 주권(ST)만 — ETF/ETN/REIT/기타 제외
            excluded["non_stock_group"] += 1
            continue
        if spac_flag_set(_tail_field(tail, fields["spac"])):  # 공식 SPAC 플래그 제외
            excluded["spac"] += 1
            continue
        if etp_flag_set(_tail_field(tail, fields["etp"])):    # ETP 이중 제외
            excluded["etp"] += 1
            continue
        if not name:
            excluded["empty_name"] += 1
            continue

        is_pref = _tail_field(tail, fields["pref"]).strip() not in ("", "0")
        records.append(StockRecord(stock_code=code, stock_name=name, market=market, is_preferred=is_pref))

    return ParseResult(market=market, records=records, excluded=excluded)
