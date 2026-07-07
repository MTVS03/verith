"""Step 1 — DART data collection for the secondary-battery MVP scope.

For each in-scope company (see :mod:`companies`) this fetches, from the most
recent 사업보고서 (annual business report):

* **Unstructured** — the '사업의 내용' section text -> ``data/raw/<code>/business_content.txt``
  (+ ``meta.json`` for provenance). Later fed to the LLM relation extractor.
* **Structured** — 타법인출자현황 (equity investments -> OWNS_STAKE) and
  최대주주현황 (major shareholders) -> accumulated CSVs under ``data/structured/``.
  These go straight to graph edges with no LLM (the accurate "backbone").

Run:
    uv run python -m src.agents.industry.dart_collect --limit 2   # smoke test
    uv run python -m src.agents.industry.dart_collect             # all 10
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

import pandas as pd
import requests
from bs4 import BeautifulSoup
from OpenDartReader.dart_utils import USER_AGENT as _USER_AGENT

from .companies import COMPANIES, Company
from .config import RAW_DIR, STRUCTURED_DIR, get_dart_client

# Business report code; '11011' = 사업보고서 (annual). Shared by list-filter and report().
ANNUAL_REPORT_CODE = "11011"
# Polite pause between companies to stay well under DART's rate limits.
SLEEP_BETWEEN_CALLS = 0.5
# dart.fss.or.kr resets connections for non-browser User-Agents, so reuse the
# browser-like UA the OpenDartReader library itself sends for its viewer fetches.


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_business_reports(dart, stock_code: str, year: int) -> list[dict]:
    """Return 사업보고서 filings for a company, newest first.

    Scans annual/periodic disclosures (``kind='A'``) from ``year`` back a few
    years. ``final=False`` keeps original filings that a later ``[첨부정정]``
    (attachment-correction) amendment would otherwise hide — the amendment can
    lack the 사업의 내용 section, so the caller may need to fall back to the
    original filing behind it.
    """
    start = f"{year - 3}-01-01"
    listing = dart.list(stock_code, start=start, kind="A", final=False)
    if listing is None or len(listing) == 0:
        return []
    reports = listing[listing["report_nm"].str.contains("사업보고서", na=False)]
    if reports.empty:
        return []
    reports = reports.sort_values("rcept_dt", ascending=False)
    return [row.to_dict() for _, row in reports.iterrows()]


def find_business_content_url(dart, rcept_no: str) -> str | None:
    """Return the viewer URL of a filing's 사업의 내용 section, or None.

    Selects by explicit title substring ('사업의 내용') rather than fuzzy
    similarity, so an amendment lacking the section returns None instead of a
    wrong-but-similar page.
    """
    sub = dart.sub_docs(rcept_no)
    if sub is None or len(sub) == 0:
        return None
    hits = sub[sub["title"].str.contains("사업의 내용", na=False)]
    return None if hits.empty else hits.iloc[0]["url"]


def fetch_section_text(source_url: str) -> str:
    """Fetch a DART viewer page and return it as plain text."""
    resp = requests.get(source_url, headers={"User-Agent": _USER_AGENT}, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    soup = BeautifulSoup(resp.text, "lxml")
    text = soup.get_text(separator="\n")
    # Collapse the runs of blank lines the DART viewer markup produces.
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _tag_rows(df: pd.DataFrame, company: Company, year: int) -> pd.DataFrame:
    """Prefix raw DART report rows with our identity/provenance columns."""
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy()
    out.insert(0, "query_stock_code", company.stock_code)
    out.insert(1, "query_canonical", company.canonical)
    out.insert(2, "bsns_year", year)
    return out


def collect_company(dart, company: Company, year: int, force: bool) -> dict:
    """Collect text + structured tables for one company.

    Returns a result dict; raises are caught by the caller so one bad company
    doesn't abort the run. Structured DataFrames are returned for the caller to
    accumulate into the shared CSVs.
    """
    out_dir = RAW_DIR / company.stock_code
    text_path = out_dir / "business_content.txt"

    result: dict = {"company": company.canonical, "stock_code": company.stock_code}

    # --- Unstructured: 사업의 내용 -------------------------------------------
    if text_path.exists() and not force:
        result["text"] = "skipped (exists)"
    else:
        reports = list_business_reports(dart, company.stock_code, year)
        if not reports:
            raise RuntimeError("no 사업보고서 found")
        # Walk newest-first and take the first filing that actually contains a
        # 사업의 내용 section (skips attachment-only [첨부정정] amendments).
        report = source_url = None
        for candidate in reports:
            url = find_business_content_url(dart, str(candidate["rcept_no"]))
            if url:
                report, source_url = candidate, url
                break
        if not source_url:
            raise RuntimeError("no 사업의 내용 section in any 사업보고서")
        rcept_no = str(report["rcept_no"])
        text = fetch_section_text(source_url)
        out_dir.mkdir(parents=True, exist_ok=True)
        text_path.write_text(text, encoding="utf-8")
        meta = {
            "canonical": company.canonical,
            "stock_code": company.stock_code,
            "aliases": company.aliases,
            "rcept_no": rcept_no,
            "report_nm": report.get("report_nm"),
            "rcept_dt": report.get("rcept_dt"),
            "bsns_year": year,
            "source_url": source_url,
            "fetched_at": _now_iso(),
        }
        (out_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result["text"] = f"{len(text)} chars"

    # --- Structured: 타법인출자 / 최대주주 -----------------------------------
    holdings = _tag_rows(dart.report(company.stock_code, "타법인출자", year, ANNUAL_REPORT_CODE), company, year)
    shareholders = _tag_rows(dart.report(company.stock_code, "최대주주", year, ANNUAL_REPORT_CODE), company, year)
    result["holdings_rows"] = len(holdings)
    result["shareholder_rows"] = len(shareholders)

    return {"result": result, "holdings": holdings, "shareholders": shareholders}


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect DART filings for the battery MVP scope.")
    parser.add_argument("--limit", type=int, default=None, help="collect only the first N companies")
    parser.add_argument(
        "--year",
        type=int,
        default=datetime.now().year - 1,
        help="business year for structured reports (default: last year)",
    )
    parser.add_argument("--force", action="store_true", help="re-fetch text even if it already exists")
    args = parser.parse_args()

    companies = COMPANIES[: args.limit] if args.limit else COMPANIES
    dart = get_dart_client()

    STRUCTURED_DIR.mkdir(parents=True, exist_ok=True)
    all_holdings: list[pd.DataFrame] = []
    all_shareholders: list[pd.DataFrame] = []
    ok: list[str] = []
    failed: list[tuple[str, str]] = []

    for company in companies:
        print(f"[{company.stock_code}] {company.canonical} ...")
        try:
            got = collect_company(dart, company, args.year, args.force)
            if len(got["holdings"]):
                all_holdings.append(got["holdings"])
            if len(got["shareholders"]):
                all_shareholders.append(got["shareholders"])
            r = got["result"]
            print(f"    text={r['text']}, holdings={r['holdings_rows']}, shareholders={r['shareholder_rows']}")
            ok.append(company.canonical)
        except Exception as exc:  # keep going; report at the end
            print(f"    FAILED: {exc}")
            failed.append((company.canonical, str(exc)))
        time.sleep(SLEEP_BETWEEN_CALLS)

    # Flush accumulated structured tables.
    if all_holdings:
        pd.concat(all_holdings, ignore_index=True).to_csv(
            STRUCTURED_DIR / "holdings.csv", index=False, encoding="utf-8-sig"
        )
    if all_shareholders:
        pd.concat(all_shareholders, ignore_index=True).to_csv(
            STRUCTURED_DIR / "major_shareholders.csv", index=False, encoding="utf-8-sig"
        )

    print(f"\nDone. ok={len(ok)}/{len(companies)}")
    if failed:
        print("Failed:")
        for name, err in failed:
            print(f"  - {name}: {err}")


if __name__ == "__main__":
    main()
