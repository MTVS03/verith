import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).resolve().parent / ".cache"
TTL_SECONDS = 60 * 60 * 24  # 연간공시 기준 일 단위면 충분


@dataclass(frozen=True)
class CacheInspection:
    key: str
    path: str
    exists: bool
    fresh: bool
    age_seconds: float | None
    ttl_seconds: int


def _path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def inspect_cache(key: str, *, ttl_seconds: int = TTL_SECONDS) -> CacheInspection:
    p = _path(key)
    if not p.exists():
        return CacheInspection(
            key=key,
            path=str(p),
            exists=False,
            fresh=False,
            age_seconds=None,
            ttl_seconds=ttl_seconds,
        )
    age = time.time() - p.stat().st_mtime
    return CacheInspection(
        key=key,
        path=str(p),
        exists=True,
        fresh=age <= ttl_seconds,
        age_seconds=age,
        ttl_seconds=ttl_seconds,
    )


def load_cached(key: str) -> Any | None:
    inspection = inspect_cache(key)
    if not inspection.exists or not inspection.fresh:
        return None
    try:
        return json.loads(_path(key).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_cached_any_age(key: str) -> Any | None:
    if not _path(key).exists():
        return None
    try:
        return json.loads(_path(key).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_cache(key: str, data: Any) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    _path(key).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
