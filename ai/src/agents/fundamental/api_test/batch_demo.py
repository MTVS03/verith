"""10개사 전체 배치 데모 — analyze_fundamental E2E 실행 + 결과 파일 생성.

Run from the ai directory:
    python -m src.agents.fundamental.api_test.batch_demo
    python -m src.agents.fundamental.api_test.batch_demo --ticker 051910
    python -m src.agents.fundamental.api_test.batch_demo --years 4 --no-cache

출력 (api_test/out/, gitignore 대상):
    {ticker}_{corp_name}.json  — FundamentalResponse 전체 덤프
    {ticker}_{corp_name}.html  — report_html 단독 (브라우저 확인용)
    summary.md                 — 10개사 비교표
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..core.config import CORP_CODE_MAP, STOCK_NAME_MAP, settings
from ..core.contract import FundamentalRequest, FundamentalResponse
from ..emit.html_builder import build_report_html
from ..report.formatting import format_metric_value
from ..graph import analyze_fundamental
from ..ratios.scorer import display_label

OUT_DIR = Path(__file__).resolve().parent / "out"

SUMMARY_RATIOS = ("roe", "operating_margin", "debt_ratio", "current_ratio", "eps", "bps")
SUMMARY_HEADERS = ("ROE", "영업이익률", "부채비율", "유동비율", "EPS", "BPS")


def _ratio_cell(response: FundamentalResponse, key: str) -> str:
    item = response.ratios.get(key, {})
    value = item.get("value")
    unit = item.get("unit", "")
    return "-" if value is None else format_metric_value(value, unit)


async def run_one(ticker: str, years: int, use_cache: bool) -> FundamentalResponse:
    request = FundamentalRequest(
        request_id=f"batch-{uuid.uuid4().hex[:8]}",
        trace_id=f"batch-demo-{ticker}",
        ticker=ticker,
        years=years,
    )
    return await analyze_fundamental(request, use_cache=use_cache)


def write_outputs(response: FundamentalResponse) -> None:
    stem = f"{response.ticker}_{response.corp_name}"
    (OUT_DIR / f"{stem}.json").write_text(
        json.dumps(response.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT_DIR / f"{stem}_debug.html").write_text(response.report_html, encoding="utf-8")


def _peer_label(rank: int, count: int) -> str:
    if count <= 1:
        return "단일 비교"
    if rank <= max(1, round(count * 0.3)):
        return "동종군 상위권"
    if rank <= max(1, round(count * 0.7)):
        return "동종군 중위권"
    return "동종군 하위권"


def _refresh_report_html(response: FundamentalResponse) -> None:
    response.report_html = build_report_html(
        corp_name=response.corp_name,
        ticker=response.ticker,
        score=response.score,
        label=response.verdict_label,
        confidence=response.confidence,
        ratios=response.ratios,
        trend=response.trend,
        interpretation=response.interpretation,
        evidence=response.evidence,
        risk_flags=response.risk_flags,
        insights=response.insights,
        score_breakdown=response.score_breakdown,
        analyst_plan=response.analyst_plan,
        meta=response.meta,
        evidence_graph=response.evidence_graph,
        audience="debug",
    )


def apply_peer_context(results: dict[str, FundamentalResponse | Exception]) -> None:
    # peer 정보는 batch_demo 표시용 상대 위치다. 내부 verdict_label은 절대 점수 라벨을 유지한다.
    valid = [result for result in results.values() if isinstance(result, FundamentalResponse)]
    valid.sort(key=lambda item: (-item.score, item.ticker))
    count = len(valid)
    for index, response in enumerate(valid, start=1):
        percentile = 100.0 if count <= 1 else round((count - index) / (count - 1) * 100, 1)
        response.meta.update(
            {
                "peer_group": "battery_10",
                "peer_group_label": "2차전지 10개사",
                "peer_rank": index,
                "peer_count": count,
                "peer_percentile": percentile,
                "sector_relative_score": percentile,
                "peer_label": _peer_label(index, count),
            }
        )
        response.score_breakdown["peer_relative"] = {
            "group": "battery_10",
            "rank": index,
            "count": count,
            "percentile": percentile,
            "sector_relative_score": percentile,
            "label": _peer_label(index, count),
        }
        _refresh_report_html(response)


def build_summary(results: dict[str, FundamentalResponse | Exception], years: int) -> str:
    lines = [
        "# Fundamental 10개사 배치 결과",
        "",
        f"- 생성: {datetime.now(timezone.utc).isoformat()}",
        f"- 조회 연수: {years}",
        "",
        "| ticker | corp_name | score | report_label | peer_rank | peer_label | sector_score | confidence | "
        + " | ".join(SUMMARY_HEADERS)
        + " | llm | prompt_tokens | completion_tokens | dart_calls | guard_violations | risk_flags |",
        "|---|---|---|---|---|---|---|---|" + "---|" * len(SUMMARY_HEADERS) + "---|---|---|---|---|---|",
    ]
    for ticker, result in results.items():
        corp_name = STOCK_NAME_MAP.get(ticker, "?")
        if isinstance(result, Exception):
            lines.append(
                f"| {ticker} | {corp_name} | ERROR | - | - | - | - | - |"
                + " - |" * len(SUMMARY_HEADERS)
                + f" - | - | - | - | - | {type(result).__name__}: {result} |"
            )
            continue
        ratio_cells = " | ".join(_ratio_cell(result, key) for key in SUMMARY_RATIOS)
        flags = ", ".join(result.risk_flags) or "-"
        guard_violations = ", ".join(result.meta.get("llm_guard_violations") or []) or "-"
        cost_summary = result.meta.get("cost_summary") or {}
        prompt_tokens = cost_summary.get("prompt_tokens") or "-"
        completion_tokens = cost_summary.get("completion_tokens") or "-"
        dart_calls = cost_summary.get("dart_network_calls")
        dart_calls = "-" if dart_calls is None else dart_calls
        llm = result.meta.get("llm_provider", "?")
        peer_rank = result.meta.get("peer_rank", "-")
        peer_count = result.meta.get("peer_count", "-")
        peer_label = result.meta.get("peer_label", "-")
        sector_score = result.meta.get("sector_relative_score", "-")
        lines.append(
            f"| {ticker} | {result.corp_name} | {result.score} | {display_label(result.verdict_label)} "
            f"| {peer_rank}/{peer_count} | {peer_label} | {sector_score} | {result.confidence} | {ratio_cells} "
            f"| {llm} | {prompt_tokens} | {completion_tokens} | {dart_calls} | {guard_violations} | {flags} |"
        )
    lines.append("")
    return "\n".join(lines)


async def run_batch(tickers: list[str], years: int, use_cache: bool) -> dict[str, FundamentalResponse | Exception]:
    # DART 호출 제한을 고려해 순차 실행한다. 실패 기업도 summary에 남겨 배치 건강도를 볼 수 있게 한다.
    results: dict[str, FundamentalResponse | Exception] = {}
    for ticker in tickers:  # DART rate limit 고려 순차 실행
        corp_name = STOCK_NAME_MAP.get(ticker, "?")
        try:
            response = await run_one(ticker, years, use_cache)
        except Exception as exc:  # 실패 기업도 summary에 남긴다
            print(f"[FAIL] {ticker} {corp_name}: {type(exc).__name__}: {exc}")
            results[ticker] = exc
            continue
        print(
            f"[OK]   {ticker} {response.corp_name}: score={response.score} "
            f"label={response.verdict_label} confidence={response.confidence} "
            f"flags={response.risk_flags}"
        )
        results[ticker] = response
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fundamental agent for all supported tickers.")
    parser.add_argument("--ticker", default=None, help="Run a single 6-digit ticker instead of all 10")
    parser.add_argument("--years", type=int, default=4, help="Number of fiscal years to analyze. default: 4")
    parser.add_argument("--no-cache", action="store_true", help="Bypass local DART response cache")
    args = parser.parse_args()

    if not settings.DART_API_KEY:
        print("DART_API_KEY is not configured in ai/.env or environment.")
        return 2

    tickers = [args.ticker] if args.ticker else list(CORP_CODE_MAP)
    OUT_DIR.mkdir(exist_ok=True)

    results = asyncio.run(run_batch(tickers, args.years, use_cache=not args.no_cache))
    apply_peer_context(results)
    for result in results.values():
        if isinstance(result, FundamentalResponse):
            write_outputs(result)

    summary = build_summary(results, args.years)
    (OUT_DIR / "summary.md").write_text(summary, encoding="utf-8")
    print(f"\nwrote {OUT_DIR / 'summary.md'}")

    failed = sum(isinstance(result, Exception) for result in results.values())
    print(f"done: ok={len(results) - failed} fail={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
