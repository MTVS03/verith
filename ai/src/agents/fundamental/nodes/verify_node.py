from __future__ import annotations

from typing import Any

from ..interpret.fallback_template import build_fallback_interpretation
from ..interpret.llm_interpreter import interpret
from ..interpret.prompts import build_retry_prompt
from ..ratios.scorer import confidence_from
from ..verify.binding import EVIDENCE_UNBOUND_FLAG
from ..verify.consistency import is_consistency_flag
from ..verify.stability import assess_verdict_stability
from ..verify.verdict_guard import guard_llm_output
from ..core.state import FundamentalAgentState, extend_unique


async def verify_node(state: FundamentalAgentState) -> dict[str, Any]:
    risk_flags = list(state.get("risk_flags", []))
    verdict = state["verdict"]
    interpretation = state["interpretation"]
    llm_provider = state["llm_provider"]
    llm_model = state["llm_model"]
    llm_latency_ms = state["llm_latency_ms"]
    llm_verdict_label = state.get("llm_verdict_label")
    llm_guard_violations: list[str] = []
    initial_provider = llm_provider
    initial_model = llm_model
    regen_count = 0

    if llm_provider != "template":
        guard = guard_llm_output(
            verdict,
            interpretation,
            state["ratios"],
            state["evidence"],
            score=state["score"],
            trend=state["trend"],
            insights=state.get("insights", {}),
        )
        if not guard.ok:
            llm_guard_violations = guard.violations
            retry_prompt = build_retry_prompt(state["interpretation_result"].prompt, guard.violations)
            regen_count += 1
            retry_result = await interpret(
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
                prompt_override=retry_prompt,
            )
            extend_unique(risk_flags, retry_result.flags)
            retry_guard = guard_llm_output(
                retry_result.verdict,
                retry_result.interpretation,
                state["ratios"],
                state["evidence"],
                score=state["score"],
                trend=state["trend"],
                insights=state.get("insights", {}),
            )
            if retry_result.provider != "template" and retry_guard.ok:
                verdict = retry_result.verdict
                interpretation = retry_result.interpretation
                llm_provider = retry_result.provider
                llm_model = retry_result.model
                llm_latency_ms += retry_result.latency_ms
                llm_verdict_label = retry_result.verdict_label
                llm_guard_violations = []
            else:
                if retry_result.provider != "template":
                    llm_guard_violations = retry_guard.violations
                verdict, interpretation = build_fallback_interpretation(
                    state["corp_name"],
                    state["score"],
                    state["label"],
                    state["ratios"],
                    risk_flags,
                )
                llm_provider = "template"
                llm_model = "rule-based"
                llm_verdict_label = state["label"]
                extend_unique(risk_flags, ["VERIFY_LLM_OUTPUT_REJECTED", "LLM_FALLBACK_TEMPLATE"])

    stability = assess_verdict_stability(verdict, state["label"], llm_verdict_label)
    if not stability.verdict_stable:
        extend_unique(risk_flags, ["VERDICT_STABILITY_GUARDED"])
    verification_summary = {
        "binding_passed": EVIDENCE_UNBOUND_FLAG not in risk_flags,
        "consistency_passed": not any(is_consistency_flag(flag) for flag in risk_flags),
        "guard_passed": not llm_guard_violations,
        "verdict_stable": stability.verdict_stable,
        "outcome": stability.outcome,
        "reasons": stability.reasons,
        "consistency_notes": state.get("consistency_notes", []),
        "regen_count": regen_count,
        "initial_provider": initial_provider,
        "initial_model": initial_model,
        "final_provider": llm_provider,
        "final_model": llm_model,
    }

    return {
        "verdict": verdict,
        "interpretation": interpretation,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "llm_latency_ms": llm_latency_ms,
        "llm_guard_violations": llm_guard_violations,
        "verification_summary": verification_summary,
        "risk_flags": risk_flags,
        "confidence": confidence_from(state["ratios"], risk_flags),
    }
