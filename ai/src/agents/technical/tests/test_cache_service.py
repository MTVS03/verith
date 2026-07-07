"""cache_service 단위 테스트 — in-memory fake Redis(실 Redis 없음).

serialize/deserialize roundtrip·fresh/stale/as_of mismatch·Redis 장애 격리를 결정론으로 검증한다.
now를 주입해 시간 의존성을 제거한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.agents.technical.config import CACHE_FRESH_TTL_SECONDS
from src.agents.technical.schemas.ohlcv import OHLCV
from src.agents.technical.services.cache_service import (
    OhlcvCache,
    as_of_identity,
    default_cache,
)

_NOW = datetime(2026, 7, 7, 0, 0, 0, tzinfo=timezone.utc)


def _candles(n=3):
    return [
        OHLCV(date=f"2026-07-0{i + 1}", open=1000, high=1100, low=900, close=1050,
              volume=123456, trading_value=123456789)
        for i in range(n)
    ]


class FakeRedis:
    """in-memory Redis. fail_get/fail_set로 장애를 시뮬레이션. ex(expire)도 key별로 기록."""

    def __init__(self, *, fail_get=False, fail_set=False):
        self.store: dict[str, str] = {}
        self.ex_by_key: dict[str, int | None] = {}
        self.fail_get = fail_get
        self.fail_set = fail_set
        self.get_calls = 0
        self.set_calls = 0

    def get(self, key):
        self.get_calls += 1
        if self.fail_get:
            raise ConnectionError("redis down")
        return self.store.get(key)

    def set(self, key, value, *, ex=None):
        self.set_calls += 1
        if self.fail_set:
            raise ConnectionError("redis down")
        self.store[key] = value
        self.ex_by_key[key] = ex


def _cache(**kw):
    return OhlcvCache(FakeRedis(**kw))


# ── serialize/deserialize roundtrip ───────────────────────────────────────────
def test_set_get_roundtrip_fresh():
    cache = _cache()
    candles = _candles()
    cache.set("373220", "D", "2026-07-06", candles, now=_NOW)
    look = cache.get("373220", "D", "2026-07-06", now=_NOW)
    assert look.status == "fresh"
    assert [c.model_dump() for c in look.candles] == [c.model_dump() for c in candles]  # 값 보존
    assert look.candles[0].date == "2026-07-01"  # date 문자열 그대로 복원


# ── fresh / stale 경계 ────────────────────────────────────────────────────────
def test_fresh_within_ttl():
    cache = _cache()
    cache.set("373220", "D", "latest", _candles(), now=_NOW)
    look = cache.get("373220", "D", "latest", now=_NOW + timedelta(seconds=CACHE_FRESH_TTL_SECONDS - 1))
    assert look.status == "fresh"


def test_stale_beyond_ttl():
    cache = _cache()
    cache.set("373220", "D", "latest", _candles(), now=_NOW)
    look = cache.get("373220", "D", "latest", now=_NOW + timedelta(seconds=CACHE_FRESH_TTL_SECONDS + 1))
    assert look.status == "stale"
    assert look.candles is not None  # stale도 candles 제공(폴백용)


# ── as_of mismatch → miss ─────────────────────────────────────────────────────
def test_as_of_mismatch_is_miss():
    cache = _cache()
    cache.set("373220", "D", "2026-07-06", _candles(), now=_NOW)
    # 다른 as_of 요청 → fresh/stale 아니라 무조건 miss
    assert cache.get("373220", "D", "2026-07-05", now=_NOW).status == "miss"


def test_absent_key_is_miss():
    assert _cache().get("373220", "W", "latest", now=_NOW).status == "miss"


# ── deserialize 실패 → miss ───────────────────────────────────────────────────
def test_corrupt_entry_is_miss():
    cache = OhlcvCache(fake := FakeRedis())
    fake.store["ohlcv:daily:373220"] = "{ not json"
    assert cache.get("373220", "D", "latest", now=_NOW).status == "miss"


# ── Redis 장애 격리 ───────────────────────────────────────────────────────────
def test_get_failure_returns_miss_not_raise():
    look = _cache(fail_get=True).get("373220", "D", "latest", now=_NOW)
    assert look.status == "miss"  # 예외 전파 없이 miss


def test_set_failure_does_not_raise():
    # set 장애가 호출자 실패로 전파되지 않음(경고만)
    _cache(fail_set=True).set("373220", "D", "latest", _candles(), now=_NOW)  # no raise


@pytest.mark.parametrize("tf,key,ex", [
    ("D", "ohlcv:daily:373220", 86400),        # 1일
    ("W", "ohlcv:weekly:373220", 604800),      # 7일
    ("M", "ohlcv:monthly:373220", 2678400),    # 31일
])
def test_set_uses_stale_expire_seconds(tf, key, ex):
    fake = FakeRedis()
    OhlcvCache(fake).set("373220", tf, "latest", _candles(), now=_NOW)
    assert fake.ex_by_key[key] == ex  # Redis expire = STALE_CACHE_MAX_AGE[tf] × 86400


# ── as_of_identity ────────────────────────────────────────────────────────────
def test_as_of_identity():
    from datetime import date
    assert as_of_identity(date(2026, 7, 6)) == "2026-07-06"
    assert as_of_identity(None) == "latest"


# ── default_cache: REDIS_URL 없으면 None ──────────────────────────────────────
def test_default_cache_none_without_env(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert default_cache() is None


# ── 무결성: ticker/timeframe mismatch → miss (종목 혼입 차단) ──────────────────
def _raw_entry(*, ticker="373220", timeframe="D", as_of="latest", fetched_at, candles=None):
    return json.dumps({
        "ticker": ticker, "timeframe": timeframe, "as_of": as_of,
        "fetched_at": fetched_at, "source": "KIS",
        "candles": [c.model_dump(mode="json") for c in (candles or _candles())],
    })


def _put(fake, key, **entry_kw):
    fake.store[key] = _raw_entry(**entry_kw)


def test_ticker_mismatch_is_miss():
    fake = FakeRedis()
    # 373220 key에 006400 payload가 들어감 → 사용 금지
    _put(fake, "ohlcv:daily:373220", ticker="006400", fetched_at=_NOW.isoformat())
    assert OhlcvCache(fake).get("373220", "D", "latest", now=_NOW).status == "miss"


def test_timeframe_mismatch_is_miss():
    fake = FakeRedis()
    _put(fake, "ohlcv:daily:373220", timeframe="W", fetched_at=_NOW.isoformat())
    assert OhlcvCache(fake).get("373220", "D", "latest", now=_NOW).status == "miss"


def test_mismatch_not_used_as_stale_either():
    fake = FakeRedis()
    old = (_NOW - timedelta(hours=2)).isoformat()  # 나이 오래됨(정상이면 stale)
    _put(fake, "ohlcv:daily:373220", ticker="006400", fetched_at=old)
    assert OhlcvCache(fake).get("373220", "D", "latest", now=_NOW).status == "miss"  # stale도 아님


# ── fetched_at 손상/naive/future → miss (예외 전파 없음) ──────────────────────
def test_naive_fetched_at_is_miss():
    fake = FakeRedis()
    _put(fake, "ohlcv:daily:373220", fetched_at="2026-07-07T00:00:00")  # tz 없음(naive)
    assert OhlcvCache(fake).get("373220", "D", "latest", now=_NOW).status == "miss"  # TypeError 아님


def test_invalid_fetched_at_is_miss():
    fake = FakeRedis()
    _put(fake, "ohlcv:daily:373220", fetched_at="not-a-datetime")
    assert OhlcvCache(fake).get("373220", "D", "latest", now=_NOW).status == "miss"


def test_future_fetched_at_is_miss():
    fake = FakeRedis()
    future = (_NOW + timedelta(hours=1)).isoformat()
    _put(fake, "ohlcv:daily:373220", fetched_at=future)
    assert OhlcvCache(fake).get("373220", "D", "latest", now=_NOW).status == "miss"  # 미래 → fresh 아님
