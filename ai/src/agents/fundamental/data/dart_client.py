"""DART fnlttSinglAcntAll 클라이언트 — 원문 수집 전용, 가공 금지(normalize 소관)."""
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import settings
from .cache import load_cached, save_cache

_RETRYABLE = (httpx.TimeoutException, httpx.TransportError)


class DartApiError(RuntimeError):
    def __init__(self, status: str, message: str):
        self.status = status
        super().__init__(f"DART {status}: {message}")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=4),
    retry=retry_if_exception_type(_RETRYABLE),
    reraise=True,
)
def _get_json(url: str, params: dict[str, str]) -> dict[str, Any]:
    with httpx.Client(timeout=settings.DART_TIMEOUT) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def fetch_financials(
    corp_code: str,
    bsns_year: int,
    *,
    reprt_code: str | None = None,
    fs_div: str | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """단일회사 전체 재무제표 원문 행 목록 반환.

    행 필드: rcept_no, sj_div, account_id, account_nm,
             thstrm_amount, frmtrm_amount, bfefrmtrm_amount, currency 등.
    데이터 없음(status 013)은 빈 리스트 — 예외가 아니라 상위의 data_status 판단 대상.
    """
    reprt_code = reprt_code or settings.DEFAULT_REPRT_CODE
    fs_div = fs_div or settings.DEFAULT_FS_DIV
    key = f"fnltt_{corp_code}_{bsns_year}_{reprt_code}_{fs_div}"

    if use_cache and (hit := load_cached(key)) is not None:
        return hit

    payload = _get_json(
        f"{settings.DART_BASE_URL}/fnlttSinglAcntAll.json",
        {
            "crtfc_key": settings.DART_API_KEY,
            "corp_code": corp_code,
            "bsns_year": str(bsns_year),
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        },
    )

    status = payload.get("status", "")
    if status == "013":
        save_cache(key, [])
        return []
    if status != "000":
        raise DartApiError(status, payload.get("message", ""))

    rows: list[dict[str, Any]] = payload["list"]
    save_cache(key, rows)
    return rows


if __name__ == "__main__":
    from .corp_code import resolve

    rows = fetch_financials(resolve("006400"), 2025)  # 삼성SDI FY2025 사업보고서
    print(f"rows={len(rows)}")
    for r in rows[:5]:
        print(r["sj_div"], r.get("account_id"), r["account_nm"], r["thstrm_amount"], r["rcept_no"])