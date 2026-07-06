"""노드 3 — 데이터수집. ticker → KIS D/W/M OHLCV.

얇은 어댑터(architecture.md §3): 계산 로직 없음. `services/kis_client.fetch_multi_timeframe_ohlcv`
를 호출만 한다. fetcher를 주입 가능하게 두어 테스트에서 실 KIS 호출 없이 검증한다.

이 단계 범위: Redis/cache·재시도 분기·계약 조립은 하지 않는다(supervisor 몫). 수집 실패는
조용히 빈 데이터로 바꾸지 않고 fetcher의 예외를 그대로 전파한다(technical_coding_guidelines §8.3).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime

from ..schemas.ohlcv import OHLCV
from ..services.kis_client import (
    ALLOWED_PERIODS,
    fetch_multi_timeframe_ohlcv,
    normalize_end_date,
)

# 주입 가능한 fetcher 타입: (ticker, *, end_date) → {"D": [...], "W": [...], "M": [...]}
OhlcvFetcher = Callable[..., dict[str, Sequence[OHLCV]]]

_EXPECTED_PERIODS = frozenset(ALLOWED_PERIODS)  # {"D", "W", "M"} (config 상수 재사용, 하드코딩 금지)


def run_data_collect(
    ticker: str,
    *,
    as_of: datetime | date | str | None = None,
    fetcher: OhlcvFetcher = fetch_multi_timeframe_ohlcv,
) -> dict[str, Sequence[OHLCV]]:
    """ticker의 D/W/M OHLCV를 수집해 dict로 반환한다(키 = D/W/M).

    `as_of`를 KIS 조회 종료일(`end_date`)로 번역해 fetcher에 넘긴다(kis_mapping §8.2) — 없으면
    fetcher의 기본(오늘 기준) 동작. fetcher는 기본값이 실제 KIS 호출이며 테스트는 fake를 주입한다.
    반환 전에 출력 envelope(정확히 D/W/M 키, 각 값이 OHLCV 시퀀스)을 검증한다(fail-fast).
    """
    if not ticker:
        raise ValueError("ticker is required for data_collect")
    end_date = normalize_end_date(as_of)  # as_of → end_date(date|None). 미래/형식 오류는 여기서 ValueError
    result = fetcher(ticker, end_date=end_date)
    _validate_collection_envelope(result)
    return result


def _validate_collection_envelope(result: object) -> None:
    """data_collect 출력 경계 검증. OHLCV 필드 재검증이 아니라 묶음 구조만 본다."""
    if not isinstance(result, dict):
        raise ValueError(f"data_collect 출력은 dict여야 합니다: {type(result).__name__}")

    keys = set(result)
    if keys != _EXPECTED_PERIODS:
        missing = _EXPECTED_PERIODS - keys
        extra = keys - _EXPECTED_PERIODS
        raise ValueError(
            f"data_collect 출력 키는 정확히 {sorted(_EXPECTED_PERIODS)}여야 합니다 "
            f"(누락={sorted(missing)}, 초과={sorted(extra)})"
        )

    for period, bars in result.items():
        # str/bytes는 Sequence처럼 보여도 OHLCV 묶음이 아니므로 거부.
        if isinstance(bars, (str, bytes)) or not isinstance(bars, Sequence):
            raise ValueError(f"'{period}' 값은 OHLCV 시퀀스여야 합니다: {type(bars).__name__}")
        for item in bars:
            if not isinstance(item, OHLCV):
                raise ValueError(f"'{period}' 시퀀스 원소는 OHLCV여야 합니다: {type(item).__name__}")
