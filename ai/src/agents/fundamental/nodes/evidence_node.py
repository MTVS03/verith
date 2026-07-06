from __future__ import annotations

from typing import Any

from ..evidence.graph_builder import build_analyst_plan, build_evidence_graph, build_retrieval_context
from ..core.state import FundamentalAgentState


def evidence_node(state: FundamentalAgentState) -> dict[str, Any]:
    evidence_graph = build_evidence_graph(
        state["ratios"],
        state["trend"],
        state.get("insights", {}),
        state["evidence"],
        state.get("risk_flags", []),
    )
    analyst_plan = build_analyst_plan(evidence_graph, state["score"], state["label"], state["request"].intent)
    retrieval_context = build_retrieval_context(evidence_graph, analyst_plan)
    if state.get("retrieval_summary"):
        retrieval_context["source_policy"] = state["retrieval_summary"]
    return {
        "evidence_graph": evidence_graph,
        "analyst_plan": analyst_plan,
        "retrieval_context": retrieval_context,
    }
