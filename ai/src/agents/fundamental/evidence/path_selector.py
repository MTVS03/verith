from __future__ import annotations

from typing import Any


def select_evidence_paths(evidence_graph: dict[str, Any], metric_priority: list[str], limit: int = 8) -> list[dict[str, Any]]:
    """LLM 프롬프트에 넘길 metric -> account -> filing 경로만 추린다.

    전체 그래프를 넘기면 프롬프트가 장황해지므로 planner의 우선순위를 기준으로
    근거 경로를 제한한다. 여기서도 값이나 라벨은 새로 만들지 않는다.
    """
    nodes = {node.get("id"): node for node in evidence_graph.get("nodes", [])}
    incoming: dict[str, list[dict[str, Any]]] = {}
    outgoing: dict[str, list[dict[str, Any]]] = {}
    for edge in evidence_graph.get("edges", []):
        incoming.setdefault(edge.get("to", ""), []).append(edge)
        outgoing.setdefault(edge.get("from", ""), []).append(edge)

    metric_nodes = [node for node in evidence_graph.get("nodes", []) if node.get("type") == "metric"]
    priority = {metric: index for index, metric in enumerate(metric_priority)}
    metric_nodes.sort(key=lambda node: priority.get(node.get("metric", ""), len(priority)))

    paths: list[dict[str, Any]] = []
    for metric in metric_nodes:
        metric_id = metric.get("id", "")
        accounts: list[dict[str, Any]] = []
        filings: dict[str, dict[str, Any]] = {}
        for edge in incoming.get(metric_id, []):
            if edge.get("relation") != "calculates":
                continue
            account = nodes.get(edge.get("from"))
            if not account:
                continue
            accounts.append(
                {
                    "account_id": account.get("account_id"),
                    "account_nm": account.get("account_nm"),
                    "role": account.get("role"),
                    "fiscal_year": account.get("fiscal_year"),
                    "rcept_no": account.get("rcept_no"),
                    "source_url": account.get("source_url"),
                }
            )
            for filing_edge in incoming.get(account.get("id", ""), []):
                if filing_edge.get("relation") == "contains_account":
                    filing = nodes.get(filing_edge.get("from"))
                    if filing:
                        filings[filing.get("rcept_no", "")] = filing
        paths.append(
            {
                "metric": metric.get("metric"),
                "label": metric.get("label"),
                "display_value": metric.get("display_value"),
                "stance": metric.get("stance"),
                "accounts": accounts,
                "filings": [
                    {
                        "rcept_no": filing.get("rcept_no"),
                        "source_url": filing.get("source_url"),
                    }
                    for filing in filings.values()
                ],
            }
        )
        if len(paths) >= limit:
            break
    return paths
