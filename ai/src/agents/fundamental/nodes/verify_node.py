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
from ..core.decisions import record_decision
from ..core.failures import record_failure


async def verify_node(state: FundamentalAgentState) -> dict[str, Any]:
    # verify는 LLM 출력의 마지막 방어선이다. retry가 실패하면 template로 닫아 JSON 계약을 보존한다.
    risk_flags = list(state.get("risk_flags", []))
    verdict = state["verdict"]
    interpretation = state["interpretation"]
    llm_provider = state["llm_provider"]
    llm_model = state["llm_model"]
    llm_latency_ms = state["llm_latency_ms"]
    llm_verdict_label = state.get("llm_verdict_label")
    usage_records = list(state.get("llm_usage_records", [])) or [state.get("llm_usage", {})]
    llm_guard_violations: list[str] = []
    initial_provider = llm_provider
    initial_model = llm_model
    regen_count = 0
    critic_revision_used = bool(state.get("critic_revision_used"))
    llm_call_count = int(state.get("llm_call_count", 0))

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
            if not critic_revision_used and int(state.get("llm_call_count", 0)) < 4:
                # critic revise를 이미 썼거나 호출 상한에 닿으면 추가 LLM 재생성 없이 fallback으로 간다.
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
                llm_call_count += 0 if retry_result.provider == "template" else 1
                extend_unique(risk_flags, retry_result.flags)
                usage_records.append(
                    {
                        "stage": "verify_retry",
                        "prompt_tokens": retry_result.prompt_tokens,
                        "completion_tokens": retry_result.completion_tokens,
                    }
                )
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
                elif retry_result.provider != "template":
                    llm_guard_violations = retry_guard.violations
            if llm_guard_violations:
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
    usage_records.append({"stage": "planner", **state.get("planner_usage", {})})
    prompt_tokens = [item.get("prompt_tokens") for item in usage_records if item.get("prompt_tokens") is not None]
    completion_tokens = [item.get("completion_tokens") for item in usage_records if item.get("completion_tokens") is not None]
    cost_summary = {
        "llm_calls": llm_call_count or len(usage_records),
        "prompt_tokens": sum(prompt_tokens) if prompt_tokens else None,
        "completion_tokens": sum(completion_tokens) if completion_tokens else None,
        "dart_network_calls": (state.get("retrieval_summary") or {}).get("financial_network_calls"),
        "probe_calls": (state.get("retrieval_summary") or {}).get("probe_network_calls"),
    }
    verification_summary = {
        # 프론트와 HTML은 이 summary를 읽어 검증됨/한계 상태를 표시한다.
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
        "cost_summary": cost_summary,
    }
    decisions = record_decision(
        state.get("agent_decisions"),
        stage="verify",
        decision="accepted" if not llm_guard_violations else "template_fallback",
        reason="검증 가드 결과를 최종 응답에 반영했습니다.",
        provider="deterministic",
    )
    failures = list(state.get("failures", []))
    if llm_guard_violations:
        failures = record_failure(
            failures,
            failure_type="guard_rejected",
            stage="verify",
            message="LLM 출력이 deterministic guard를 통과하지 못했습니다.",
            retryable=True,
        )

    return {
        "verdict": verdict,
        "interpretation": interpretation,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "llm_latency_ms": llm_latency_ms,
        "llm_guard_violations": llm_guard_violations,
        "verification_summary": verification_summary,
        "cost_summary": cost_summary,
        "risk_flags": risk_flags,
        "confidence": confidence_from(state["ratios"], risk_flags),
        "agent_decisions": decisions,
        "failures": failures,
        "llm_usage_records": usage_records,
        "llm_call_count": llm_call_count,
    }
