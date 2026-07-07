"""Create stable sample payloads for backend/frontend handoff.

Run from the ai directory:
    python -m src.agents.fundamental.api_test.make_sample_payload
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from ..core.contract import FundamentalRequest
from ..graph import analyze_fundamental


SAMPLES_DIR = Path(__file__).resolve().parent / "samples"


async def build_sample(ticker: str, years: int, use_cache: bool) -> None:
    request = FundamentalRequest(
        request_id=f"sample-{uuid.uuid4().hex[:8]}",
        trace_id=f"sample-fundamental-{ticker}",
        ticker=ticker,
        years=years,
    )
    response = await analyze_fundamental(request, use_cache=use_cache)
    SAMPLES_DIR.mkdir(exist_ok=True)
    (SAMPLES_DIR / "fundamental_response_sample.json").write_text(
        json.dumps(response.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (SAMPLES_DIR / "fundamental_report_sample.html").write_text(
        response.report_html,
        encoding="utf-8",
    )
    print(f"wrote {SAMPLES_DIR / 'fundamental_response_sample.json'}")
    print(f"wrote {SAMPLES_DIR / 'fundamental_report_sample.html'}")
    print(
        f"sample ticker={response.ticker} score={response.score} "
        f"label={response.verdict_label} llm={response.meta.get('llm_provider')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Create fundamental sample response/html files.")
    parser.add_argument("--ticker", default="373220", help="default: 373220 LG Energy Solution")
    parser.add_argument("--years", type=int, default=4)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()
    asyncio.run(build_sample(args.ticker, args.years, not args.no_cache))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
