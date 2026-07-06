"""LangGraph와 evidence graph 시각화 산출물을 생성한다."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from ..core.config import STOCK_NAME_MAP
from ..core.contract import FundamentalRequest
from ..graph import analyze_fundamental
from ..nodes.workflow import build_fundamental_workflow

OUT_DIR = Path(__file__).resolve().parent / "out"


def workflow_mermaid() -> str:
    return build_fundamental_workflow().get_graph().draw_mermaid()


def evidence_graph_mermaid(evidence_graph: dict) -> str:
    nodes = evidence_graph.get("nodes") or []
    edges = evidence_graph.get("edges") or []
    labels = {
        str(node.get("id")): str(
            node.get("label")
            or node.get("account_nm")
            or node.get("rcept_no")
            or node.get("metric")
            or node.get("type")
            or node.get("id")
        )
        for node in nodes
        if node.get("id")
    }
    lines = ["graph TD"]
    for node_id, label in labels.items():
        safe_id = _safe_mermaid_id(node_id)
        lines.append(f'  {safe_id}["{_escape_mermaid_label(label)}"]')
    for edge in edges:
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        if not source or not target:
            continue
        relation = _escape_mermaid_label(str(edge.get("relation") or "relates_to"))
        lines.append(f"  {_safe_mermaid_id(source)} -- {relation} --> {_safe_mermaid_id(target)}")
    return "\n".join(lines)


def _safe_mermaid_id(value: str) -> str:
    return "n_" + "".join(ch if ch.isalnum() else "_" for ch in value)


def _escape_mermaid_label(value: str) -> str:
    return value.replace('"', "'").replace("\n", " ")


def write_mermaid_doc(path: Path, title: str, mermaid: str) -> None:
    path.write_text(f"# {title}\n\n```mermaid\n{mermaid}\n```\n", encoding="utf-8")


async def export_evidence_graph(ticker: str, years: int, use_cache: bool) -> None:
    response = await analyze_fundamental(
        FundamentalRequest(
            request_id=f"graph-export-{ticker}",
            trace_id=f"graph-export-{ticker}",
            ticker=ticker,
            corp_name=STOCK_NAME_MAP.get(ticker),
            years=years,
        ),
        use_cache=use_cache,
    )
    mermaid = evidence_graph_mermaid(response.evidence_graph)
    write_mermaid_doc(OUT_DIR / f"evidence_graph_{ticker}.md", f"Evidence Graph - {ticker}", mermaid)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fundamental agent graph 시각화 산출물을 생성한다.")
    parser.add_argument("--ticker", default="051910", help="Evidence graph 샘플을 생성할 6자리 종목코드")
    parser.add_argument("--years", type=int, default=4, help="분석 연수")
    parser.add_argument("--no-cache", action="store_true", help="DART 캐시를 우회한다")
    parser.add_argument("--skip-evidence", action="store_true", help="워크플로 그래프만 생성한다")
    args = parser.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    write_mermaid_doc(OUT_DIR / "workflow_graph.md", "Fundamental Workflow Graph", workflow_mermaid())
    if not args.skip_evidence:
        asyncio.run(export_evidence_graph(args.ticker, args.years, use_cache=not args.no_cache))
    print(f"wrote {OUT_DIR / 'workflow_graph.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
