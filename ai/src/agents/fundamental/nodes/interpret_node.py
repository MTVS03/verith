from __future__ import annotations

from typing import Any

from ..interpret.llm_interpreter import interpret
from ..core.state import FundamentalAgentState, extend_unique


async def interpret_node(state: FundamentalAgentState) -> dict[str, Any]:
    risk_flags = list(state.get("risk_flags", []))
    result = await interpret(
        state["corp_name"],
        state["score"],
        state["label"],
        state["ratios"],
        state["trend"],
        risk_flags,
        insights=state.get("insights", {}),
        analyst_plan=state.get("analyst_plan", {}),
        retrieval_context=state.get("retrieval_context", {}),
        period_basis=state.get("period_basis", {}),
    )
    extend_unique(risk_flags, result.flags)
    return {
        "interpretation_result": result,
        "risk_flags": risk_flags,
        "verdict": result.verdict,
        "interpretation": result.interpretation,
        "llm_verdict_label": result.verdict_label,
        "llm_provider": result.provider,
        "llm_model": result.model,
        "llm_latency_ms": result.latency_ms,
        "llm_guard_violations": [],
    }
