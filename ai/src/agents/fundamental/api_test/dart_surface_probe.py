"""Probe broad OpenDART surfaces for fundamental-report insight candidates.

Run from the ai directory:
    python -m src.agents.fundamental.api_test.dart_surface_probe --ticker 373220
    python -m src.agents.fundamental.api_test.dart_surface_probe --all-tickers

This is a diagnostic script only. It does not change the production pipeline.
It never prints DART_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..core.config import CORP_CODE_MAP, settings
from ..data.corp_code import resolve, resolve_name
from ..data.dart_client import fetch_financials
from ..normalize.standardize import standardize_year_rows


OUT_DIR = Path(__file__).resolve().parent / "out"


@dataclass(frozen=True)
class EndpointSpec:
    endpoint: str
    title: str
    insight: str
    priority: int = 1


ENDPOINTS = (
    EndpointSpec("stockTotqySttus", "주식의 총수 현황", "BPS/PBR 분모 후보, 자기주식/유통주식수"),
    EndpointSpec("tesstkAcqsDspsSttus", "자기주식 취득 및 처분 현황", "자기주식 변화, 유통주식수 보정"),
    EndpointSpec("alotMatter", "배당에 관한 사항", "배당성향, DPS, DART EPS 교차검증"),
    EndpointSpec("irdsSttus", "증자(감자) 현황", "주식수 급변 사유, 희석 리스크"),
    EndpointSpec("detScritsIsuAcmslt", "채무증권 발행실적", "차입/조달 구조"),
    EndpointSpec("entrprsBilScritsNrdmpBlce", "기업어음증권 미상환 잔액", "단기 자금조달 부담"),
    EndpointSpec("srtpdPsndbtNrdmpBlce", "단기사채 미상환 잔액", "단기 부채 만기 부담"),
    EndpointSpec("cprndNrdmpBlce", "회사채 미상환 잔액", "회사채 만기 구조"),
    EndpointSpec("newCaplScritsNrdmpBlce", "신종자본증권 미상환 잔액", "자본성 증권/부채성 자본"),
    EndpointSpec("cndlCaplScritsNrdmpBlce", "조건부 자본증권 미상환 잔액", "조건부 자본 리스크"),
    EndpointSpec("pssrpCptalUseDtls", "공모자금의 사용내역", "공모자금 사용 계획 대비 집행"),
    EndpointSpec("prvsrpCptalUseDtls", "사모자금의 사용내역", "사모자금 사용 계획 대비 집행"),
    EndpointSpec("accnutAdtorNmNdAdtOpinion", "회계감사인의 명칭 및 감사의견", "감사의견/계속기업/검토의견 리스크"),
    EndpointSpec("adtServcCnclsSttus", "감사용역체결현황", "감사보수/감사시간"),
    EndpointSpec("accnutAdtorNonAdtServcCnclsSttus", "비감사용역 계약체결 현황", "감사 독립성 보조 판단"),
    EndpointSpec("outcmpnyDrctrNdChangeSttus", "사외이사 및 그 변동현황", "거버넌스 안정성"),
    EndpointSpec("hyslrSttus", "최대주주 현황", "지배구조/최대주주 지분율"),
    EndpointSpec("hyslrChgSttus", "최대주주 변동현황", "지배구조 변동 리스크"),
    EndpointSpec("mrhlSttus", "소액주주 현황", "유통물량/주주분산"),
    EndpointSpec("exctvSttus", "임원 현황", "경영진 구조"),
    EndpointSpec("empSttus", "직원 현황", "인력 규모/평균급여/근속"),
    EndpointSpec("hmvAuditIndvdlBySttus", "이사감사 개인별 보수현황", "고액보수/보상구조"),
    EndpointSpec("hmvAuditAllSttus", "이사감사 전체 보수현황", "이사회 보상 규모"),
    EndpointSpec("indvdlByPay", "개인별 보수지급 금액", "상위 보수자 집중도"),
    EndpointSpec("otrCprInvstmntSttus", "타법인 출자현황", "투자자산/계열사 익스포저"),
    EndpointSpec("fnlttSinglAcnt", "단일회사 주요계정", "주요 재무계정 교차검증"),
    EndpointSpec("fnlttSinglAcntAll", "단일회사 전체 재무제표", "현재 production 원천"),
    EndpointSpec("fnlttSinglIndx", "단일회사 주요 재무지표", "DART 제공 지표와 자체 산식 비교"),
)

KEYWORDS = (
    "BPS",
    "EPS",
    "주당",
    "배당",
    "보통주",
    "우선주",
    "발행주식",
    "유통주식",
    "자기주식",
    "감사의견",
    "계속기업",
    "최대주주",
    "소액주주",
    "직원",
    "평균",
    "급여",
    "회사채",
    "미상환",
    "공모",
    "사모",
    "출자",
)


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


def _format_number(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.2f}" if abs(value) < 1_000_000 else f"{value:,.0f}"


def _get_json(endpoint: str, corp_code: str, year: int, reprt_code: str) -> dict[str, Any]:
    params = {
        "crtfc_key": settings.DART_API_KEY,
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": reprt_code,
    }
    if endpoint in ("fnlttSinglAcnt", "fnlttSinglAcntAll", "fnlttSinglIndx"):
        params["fs_div"] = settings.DEFAULT_FS_DIV

    with httpx.Client(timeout=settings.DART_TIMEOUT) as client:
        resp = client.get(f"{settings.DART_BASE_URL}/{endpoint}.json", params=params)
        resp.raise_for_status()
        return resp.json()


def _interesting_rows(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    hits = []
    for row in rows:
        text = " ".join(str(v) for v in row.values() if v is not None)
        if any(keyword in text for keyword in KEYWORDS):
            hits.append(row)
        if len(hits) >= limit:
            break
    return hits


def _stock_insights(rows: list[dict[str, Any]], equity: float | None) -> dict[str, Any]:
    common = next((row for row in rows if str(row.get("se")) in ("보통주", "보통주식", "의결권이 있는 주식")), None)
    total = next((row for row in rows if str(row.get("se")) == "합계"), None)
    source = common or total or {}
    issued = _parse_number(source.get("istc_totqy"))
    distributed = _parse_number(source.get("distb_stock_co"))
    treasury = _parse_number(source.get("tesstk_co"))
    return {
        "source_label": source.get("se"),
        "issued_shares": issued,
        "treasury_shares": treasury,
        "distributed_shares": distributed,
        "bps_by_issued_shares": round(equity / issued, 2) if equity and issued else None,
        "bps_by_distributed_shares": round(equity / distributed, 2) if equity and distributed else None,
    }


def _dividend_insights(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for row in rows:
        label = str(row.get("se") or "")
        stock = str(row.get("stock_knd") or "")
        if "주당 현금배당금" in label and ("보통" in stock or stock == "-"):
            result["dps_common"] = row
        elif "현금배당수익률" in label and ("보통" in stock or stock == "-"):
            result["dividend_yield_common"] = row
        elif "현금배당성향" in label:
            result["payout_ratio"] = row
        elif "연결" in label and "주당순이익" in label:
            result["dart_eps_row"] = row
    return result


def _first_rows(rows: list[dict[str, Any]], n: int = 3) -> list[dict[str, Any]]:
    return rows[:n]


def _derive_insights(endpoint_payloads: dict[str, Any], equity: float | None) -> dict[str, Any]:
    insights: dict[str, Any] = {}
    stock_rows = endpoint_payloads.get("stockTotqySttus", {}).get("rows") or []
    if stock_rows:
        insights["shares_and_bps"] = _stock_insights(stock_rows, equity)

    alot_rows = endpoint_payloads.get("alotMatter", {}).get("rows") or []
    if alot_rows:
        insights["dividend"] = _dividend_insights(alot_rows)

    for endpoint in ("hyslrSttus", "mrhlSttus", "accnutAdtorNmNdAdtOpinion", "empSttus", "cprndNrdmpBlce", "irdsSttus", "otrCprInvstmntSttus"):
        rows = endpoint_payloads.get(endpoint, {}).get("rows") or []
        if rows:
            insights[endpoint] = _first_rows(rows)
    return insights


def _probe_ticker(ticker: str, year: int, reprt_code: str, sample_rows: int) -> dict[str, Any]:
    corp_code = resolve(ticker)
    corp_name = resolve_name(ticker)
    financial_rows = fetch_financials(corp_code, year, reprt_code=reprt_code)
    metrics = standardize_year_rows(financial_rows, str(year))
    equity = metrics.get("equity")

    endpoint_payloads: dict[str, Any] = {}
    for spec in ENDPOINTS:
        try:
            payload = _get_json(spec.endpoint, corp_code, year, reprt_code)
            rows = payload.get("list") or []
            endpoint_payloads[spec.endpoint] = {
                "title": spec.title,
                "insight": spec.insight,
                "status": payload.get("status"),
                "message": payload.get("message"),
                "row_count": len(rows),
                "keys": sorted({key for row in rows for key in row.keys()}),
                "interesting_rows": _interesting_rows(rows, sample_rows),
                "sample_rows": rows[:sample_rows],
                "rows": rows,
            }
        except Exception as exc:
            endpoint_payloads[spec.endpoint] = {
                "title": spec.title,
                "insight": spec.insight,
                "status": "ERROR",
                "message": f"{type(exc).__name__}: {exc}",
                "row_count": 0,
                "keys": [],
                "interesting_rows": [],
                "sample_rows": [],
                "rows": [],
            }

    insights = _derive_insights(endpoint_payloads, equity.value if equity else None)
    return {
        "ticker": ticker,
        "corp_name": corp_name,
        "corp_code": corp_code,
        "year": year,
        "reprt_code": reprt_code,
        "equity": equity.value if equity else None,
        "insights": insights,
        "endpoints": endpoint_payloads,
    }


def _endpoint_matrix(results: list[dict[str, Any]]) -> list[str]:
    lines = [
        "## Endpoint Matrix",
        "",
        "| API | insight candidate | ok tickers | rows | fields |",
        "|---|---|---:|---:|---|",
    ]
    for spec in ENDPOINTS:
        ok = 0
        rows = 0
        keys: set[str] = set()
        for result in results:
            payload = result["endpoints"].get(spec.endpoint) or {}
            if payload.get("status") == "000":
                ok += 1
            rows += int(payload.get("row_count") or 0)
            keys.update(payload.get("keys") or [])
        key_preview = ", ".join(sorted(keys)[:12])
        if len(keys) > 12:
            key_preview += ", ..."
        lines.append(f"| `{spec.endpoint}` | {spec.insight} | {ok}/{len(results)} | {rows} | {key_preview} |")
    return lines


def _insight_summary(results: list[dict[str, Any]]) -> list[str]:
    lines = [
        "## Derived Insight Candidates",
        "",
        "| ticker | name | BPS issued | BPS distributed | dividend rows | holder rows | audit rows | employee rows |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        insights = result.get("insights") or {}
        shares = insights.get("shares_and_bps") or {}
        endpoints = result.get("endpoints") or {}
        lines.append(
            "| {ticker} | {name} | {bps_issued} | {bps_dist} | {dividend} | {holder} | {audit} | {employee} |".format(
                ticker=result["ticker"],
                name=result["corp_name"],
                bps_issued=_format_number(shares.get("bps_by_issued_shares")),
                bps_dist=_format_number(shares.get("bps_by_distributed_shares")),
                dividend=endpoints.get("alotMatter", {}).get("row_count", 0),
                holder=endpoints.get("hyslrSttus", {}).get("row_count", 0),
                audit=endpoints.get("accnutAdtorNmNdAdtOpinion", {}).get("row_count", 0),
                employee=endpoints.get("empSttus", {}).get("row_count", 0),
            )
        )
    return lines


def _write_markdown(results: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "# DART Surface Probe",
        "",
        "Diagnostic only. This file maps which OpenDART APIs produce useful fields for the fundamental agent.",
        "",
    ]
    lines.extend(_insight_summary(results))
    lines.append("")
    lines.extend(_endpoint_matrix(results))
    lines.extend(
        [
            "",
            "## Recommended Next Pulls",
            "",
            "- `stockTotqySttus`: use `istc_totqy`, `tesstk_co`, `distb_stock_co` for issued/outstanding-share BPS variants.",
            "- `alotMatter`: compare DART provided EPS/DPS/dividend yield with our EPS and future valuation cards.",
            "- `hyslrSttus` and `mrhlSttus`: add ownership concentration and free-float context to risk flags.",
            "- `accnutAdtorNmNdAdtOpinion`: add audit-opinion risk flags before LLM interpretation.",
            "- `empSttus`: optional operating-quality context such as headcount and average pay trends.",
            "- Debt endpoints: use only when row coverage is non-empty; otherwise keep them as optional data-limit notes.",
            "",
            "See the JSON file with the same stem for raw rows and full field names.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe broad DART APIs for fundamental insight candidates.")
    parser.add_argument("--ticker", action="append", help="6-digit supported ticker. Repeatable.")
    parser.add_argument("--all-tickers", action="store_true", help="Probe the CORP_CODE_MAP demo set (fallback tickers).")
    parser.add_argument("--year", type=int, default=2025, help="Business year. default: 2025")
    parser.add_argument("--reprt-code", default="11011", help="DART report code. default: 11011 annual report")
    parser.add_argument("--sample-rows", type=int, default=5, help="Rows to preserve in markdown-adjacent samples")
    args = parser.parse_args()

    if not settings.DART_API_KEY:
        print("DART_API_KEY is not configured in ai/.env or environment.")
        return 2

    tickers = list(CORP_CODE_MAP) if args.all_tickers else (args.ticker or ["373220"])
    results = []
    for ticker in tickers:
        result = _probe_ticker(ticker, args.year, args.reprt_code, args.sample_rows)
        results.append(result)
        ok_count = sum(1 for payload in result["endpoints"].values() if payload.get("status") == "000")
        bps = ((result.get("insights") or {}).get("shares_and_bps") or {}).get("bps_by_issued_shares")
        print(f"[OK] {ticker} {result['corp_name']}: endpoint_ok={ok_count}/{len(ENDPOINTS)} bps_issued={bps}")

    OUT_DIR.mkdir(exist_ok=True)
    stem = f"dart_surface_probe_{args.year}_{'all' if args.all_tickers else '_'.join(tickers)}"
    json_path = OUT_DIR / f"{stem}.json"
    md_path = OUT_DIR / f"{stem}.md"

    json_ready = []
    for result in results:
        slim = dict(result)
        slim["endpoints"] = {
            endpoint: {k: v for k, v in payload.items() if k != "rows"}
            for endpoint, payload in result["endpoints"].items()
        }
        json_ready.append(slim)
    json_path.write_text(json.dumps(json_ready, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(results, md_path)
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
