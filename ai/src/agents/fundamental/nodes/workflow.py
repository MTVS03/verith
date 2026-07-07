from __future__ import annotations

from langgraph.graph import END, StateGraph

from .calc_node import calc_node
from .collect_node import collect_node
from .evidence_node import evidence_node
from .interpret_node import interpret_node
from .normalize_node import normalize_node
from .plan_node import plan_node
from .critic_node import critic_node
from .report_node import report_node
from ..core.observability import traced_node
from ..core.state import FundamentalAgentState
from .verify_node import verify_node


def build_fundamental_workflow():
    # 노드 순서는 계약이다. collect 실패만 report로 우회하고, 정상 데이터는 검증까지 단방향으로 흐른다.
    workflow = StateGraph(FundamentalAgentState)
    workflow.add_node("collect", traced_node("collect", collect_node))
    workflow.add_node("normalize", traced_node("normalize", normalize_node))
    workflow.add_node("calculate", traced_node("calculate", calc_node))
    workflow.add_node("evidence", traced_node("evidence", evidence_node))
    workflow.add_node("plan", traced_node("plan", plan_node))
    workflow.add_node("interpret", traced_node("interpret", interpret_node))
    workflow.add_node("critic", traced_node("critic", critic_node))
    workflow.add_node("verify", traced_node("verify", verify_node))
    workflow.add_node("report", traced_node("report", report_node))

    workflow.set_entry_point("collect")
    workflow.add_conditional_edges(
        "collect",
        # 데이터가 없을 때도 FundamentalResponse JSON을 반환해야 하므로 report 노드에서 insufficient 응답을 만든다.
        lambda state: "report" if state.get("data_status") in {"unsupported_ticker", "empty_data"} else "normalize",
        {"report": "report", "normalize": "normalize"},
    )
    workflow.add_edge("normalize", "calculate")
    workflow.add_edge("calculate", "evidence")
    workflow.add_edge("evidence", "plan")
    workflow.add_edge("plan", "interpret")
    workflow.add_edge("interpret", "critic")
    workflow.add_edge("critic", "verify")
    workflow.add_edge("verify", "report")
    workflow.add_edge("report", END)
    return workflow.compile()
