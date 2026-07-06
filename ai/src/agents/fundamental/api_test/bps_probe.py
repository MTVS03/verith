"""Probe DART endpoints for BPS-related inputs.

Run from the ai directory:
    python -m src.agents.fundamental.api_test.bps_probe
    python -m src.agents.fundamental.api_test.bps_probe --ticker 373220 --year 2025

This is a diagnostic script only. It does not change the fundamental pipeline.
It never prints DART_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import httpx

from ..core.config import CORP_CODE_MAP, settings
from ..data.corp_code import resolve, resolve_name
from ..data.dart_client import fetch_financials
from ..normalize.standardize import standardize_year_rows


OUT_DIR = Path(__file__).resolve().parent / "out"
BPS_KEYWORDS = (
    "BPS",
    "bps",
    "주당순자산",
    "순자산",
    "자본총계",
    "지배기업",
    "보통주",
    "발행",
    "주식수",
    "총수",
    "자기주식",
    "share",
    "stock",
)

ENDPOINTS = (
    ("stockTotqySttus", "주식의 총수 현황"),
    ("tesstkAcqsDspsSttus", "자기주식 취득 및 처분 현황"),
    ("alotMatter", "배당에 관한 사항"),
)


def _parse_number(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    text = str(value)
    text = re.sub(r"[^0-9.\-]", "", text)
    if text in ("", "-", ".", "-."):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _get_json(endpoint: str, corp_code: str, year: int, reprt_code: str) -> dict[str, Any]:
    with httpx.Client(timeout=settings.DART_TIMEOUT) as client:
        resp = client.get(
            f"{settings.DART_BASE_URL}/{endpoint}.json",
            params={
                "crtfc_key": settings.DART_API_KEY,
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": reprt_code,
            },
        )
        resp.raise_for_status()
        return resp.json()


def _interesting_row(row: dict[str, Any]) -> bool:
    text = " ".join(str(v) for v in row.values() if v is not None)
    return any(keyword in text for keyword in BPS_KEYWORDS)


def _share_candidates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return diagnostic share-count candidates.

    Do not use `isu_stock_totqy` as BPS denominator. In this DART endpoint it can
    represent authorized shares, not currently issued/outstanding shares.
    """
    candidates: dict[str, Any] = {}
    for row in rows:
        label = str(row.get("se") or "")
        if label not in ("보통주", "보통주식", "의결권이 있는 주식", "합계"):
            continue
        row_key = "common" if label in ("보통주", "보통주식", "의결권이 있는 주식") else "total"
        for field in ("istc_totqy", "now_to_isu_stock_totqy"):
            shares = _parse_number(row.get(field))
            if shares and shares > 0:
                candidates[f"{row_key}_{field}"] = {
                    "source_field": field,
                    "shares": shares,
                    "row_label": label,
                    "row": row,
                }
    return candidates


def _pick_share_candidate(candidates: dict[str, Any]) -> dict[str, Any] | None:
    for key in (
        "common_istc_totqy",
        "common_now_to_isu_stock_totqy",
        "total_istc_totqy",
        "total_now_to_isu_stock_totqy",
    ):
        if key in candidates:
            candidate = dict(candidates[key])
            candidate["candidate_key"] = key
            return candidate
    return None


def _probe_one(ticker: str, year: int, reprt_code: str, use_cache: bool) -> dict[str, Any]:
    corp_code = resolve(ticker)
    corp_name = resolve_name(ticker)
    financial_rows = fetch_financials(corp_code, year, reprt_code=reprt_code, use_cache=use_cache)
    metrics = standardize_year_rows(financial_rows, str(year))
    equity = metrics.get("equity")

    financial_matches = [
        row
        for row in financial_rows
        if _interesting_row(
            {
                "sj_div": row.get("sj_div"),
                "account_id": row.get("account_id"),
                "account_nm": row.get("account_nm"),
                "thstrm_amount": row.get("thstrm_amount"),
            }
        )
    ]

    endpoint_results: dict[str, Any] = {}
    stock_rows: list[dict[str, Any]] = []
    for endpoint, description in ENDPOINTS:
        try:
            payload = _get_json(endpoint, corp_code, year, reprt_code)
        except Exception as exc:  # diagnostic script: keep going across endpoints
            endpoint_results[endpoint] = {
                "description": description,
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
            }
            continue

        rows = payload.get("list") or []
        if endpoint == "stockTotqySttus":
            stock_rows = rows
        endpoint_results[endpoint] = {
            "description": description,
            "ok": payload.get("status") == "000",
            "status": payload.get("status"),
            "message": payload.get("message"),
            "row_count": len(rows),
            "keys": sorted({key for row in rows for key in row.keys()}),
            "interesting_rows": [row for row in rows if _interesting_row(row)][:12],
            "sample_rows": rows[:5],
        }

    share_candidates = _share_candidates(stock_rows)
    share_candidate = _pick_share_candidate(share_candidates)
    candidate_bps = None
    if equity and share_candidate:
        candidate_bps = round(equity.value / share_candidate["shares"], 2)

    return {
        "ticker": ticker,
        "corp_name": corp_name,
        "corp_code": corp_code,
        "year": year,
        "reprt_code": reprt_code,
        "equity": {
            "value": equity.value,
            "account_id": equity.account_id,
            "account_nm": equity.account_nm,
            "rcept_no": equity.rcept_no,
        }
        if equity
        else None,
        "share_candidate": share_candidate,
        "share_candidates": share_candidates,
        "candidate_bps_equity_per_share": candidate_bps,
        "financial_statement_keyword_matches": financial_matches[:30],
        "endpoints": endpoint_results,
    }


def _md_table(results: list[dict[str, Any]]) -> str:
    lines = [
        "# BPS Data Probe",
        "",
        "Diagnostic only. `candidate_bps_equity_per_share` is not yet an official report metric.",
        "",
        "| ticker | name | equity | share candidate | candidate BPS | endpoint status |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for item in results:
        equity = item.get("equity") or {}
        share_candidate = item.get("share_candidate") or {}
        statuses = []
        for endpoint, data in item.get("endpoints", {}).items():
            statuses.append(f"{endpoint}:{data.get('status') or data.get('error')}")
        lines.append(
            "| {ticker} | {name} | {equity} | {shares} | {bps} | {statuses} |".format(
                ticker=item["ticker"],
                name=item["corp_name"],
                equity=f"{equity.get('value'):,.0f}" if equity.get("value") is not None else "n/a",
                shares=f"{share_candidate.get('shares'):,.0f}"
                if share_candidate.get("shares") is not None
                else "n/a",
                bps=f"{item['candidate_bps_equity_per_share']:,.2f}"
                if item.get("candidate_bps_equity_per_share") is not None
                else "n/a",
                statuses=", ".join(statuses),
            )
        )
    lines.extend(
        [
            "",
            "## How to read",
            "",
            "- `stockTotqySttus` is the main candidate for share count.",
            "- `tesstkAcqsDspsSttus` may help identify treasury-share limits, but it is not enough by itself.",
            "- `alotMatter` may contain dividend/share fields, but BPS should not be derived from dividend rows alone.",
            "- Use the JSON file next to this markdown to inspect raw rows before changing the production metric.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe DART APIs for BPS-related data.")
    parser.add_argument("--ticker", action="append", help="6-digit supported ticker. Repeatable.")
    parser.add_argument("--year", type=int, default=2025, help="Business year. default: 2025")
    parser.add_argument("--reprt-code", default="11011", help="DART report code. default: 11011 annual report")
    parser.add_argument("--no-cache", action="store_true", help="Bypass local financial statement cache")
    args = parser.parse_args()

    if not settings.DART_API_KEY:
        print("DART_API_KEY is not configured in ai/.env or environment.")
        return 2

    tickers = args.ticker or list(CORP_CODE_MAP)
    results = []
    for ticker in tickers:
        try:
            result = _probe_one(ticker, args.year, args.reprt_code, use_cache=not args.no_cache)
            results.append(result)
            print(
                "[OK] {ticker} {name}: shares={shares} candidate_bps={bps}".format(
                    ticker=ticker,
                    name=result["corp_name"],
                    shares=(result.get("share_candidate") or {}).get("shares"),
                    bps=result.get("candidate_bps_equity_per_share"),
                )
            )
        except Exception as exc:
            print(f"[FAIL] {ticker}: {type(exc).__name__}: {exc}")
            results.append({"ticker": ticker, "error": type(exc).__name__, "message": str(exc)})

    OUT_DIR.mkdir(exist_ok=True)
    json_path = OUT_DIR / f"bps_probe_{args.year}.json"
    md_path = OUT_DIR / f"bps_probe_{args.year}.md"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_md_table(results), encoding="utf-8")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
