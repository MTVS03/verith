from __future__ import annotations

from typing import Any

from ..core.decisions import record_decision
from ..core.state import FundamentalAgentState
from ..evidence.path_selector import select_evidence_paths
from ..interpret.planner import plan_analysis


async def plan_node(state: FundamentalAgentState) -> dict[str, Any]:
    # planner는 보고서의 초점과 근거 우선순위만 고른다. 숫자·점수·라벨은 이전 calculate 결과를 그대로 쓴다.
    plan, usage = await plan_analysis(
        corp_name=state["corp_name"],
        intent=state["request"].intent,
        analyst_plan=state.get("analyst_plan", {}),
        evidence_graph=state.get("evidence_graph", {}),
        risk_flags=state.get("risk_flags", []),
    )
    analyst_plan = dict(state.get("analyst_plan", {}))
    analyst_plan["agent_plan"] = plan.model_dump()
    analyst_plan["section_order"] = plan.section_order or analyst_plan.get("section_order", [])
    selected_paths = select_evidence_paths(state.get("evidence_graph", {}), plan.evidence_priority)
    retrieval_context = dict(state.get("retrieval_context", {}))
    retrieval_context["selected_paths"] = selected_paths
    retrieval_context["agent_focus_sections"] = plan.focus_sections
    retrieval_context["agent_emphasis_notes"] = plan.emphasis_notes
    decisions = record_decision(
        state.get("agent_decisions"),
        stage="planner",
        decision="llm_plan" if usage["provider"] != "template" else "fallback_plan",
        reason="분석 섹션 순서와 근거 우선순위를 결정했습니다.",
        provider=usage["provider"],
        model=usage.get("model"),
        latency_ms=usage.get("latency_ms"),
    )
    decisions = record_decision(
        decisions,
        stage="evidence_selector",
        decision="selected_paths",
        reason=f"선택된 근거 경로 {len(selected_paths)}개를 해석 프롬프트에 전달했습니다.",
    )
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    return {
        "analysis_plan": plan.model_dump(),
        "analyst_plan": analyst_plan,
        "selected_paths": selected_paths,
        "retrieval_context": retrieval_context,
        "agent_decisions": decisions,
        "llm_call_count": 1 if usage["provider"] != "template" else 0,
        "planner_usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }
