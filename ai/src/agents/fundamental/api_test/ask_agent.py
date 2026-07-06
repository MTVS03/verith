"""Ask the fundamental sub-agent a user-style question.

Run from the ai directory:
    python -m src.agents.fundamental.api_test.ask_agent --question "LG에너지솔루션 재무 분석해줘"
    python -m src.agents.fundamental.api_test.ask_agent

This is an agent-quality test harness, not a backend/frontend integration.
It stays inside the fundamental package and exercises:
question -> ticker intent -> LangGraph agent -> DART/Qwen -> analyst report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from ..core.contract import FundamentalRequest, FundamentalResponse
from ..graph import analyze_fundamental
from ..ratios.scorer import display_label

OUT_DIR = Path(__file__).resolve().parent / "out" / "ask_agent"

COMPANY_ALIASES: dict[str, tuple[str, ...]] = {
    "051910": ("051910", "LG화학", "엘지화학", "lg화학", "lg chem"),
    "373220": ("373220", "LG에너지솔루션", "엘지에너지솔루션", "엔솔", "lg에너지솔루션", "lg energy solution"),
    "006400": ("006400", "삼성SDI", "삼성에스디아이", "sdi", "samsung sdi"),
    "096770": ("096770", "SK이노베이션", "에스케이이노베이션", "sk이노베이션", "sk innovation"),
    "086520": ("086520", "에코프로", "ecopro"),
    "247540": ("247540", "에코프로비엠", "에코프로bm", "ecopro bm"),
    "003670": ("003670", "포스코퓨처엠", "포스코퓨처", "posco future m"),
    "066970": ("066970", "엘앤에프", "엘앤F", "l&f", "l and f"),
    "348370": ("348370", "엔켐", "enchem"),
    "361610": ("361610", "SK아이이테크놀로지", "SKIET", "skiet", "sk ie technology"),
}

DISPLAY_NAMES = {
    "051910": "LG화학",
    "373220": "LG에너지솔루션",
    "006400": "삼성SDI",
    "096770": "SK이노베이션",
    "086520": "에코프로",
    "247540": "에코프로비엠",
    "003670": "포스코퓨처엠",
    "066970": "엘앤에프",
    "348370": "엔켐",
    "361610": "SK아이이테크놀로지",
}


def resolve_ticker_from_question(question: str, forced_ticker: str | None = None) -> str:
    if forced_ticker:
        return forced_ticker
    normalized = question.lower().replace(" ", "")
    for ticker, aliases in COMPANY_ALIASES.items():
        if ticker in question:
            return ticker
        for alias in aliases:
            if alias.lower().replace(" ", "") in normalized:
                return ticker
    choices = ", ".join(f"{ticker} {name}" for ticker, name in DISPLAY_NAMES.items())
    raise ValueError(f"기업을 찾지 못했습니다. 질문에 종목코드나 기업명을 넣어주세요. 지원 목록: {choices}")


def resolve_years_from_question(question: str, default: int = 4) -> int:
    match = re.search(r"(\d+)\s*(?:년|개년)", question)
    if not match:
        return default
    return max(1, min(6, int(match.group(1))))


def resolve_latest_mode_from_question(question: str, forced_latest: bool = False) -> bool:
    if forced_latest:
        return True
    tokens = ("최신", "실시간", "새로", "다시 가져", "캐시 없이", "fresh")
    return any(token in question.lower() for token in tokens)


def _ratio_line(response: FundamentalResponse, key: str) -> str:
    item = response.ratios.get(key, {})
    label = item.get("label", key)
    display = item.get("display_value") or "-"
    reason = item.get("reason")
    return f"- {label}: {display}" + (f" ({reason})" if reason else "")


def _analyst_briefs(response: FundamentalResponse) -> list[str]:
    plan = response.analyst_plan or {}
    briefs = plan.get("section_briefs") or {}
    order = plan.get("section_order") or list(briefs)
    return [f"- {key}: {briefs[key]}" for key in order if key in briefs]


def _source_policy_lines(response: FundamentalResponse) -> list[str]:
    summary = response.meta.get("retrieval_summary") or {}
    if not summary:
        return ["- source policy 없음"]
    sources = summary.get("financial_sources") or []
    lines = [
        f"- policy: {summary.get('policy')}",
        f"- network calls: {summary.get('financial_network_calls')}",
        f"- cache hits: {summary.get('financial_cache_hits')}",
        f"- stale refreshes: {summary.get('financial_stale_refreshes')}",
        f"- bypassed cache: {summary.get('financial_bypassed_cache')}",
    ]
    for source in sources[:6]:
        rcepts = ", ".join(source.get("rcept_nos") or []) or "-"
        lines.append(
            f"- {source.get('bsns_year')} {source.get('reprt_code')} {source.get('fs_div')}: "
            f"{source.get('cache_status')} / rows={source.get('row_count')} / rcept={rcepts}"
        )
    return lines


def _storage_contract_lines(response: FundamentalResponse) -> list[str]:
    payload = response.meta.get("erd_payload") or {}
    report = payload.get("fundamental_report") or {}
    if not report:
        return ["- storage contract 없음"]
    return [
        f"- report_id: {report.get('id')}",
        f"- data_status: {report.get('data_status')}",
        f"- ratios: {len(payload.get('report_ratios') or [])}",
        f"- evidence rows: {len(payload.get('report_evidence') or [])}",
        f"- verification: {(payload.get('report_verification') or {}).get('outcome')}",
    ]


def _verification_lines(response: FundamentalResponse) -> list[str]:
    summary = response.meta.get("verification_summary") or {}
    if not summary:
        return ["- verification summary 없음"]
    reasons = ", ".join(summary.get("reasons") or []) or "특이 사항 없음"
    return [
        f"- outcome: {summary.get('outcome')}",
        f"- binding_passed: {summary.get('binding_passed')}",
        f"- consistency_passed: {summary.get('consistency_passed')}",
        f"- guard_passed: {summary.get('guard_passed')}",
        f"- verdict_stable: {summary.get('verdict_stable')}",
        f"- regen_count: {summary.get('regen_count')}",
        f"- provider: {summary.get('initial_provider')} -> {summary.get('final_provider')}",
        f"- reasons: {reasons}",
    ]


def render_agent_markdown(question: str, response: FundamentalResponse) -> str:
    ratios = [
        _ratio_line(response, "roe"),
        _ratio_line(response, "operating_margin"),
        _ratio_line(response, "debt_ratio"),
        _ratio_line(response, "current_ratio"),
        _ratio_line(response, "revenue_growth"),
        _ratio_line(response, "operating_income_growth"),
        _ratio_line(response, "eps"),
        _ratio_line(response, "bps"),
    ]
    flags = ", ".join(response.risk_flags) if response.risk_flags else "특이 플래그 없음"
    workflow = " -> ".join(response.meta.get("workflow", [])) or "-"
    llm = f"{response.meta.get('llm_provider')} / {response.meta.get('llm_model')}"
    peer_relative = response.score_breakdown.get("peer_relative") or {}
    peer_line = ""
    if response.meta.get("sector_relative_score") is not None:
        peer_line = f"- 동종군 백분위: {response.meta.get('sector_relative_score')}점"
    elif peer_relative.get("percentile") is not None:
        peer_line = f"- 동종군 백분위: {peer_relative.get('percentile')}점"
    payload = {
        "ticker": response.ticker,
        "corp_name": response.corp_name,
        "score": response.score,
        "label": response.verdict_label,
        "confidence": response.confidence,
        "llm": response.meta.get("llm_provider"),
        "report_mode": response.meta.get("report_mode"),
        "reprt_code": response.meta.get("reprt_code"),
        "reprt_name": response.meta.get("reprt_name"),
        "fresh_dart": response.meta.get("fresh_dart"),
        "workflow": response.meta.get("workflow", []),
        "retrieval_summary": response.meta.get("retrieval_summary", {}),
        "verification_summary": response.meta.get("verification_summary", {}),
        "erd_payload_summary": {
            "report_id": (response.meta.get("erd_payload") or {}).get("fundamental_report", {}).get("id"),
            "ratio_rows": len((response.meta.get("erd_payload") or {}).get("report_ratios") or []),
            "evidence_rows": len((response.meta.get("erd_payload") or {}).get("report_evidence") or []),
        },
    }
    return "\n".join(
        [
            f"# Fundamental Agent 질의 응답 - {response.corp_name}",
            "",
            f"- 질문: {question}",
            f"- 종목: {response.corp_name} ({response.ticker})",
            f"- 점수: {response.score} / 100",
            peer_line,
            f"- 라벨: {display_label(response.verdict_label)}",
            f"- 신뢰도: {response.confidence}",
            f"- LLM: {llm}",
            f"- DART report: {response.meta.get('reprt_name')} ({response.meta.get('reprt_code')})",
            f"- fresh_dart: {response.meta.get('fresh_dart')}",
            f"- workflow: {workflow}",
            f"- risk_flags: {flags}",
            "",
            "## Agent Verdict",
            "",
            response.verdict,
            "",
            "## Analyst Interpretation",
            "",
            response.interpretation,
            "",
            "## 핵심 지표",
            "",
            *ratios,
            "",
            "## Analyst Plan",
            "",
            *(_analyst_briefs(response) or ["- 분석 플랜 없음"]),
            "",
            "## DART Source Policy",
            "",
            *_source_policy_lines(response),
            "",
            "## Verification Gate",
            "",
            *_verification_lines(response),
            "",
            "## Storage Contract",
            "",
            *_storage_contract_lines(response),
            "",
            "## Payload Snapshot",
            "",
            "```json",
            json.dumps(payload, ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )


async def ask_once(
    question: str,
    *,
    ticker: str | None,
    years: int | None,
    use_cache: bool,
    latest: bool = False,
) -> tuple[FundamentalResponse, Path, Path]:
    resolved_ticker = resolve_ticker_from_question(question, ticker)
    resolved_years = years if years is not None else resolve_years_from_question(question)
    latest_mode = resolve_latest_mode_from_question(question, latest)
    request = FundamentalRequest(
        request_id=f"ask-{uuid.uuid4().hex[:8]}",
        trace_id=f"ask-agent-{resolved_ticker}",
        ticker=resolved_ticker,
        corp_name=DISPLAY_NAMES.get(resolved_ticker),
        years=resolved_years,
        report_mode="latest" if latest_mode else "annual",
    )
    response = await analyze_fundamental(request, use_cache=False if latest_mode else use_cache)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"{stamp}_{response.ticker}"
    md_path = OUT_DIR / f"{stem}.md"
    html_path = OUT_DIR / f"{stem}.html"
    md_path.write_text(render_agent_markdown(question, response), encoding="utf-8")
    html_path.write_text(response.report_html, encoding="utf-8")
    return response, md_path, html_path


async def interactive_loop(args: argparse.Namespace) -> int:
    print("Fundamental sub-agent 대화형 테스트입니다. 종료하려면 exit 입력.")
    print("예: LG에너지솔루션 최근 4개년 재무 리포트 만들어줘")
    while True:
        question = input("\n질문> ").strip()
        if question.lower() in {"exit", "quit", "q"}:
            return 0
        if not question:
            continue
        try:
            response, md_path, html_path = await ask_once(
                question,
                ticker=args.ticker,
                years=args.years,
                use_cache=not args.no_cache,
                latest=args.latest,
            )
        except Exception as exc:
            print(f"[ERROR] {type(exc).__name__}: {exc}")
            continue
        print_response_summary(response, md_path, html_path)


def print_response_summary(response: FundamentalResponse, md_path: Path, html_path: Path) -> None:
    print("\n=== Fundamental Agent Report ===")
    print(f"{response.corp_name} ({response.ticker})")
    print(f"score={response.score} label={response.verdict_label} confidence={response.confidence}")
    if response.meta.get("sector_relative_score") is not None:
        print(f"sector_relative_score={response.meta.get('sector_relative_score')}")
    print(f"llm={response.meta.get('llm_provider')} workflow={' -> '.join(response.meta.get('workflow', []))}")
    print(
        f"dart_report={response.meta.get('reprt_name')}({response.meta.get('reprt_code')}) "
        f"mode={response.meta.get('report_mode')} fresh={response.meta.get('fresh_dart')}"
    )
    print(f"\n[Verdict]\n{response.verdict}")
    print(f"\n[Interpretation]\n{response.interpretation}")
    print(f"\nSaved markdown: {md_path}")
    print(f"Saved html:     {html_path}")
    print("VS Code에서 파일을 열어 보세요. legacy CMD type/more는 한글이 깨질 수 있습니다.")


def _clean_question_text(value: str | None) -> str:
    return (value or "").strip().strip('"')


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask the fundamental sub-agent a natural-language question.")
    parser.add_argument("--question", "-q", default=None, help="User-style Korean question")
    parser.add_argument("--ticker", default=None, help="Optional 6-digit ticker override")
    parser.add_argument("--years", type=int, default=None, help="Optional analysis years, 1-6")
    parser.add_argument("--no-cache", action="store_true", help="Bypass local DART cache")
    parser.add_argument("--latest", action="store_true", help="Discover the newest available DART filing and bypass cache")
    parser.add_argument("question_parts", nargs="*", help="Question words, useful when CMD quoting breaks")
    args, unknown = parser.parse_known_args()

    trailing_question = _clean_question_text(" ".join([*args.question_parts, *unknown]))
    if args.question and trailing_question:
        args.question = f"{_clean_question_text(args.question)} {trailing_question}".strip()
    elif trailing_question:
        args.question = trailing_question

    if args.question:
        response, md_path, html_path = asyncio.run(
            ask_once(
                args.question,
                ticker=args.ticker,
                years=args.years,
                use_cache=not args.no_cache,
                latest=args.latest,
            )
        )
        print_response_summary(response, md_path, html_path)
        return 0
    return asyncio.run(interactive_loop(args))


if __name__ == "__main__":
    raise SystemExit(main())
