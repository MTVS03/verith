from __future__ import annotations

from langgraph.graph import END, StateGraph

from .calc_node import calc_node
from .collect_node import collect_node
from .evidence_node import evidence_node
from .interpret_node import interpret_node
from .normalize_node import normalize_node
from .report_node import report_node
from ..core.observability import traced_node
from ..core.state import FundamentalAgentState
from .verify_node import verify_node


def build_fundamental_workflow():
    workflow = StateGraph(FundamentalAgentState)
    workflow.add_node("collect", traced_node("collect", collect_node))
    workflow.add_node("normalize", traced_node("normalize", normalize_node))
    workflow.add_node("calculate", traced_node("calculate", calc_node))
    workflow.add_node("evidence", traced_node("evidence", evidence_node))
    workflow.add_node("interpret", traced_node("interpret", interpret_node))
    workflow.add_node("verify", traced_node("verify", verify_node))
    workflow.add_node("report", traced_node("report", report_node))

    workflow.set_entry_point("collect")
    workflow.add_conditional_edges(
        "collect",
        lambda state: "report" if state.get("data_status") in {"unsupported_ticker", "empty_data"} else "normalize",
        {"report": "report", "normalize": "normalize"},
    )
    workflow.add_edge("normalize", "calculate")
    workflow.add_edge("calculate", "evidence")
    workflow.add_edge("evidence", "interpret")
    workflow.add_edge("interpret", "verify")
    workflow.add_edge("verify", "report")
    workflow.add_edge("report", END)
    return workflow.compile()
