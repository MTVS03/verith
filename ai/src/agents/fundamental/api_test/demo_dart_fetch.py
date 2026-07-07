"""Small DART fetch demo for the fundamental agent.

Run from the ai directory:
    python -m src.agents.fundamental.api_test.demo_dart_fetch --ticker 006400 --year 2025

This prints a compact shape preview only. It never prints DART_API_KEY.
"""

from __future__ import annotations

import argparse
from collections import Counter

from ..core.config import settings
from ..data.corp_code import resolve, resolve_name
from ..data.dart_client import fetch_financials
from ..normalize.standardize import standardize_year_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch DART fnlttSinglAcntAll sample rows.")
    parser.add_argument("--ticker", default="006400", help="6-digit supported ticker. default: 006400 삼성SDI")
    parser.add_argument("--year", type=int, default=2025, help="Business year. default: 2025")
    parser.add_argument("--fs-div", default="CFS", choices=["CFS", "OFS"], help="Financial statement division")
    parser.add_argument("--limit", type=int, default=12, help="Number of raw rows to preview")
    parser.add_argument("--statement", default=None, help="Optional statement filter, e.g. BS, CIS, CF, SCE")
    parser.add_argument("--no-cache", action="store_true", help="Bypass local DART response cache")
    args = parser.parse_args()

    if not settings.DART_API_KEY:
        print("DART_API_KEY is not configured in ai/.env or environment.")
        return 2

    corp_code = resolve(args.ticker)
    corp_name = resolve_name(args.ticker)
    rows = fetch_financials(
        corp_code,
        args.year,
        fs_div=args.fs_div,
        use_cache=not args.no_cache,
    )

    print(f"ticker={args.ticker} corp_name={corp_name} corp_code={corp_code} year={args.year} fs_div={args.fs_div}")
    print(f"raw_rows={len(rows)}")
    print(f"statement_counts={dict(Counter(row.get('sj_div', 'UNKNOWN') for row in rows))}")
    print()
    print("raw preview:")
    preview_rows = [row for row in rows if not args.statement or row.get("sj_div") == args.statement]
    for row in preview_rows[: args.limit]:
        print(
            {
                "rcept_no": row.get("rcept_no"),
                "sj_div": row.get("sj_div"),
                "account_id": row.get("account_id"),
                "account_nm": row.get("account_nm"),
                "thstrm_amount": row.get("thstrm_amount"),
                "frmtrm_amount": row.get("frmtrm_amount"),
                "currency": row.get("currency"),
            }
        )

    standardized = standardize_year_rows(rows, str(args.year))
    print()
    print("standardized metrics:")
    for key, value in standardized.items():
        print(
            {
                "metric": key,
                "value": value.value,
                "fiscal_year": value.fiscal_year,
                "rcept_no": value.rcept_no,
                "account_id": value.account_id,
                "account_nm": value.account_nm,
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
