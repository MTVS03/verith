"""DART regular-report major information clients."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..core.config import settings
from .cache import load_cached, save_cache
from .dart_client import DartApiError


_RETRYABLE = (httpx.TimeoutException, httpx.TransportError)


@dataclass(frozen=True)
class ShareCountData:
    issued_shares: float
    distributed_shares: float | None
    treasury_shares: float | None
    share_class: str
    basis: str
    rcept_no: str
    stlm_dt: str
    source_endpoint: str = "stockTotqySttus"
    source_field: str = "istc_totqy"


def _parse_number(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    text = re.sub(r"[^0-9.\-]", "", str(value))
    if text in ("", "-", ".", "-."):
        return None
    try:
        return float(text)
    except ValueError:
        return None


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


def _row_rank(row: dict[str, Any]) -> int:
    label = str(row.get("se") or "")
    if label in ("보통주", "보통주식"):
        return 0
    if label == "의결권이 있는 주식":
        return 1
    if label == "합계":
        return 2
    return 99


def _select_share_row(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], str] | tuple[None, None]:
    candidates = []
    for row in rows:
        issued = _parse_number(row.get("istc_totqy"))
        if issued is None or issued <= 0:
            continue
        rank = _row_rank(row)
        if rank >= 99:
            continue
        candidates.append((rank, row))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: item[0])
    row = candidates[0][1]
    basis = "common_issued_shares" if candidates[0][0] in (0, 1) else "total_issued_shares"
    return row, basis


def fetch_share_count(
    corp_code: str,
    bsns_year: int,
    *,
    reprt_code: str | None = None,
    use_cache: bool = True,
) -> ShareCountData | None:
    """Return issued-share data from DART stockTotqySttus.

    Primary denominator is common issued shares (`istc_totqy`). If a company only
    exposes a total row, we return that with `basis=total_issued_shares`.
    """
    reprt_code = reprt_code or settings.DEFAULT_REPRT_CODE
    key = f"stock_totqy_{corp_code}_{bsns_year}_{reprt_code}"

    if use_cache and (hit := load_cached(key)) is not None:
        return ShareCountData(**hit) if hit else None

    payload = _get_json(
        f"{settings.DART_BASE_URL}/stockTotqySttus.json",
        {
            "crtfc_key": settings.DART_API_KEY,
            "corp_code": corp_code,
            "bsns_year": str(bsns_year),
            "reprt_code": reprt_code,
        },
    )
    status = payload.get("status", "")
    if status == "013":
        save_cache(key, None)
        return None
    if status != "000":
        raise DartApiError(status, payload.get("message", ""))

    row, basis = _select_share_row(payload.get("list") or [])
    if row is None or basis is None:
        save_cache(key, None)
        return None

    issued = _parse_number(row.get("istc_totqy"))
    if issued is None or issued <= 0:
        save_cache(key, None)
        return None
    data = ShareCountData(
        issued_shares=issued,
        distributed_shares=_parse_number(row.get("distb_stock_co")),
        treasury_shares=_parse_number(row.get("tesstk_co")),
        share_class=str(row.get("se") or ""),
        basis=basis,
        rcept_no=str(row.get("rcept_no") or ""),
        stlm_dt=str(row.get("stlm_dt") or ""),
    )
    save_cache(key, data.__dict__)
    return data


def _fetch_regular_rows(
    endpoint: str,
    corp_code: str,
    bsns_year: int,
    *,
    reprt_code: str | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    reprt_code = reprt_code or settings.DEFAULT_REPRT_CODE
    key = f"{endpoint}_{corp_code}_{bsns_year}_{reprt_code}"
    if use_cache and (hit := load_cached(key)) is not None:
        return hit

    payload = _get_json(
        f"{settings.DART_BASE_URL}/{endpoint}.json",
        {
            "crtfc_key": settings.DART_API_KEY,
            "corp_code": corp_code,
            "bsns_year": str(bsns_year),
            "reprt_code": reprt_code,
        },
    )
    status = payload.get("status", "")
    if status == "013":
        save_cache(key, [])
        return []
    if status != "000":
        raise DartApiError(status, payload.get("message", ""))
    rows = payload.get("list") or []
    save_cache(key, rows)
    return rows


def _find_row(rows: list[dict[str, Any]], label_token: str, stock_token: str | None = None) -> dict[str, Any] | None:
    for row in rows:
        label = str(row.get("se") or "")
        stock = str(row.get("stock_knd") or "")
        if label_token not in label:
            continue
        if stock_token and stock_token not in stock:
            continue
        return row
    return None


def _amount_from_period(row: dict[str, Any] | None) -> float | None:
    if not row:
        return None
    return _parse_number(row.get("thstrm"))


def _dividend_insight(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dps_row = _find_row(rows, "주당 현금배당금", "보통")
    yield_row = _find_row(rows, "현금배당수익률", "보통")
    payout_row = _find_row(rows, "현금배당성향")
    eps_row = _find_row(rows, "주당순이익")
    source_row = dps_row or yield_row or payout_row or eps_row or {}
    return {
        "dps_common": _amount_from_period(dps_row),
        "dividend_yield_common": _amount_from_period(yield_row),
        "payout_ratio": _amount_from_period(payout_row),
        "dart_eps": _amount_from_period(eps_row),
        "rcept_no": str(source_row.get("rcept_no") or ""),
        "source_endpoint": "alotMatter",
    }


def _major_holder_insight(rows: list[dict[str, Any]]) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    best_ratio = -1.0
    for row in rows:
        name = str(row.get("nm") or "").strip()
        if name in {"계", "합계", "총계"}:
            continue
        ratio = _parse_number(row.get("trmend_posesn_stock_qota_rt"))
        if ratio is not None and ratio > best_ratio:
            best = row
            best_ratio = ratio
    if not best:
        return {"source_endpoint": "hyslrSttus"}
    return {
        "name": str(best.get("nm") or ""),
        "relation": str(best.get("relate") or ""),
        "shares": _parse_number(best.get("trmend_posesn_stock_co")),
        "ratio": best_ratio,
        "rcept_no": str(best.get("rcept_no") or ""),
        "source_endpoint": "hyslrSttus",
    }


def _minor_holder_insight(rows: list[dict[str, Any]]) -> dict[str, Any]:
    row = rows[0] if rows else {}
    return {
        "shareholders": _parse_number(row.get("shrholdr_co")),
        "shareholder_rate": _parse_number(row.get("shrholdr_rate")),
        "held_shares": _parse_number(row.get("hold_stock_co")),
        "held_ratio": _parse_number(row.get("hold_stock_rate")),
        "total_shares": _parse_number(row.get("stock_tot_co")),
        "rcept_no": str(row.get("rcept_no") or ""),
        "source_endpoint": "mrhlSttus",
    }


def _audit_insight(rows: list[dict[str, Any]], bsns_year: int) -> dict[str, Any]:
    row = next((item for item in rows if str(item.get("bsns_year") or "") == str(bsns_year)), None)
    row = row or (rows[0] if rows else {})
    return {
        "auditor": str(row.get("adtor") or ""),
        "opinion": str(row.get("adt_opinion") or ""),
        "emphasis": str(row.get("emphs_matter") or ""),
        "key_audit_matter": str(row.get("core_adt_matter") or ""),
        "rcept_no": str(row.get("rcept_no") or ""),
        "source_endpoint": "accnutAdtorNmNdAdtOpinion",
    }


def fetch_regular_report_insights(
    corp_code: str,
    bsns_year: int,
    *,
    reprt_code: str | None = None,
    use_cache: bool = True,
) -> tuple[dict[str, Any], int]:
    """Fetch non-financial regular-report fields useful for report context."""
    endpoints = {
        "dividend": ("alotMatter", _dividend_insight),
        "major_holder": ("hyslrSttus", _major_holder_insight),
        "minor_holder": ("mrhlSttus", _minor_holder_insight),
        "audit": ("accnutAdtorNmNdAdtOpinion", lambda rows: _audit_insight(rows, bsns_year)),
    }
    insights: dict[str, Any] = {}
    calls = 0
    for key, (endpoint, parser) in endpoints.items():
        try:
            rows = _fetch_regular_rows(
                endpoint,
                corp_code,
                bsns_year,
                reprt_code=reprt_code,
                use_cache=use_cache,
            )
            calls += 1
            insights[key] = parser(rows)
        except Exception as exc:
            insights[key] = {
                "status": "unavailable",
                "reason": f"{endpoint}: {type(exc).__name__}",
            }
    return insights, calls
