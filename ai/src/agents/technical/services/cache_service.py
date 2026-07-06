"""Redis OHLCV 캐시 (config.md §7·§8). D/W/M 원본을 timeframe별로 캐시한다(1D 분봉은 범위 밖).

정책(결정 확정):
  - **key는 as_of를 포함하지 않는다**(문서 계약 `ohlcv:daily|weekly|monthly:{ticker}`). 대신 entry에
    `as_of`를 저장하고, 요청 as_of와 다르면 **fresh/stale 모두 쓰지 않고 miss** 처리한다.
  - **fresh**: entry 존재 ∧ as_of 일치 ∧ `fetched_at` 나이 ≤ `CACHE_FRESH_TTL_SECONDS`(15분).
  - **stale**: entry 존재 ∧ as_of 일치 ∧ 나이 > 15분(Redis expire 안이면 stale 폴백 가능).
  - **Redis expire** = `STALE_CACHE_MAX_AGE_BY_PERIOD[tf] × 86400` — 그 안엔 stale로 재사용 가능하게 보존.
  - **Redis 장애를 전파하지 않는다**: get 실패=miss, set 실패=경고+no-op. deserialize 실패=miss.

역직렬화 시 `OHLCV(**c)`로 복원해 계약 검증을 유지한다(chart_builder 입력과 동일 타입). 계산·재시도·폴백
분기는 여기서 하지 않는다(supervisor 몫) — 이 파일은 순수 get/set 캐시 서비스다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol

from ..config import (
    CACHE_FRESH_TTL_SECONDS,
    CACHE_KEY_BY_PERIOD,
    CACHE_SECONDS_PER_DAY,
    STALE_CACHE_MAX_AGE_BY_PERIOD,
)
from ..schemas.ohlcv import OHLCV

logger = logging.getLogger(__name__)


class RedisLike(Protocol):
    """캐시가 쓰는 최소 Redis 인터페이스(구조적 Protocol). 실제 redis.Redis·테스트 fake 모두 호환."""

    def get(self, key: str) -> bytes | str | None: ...
    def set(self, key: str, value: str, *, ex: int | None = None) -> object: ...


CacheStatus = Literal["fresh", "stale", "miss"]


@dataclass(frozen=True)
class CacheLookup:
    """캐시 조회 결과. status=miss면 candles는 None."""
    status: CacheStatus
    candles: list[OHLCV] | None = None


def as_of_identity(end_date: date | None) -> str:
    """정규화된 as_of(end_date) → entry 비교용 식별자. None(오늘 기본)은 'latest'."""
    return end_date.isoformat() if end_date is not None else "latest"


def _key(ticker: str, timeframe: str) -> str:
    return CACHE_KEY_BY_PERIOD[timeframe].format(ticker=ticker)


def _serialize(ticker: str, timeframe: str, as_of_id: str,
               candles: Sequence[OHLCV], *, fetched_at: datetime) -> str:
    return json.dumps(
        {
            "ticker": ticker,
            "timeframe": timeframe,
            "as_of": as_of_id,
            "fetched_at": fetched_at.isoformat(),
            "source": "KIS",
            "candles": [c.model_dump(mode="json") for c in candles],
        },
        ensure_ascii=False,
    )


def _deserialize(raw: bytes | str) -> tuple[str, datetime, list[OHLCV]] | None:
    """(as_of, fetched_at, candles) 복원. 하나라도 깨지면 None(→ miss)."""
    try:
        text = raw.decode() if isinstance(raw, bytes) else raw
        obj = json.loads(text)
        as_of = obj["as_of"]
        fetched_at = datetime.fromisoformat(obj["fetched_at"])
        candles = [OHLCV(**c) for c in obj["candles"]]  # 계약 재검증
        return as_of, fetched_at, candles
    except Exception:  # noqa: BLE001 - 손상된 캐시는 조용히 miss(운영 안전)
        logger.warning("cache_deserialize_failed", exc_info=True)
        return None


class OhlcvCache:
    """Redis 기반 OHLCV 캐시. client(RedisLike)를 주입받는다(테스트는 in-memory fake)."""

    def __init__(self, client: RedisLike):
        self._client = client

    def get(self, ticker: str, timeframe: str, as_of_id: str, *, now: datetime) -> CacheLookup:
        try:
            raw = self._client.get(_key(ticker, timeframe))
        except Exception:  # noqa: BLE001 - Redis 장애는 miss처럼 처리(전파 금지)
            logger.warning("cache_get_failed", extra={"timeframe": timeframe}, exc_info=True)
            return CacheLookup("miss")
        if raw is None:
            return CacheLookup("miss")
        parsed = _deserialize(raw)
        if parsed is None:
            return CacheLookup("miss")
        entry_as_of, fetched_at, candles = parsed
        if entry_as_of != as_of_id:  # as_of 불일치 → fresh/stale 모두 사용 금지
            return CacheLookup("miss")
        age = (now - fetched_at).total_seconds()
        if age <= CACHE_FRESH_TTL_SECONDS:  # 시계 역전(음수)도 fresh로 포함
            return CacheLookup("fresh", candles)
        return CacheLookup("stale", candles)  # Redis expire가 stale 상한을 강제

    def set(self, ticker: str, timeframe: str, as_of_id: str,
            candles: Sequence[OHLCV], *, now: datetime) -> None:
        try:
            payload = _serialize(ticker, timeframe, as_of_id, candles, fetched_at=now)
            ex = STALE_CACHE_MAX_AGE_BY_PERIOD[timeframe] * CACHE_SECONDS_PER_DAY
            self._client.set(_key(ticker, timeframe), payload, ex=ex)
        except Exception:  # noqa: BLE001 - set 실패는 경고만(output 정상 유지)
            logger.warning("cache_set_failed", extra={"timeframe": timeframe}, exc_info=True)


def default_cache() -> OhlcvCache | None:
    """환경변수 `REDIS_URL` 기반 Redis 클라이언트로 캐시 생성. 미설정/미설치/연결 실패면 None(캐시 비활성).

    supervisor 기본은 `cache=None`(캐시 미사용, 기존 동작)이며, 운영에서 이 factory로 만든 캐시를 주입한다.
    """
    try:
        import os

        import redis  # lazy import — 미설치 환경에서도 이 모듈 import는 깨지지 않게

        url = os.getenv("REDIS_URL")
        if not url:
            return None
        return OhlcvCache(redis.Redis.from_url(url))
    except Exception:  # noqa: BLE001 - Redis 미가용이면 캐시 없이 진행
        logger.warning("cache_default_client_unavailable", exc_info=True)
        return None
