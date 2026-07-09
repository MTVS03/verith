"""stock_code(6자리) -> DART corp_code(8자리) 변환 + 원문 무결성 검증."""
from __future__ import annotations

from dataclasses import dataclass
import io
import time
from typing import Literal
import xml.etree.ElementTree as ET
import zipfile

import httpx

from ..core.config import CORP_CODE_MAP, STOCK_NAME_MAP, settings


class UnknownStockCodeError(KeyError):
    """backend 정본과 static fallback에서 모두 찾지 못한 종목코드."""


class CorpCodeRepositoryUnavailable(RuntimeError):
    """backend 정본 조회 경계가 설정되지 않았거나 일시적으로 사용할 수 없음."""


class CorpCodeRepositoryQueryError(RuntimeError):
    """backend 정본 조회가 명시적으로 실패함."""


CorpCodeSource = Literal["backend_stock_corp_codes", "static_fallback"]
CORP_CODE_FALLBACK_STATIC_FLAG = "CORP_CODE_FALLBACK_STATIC"


@dataclass(frozen=True)
class CorpCodeResolution:
    stock_code: str
    corp_code: str
    corp_name: str | None
    source: CorpCodeSource
    risk_flags: tuple[str, ...] = ()


_RESOLUTION_CACHE: dict[str, CorpCodeResolution] = {}


def clear_resolution_cache() -> None:
    _RESOLUTION_CACHE.clear()


def _normalize_db_url(db_url: str) -> str:
    if db_url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + db_url.removeprefix("postgresql+asyncpg://")
    if db_url.startswith("postgres+asyncpg://"):
        return "postgres://" + db_url.removeprefix("postgres+asyncpg://")
    return db_url


def _backend_lookup(stock_code: str) -> CorpCodeResolution | None:
    db_url = settings.VERITH_DB_URL.strip()
    if not db_url:
        raise CorpCodeRepositoryUnavailable("VERITH_DB_URL is not configured")

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise CorpCodeRepositoryUnavailable("psycopg dependency is not installed") from exc

    timeout = max(settings.CORP_CODE_DB_TIMEOUT_SECONDS, 0.1)
    statement_timeout_ms = int(timeout * 1000)
    conninfo = _normalize_db_url(db_url)
    query = """
        SELECT stock_code, corp_code, corp_name_from_dart
        FROM stock_corp_codes
        WHERE stock_code = %s
        LIMIT 1
    """
    try:
        with psycopg.connect(
            conninfo,
            connect_timeout=timeout,
            options=f"-c statement_timeout={statement_timeout_ms}",
            row_factory=dict_row,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (stock_code,))
                row = cur.fetchone()
    except psycopg.Error as exc:
        raise CorpCodeRepositoryQueryError(type(exc).__name__) from exc

    if row is None:
        return None
    return CorpCodeResolution(
        stock_code=row["stock_code"],
        corp_code=row["corp_code"],
        corp_name=row["corp_name_from_dart"],
        source="backend_stock_corp_codes",
    )


def _lookup_backend_with_retry(stock_code: str) -> CorpCodeResolution | None:
    retries = max(settings.CORP_CODE_DB_RETRIES, 0)
    last_error: CorpCodeRepositoryUnavailable | CorpCodeRepositoryQueryError | None = None
    for attempt in range(retries + 1):
        try:
            return _backend_lookup(stock_code)
        except (CorpCodeRepositoryUnavailable, CorpCodeRepositoryQueryError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.05 * (attempt + 1))
    if last_error is not None:
        raise last_error
    return None


def _static_fallback(stock_code: str) -> CorpCodeResolution:
    try:
        corp_code = CORP_CODE_MAP[stock_code]
    except KeyError:
        raise UnknownStockCodeError(f"unsupported stock_code: {stock_code}") from None
    return CorpCodeResolution(
        stock_code=stock_code,
        corp_code=corp_code,
        corp_name=STOCK_NAME_MAP.get(stock_code),
        source="static_fallback",
        risk_flags=(CORP_CODE_FALLBACK_STATIC_FLAG,),
    )


def resolve_details(stock_code: str) -> CorpCodeResolution:
    cached = _RESOLUTION_CACHE.get(stock_code)
    if cached is not None:
        return cached

    try:
        resolution = _lookup_backend_with_retry(stock_code)
    except (CorpCodeRepositoryUnavailable, CorpCodeRepositoryQueryError):
        resolution = None

    if resolution is None:
        resolution = _static_fallback(stock_code)
    _RESOLUTION_CACHE[stock_code] = resolution
    return resolution


def resolution_metadata(stock_code: str) -> CorpCodeResolution | None:
    return _RESOLUTION_CACHE.get(stock_code)


def resolve(stock_code: str) -> str:
    return resolve_details(stock_code).corp_code


def resolve_name(stock_code: str) -> str:
    try:
        return STOCK_NAME_MAP[stock_code]
    except KeyError:
        raise UnknownStockCodeError(f"unsupported stock_code: {stock_code}") from None


def verify_map_against_dart() -> dict[str, tuple[str, str]]:
    """config 맵을 corpCode.xml 원문과 대조. 반환이 빈 dict면 무결.

    반환: {stock_code: (config값, DART원문값)} — 불일치 항목만.
    """
    resp = httpx.get(
        f"{settings.DART_BASE_URL}/corpCode.xml",
        params={"crtfc_key": settings.DART_API_KEY},
        timeout=30.0,
    )
    resp.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    root = ET.fromstring(zf.read("CORPCODE.xml"))

    dart_map: dict[str, str] = {}
    for node in root.iter("list"):
        sc = (node.findtext("stock_code") or "").strip()
        if sc in CORP_CODE_MAP:
            dart_map[sc] = (node.findtext("corp_code") or "").strip()

    return {
        sc: (cc, dart_map.get(sc, "MISSING"))
        for sc, cc in CORP_CODE_MAP.items()
        if dart_map.get(sc) != cc
    }


if __name__ == "__main__":
    diff = verify_map_against_dart()
    print("corp_code 무결성:", "OK (10/10 일치)" if not diff else f"불일치 발견: {diff}")
