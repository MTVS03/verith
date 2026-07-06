import json
import time
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).resolve().parent / ".cache"
TTL_SECONDS = 60 * 60 * 24  # 연간공시 기준 일 단위면 충분


def _path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def load_cached(key: str) -> Any | None:
    p = _path(key)
    if not p.exists() or time.time() - p.stat().st_mtime > TTL_SECONDS:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_cache(key: str, data: Any) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    _path(key).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")