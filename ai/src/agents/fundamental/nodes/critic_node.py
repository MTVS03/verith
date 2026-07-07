from __future__ import annotations

from typing import Any

from ..core.decisions import record_decision
from ..core.failures import record_failure
from ..core.state import FundamentalAgentState, extend_unique
from ..interpret.critic import build_revise_prompt, critic_review
from ..interpret.llm_interpreter import interpret


async def critic_node(state: FundamentalAgentState) -> dict[str, Any]:
    # critic은 최대 호출 상한 안에서 한 번만 revise를 유도한다. template 해석은 이미 결정론적이라 생략한다.
    decisions = list(state.get("agent_decisions", []))
    failures = list(state.get("failures", []))
    usage_records = list(state.get("llm_usage_records", []))
    call_count = int(state.get("llm_call_count", 0)) + (0 if state.get("llm_provider") == "template" else 1)

    if state.get("llm_provider") == "template":
        decisions = record_decision(
            decisions,
            stage="critic",
            decision="skip",
            reason="템플릿 해석은 결정론적 생성물이므로 LLM critic을 생략했습니다.",
            provider="template",
        )
        return {"agent_decisions": decisions, "failures": failures, "llm_call_count": call_count, "critic_result": {"decision": "skip"}}

    critic = await critic_review(state)
    if critic.output is None:
        failures = record_failure(
            failures,
            failure_type="critic_skipped",
            stage="critic",
            message="critic structured output 검증에 실패해 검토를 생략했습니다.",
            retryable=True,
        )
        decisions = record_decision(
            decisions,
            stage="critic",
            decision="skip",
            reason="critic structured output을 확보하지 못했습니다.",
            provider=critic.provider,
            model=critic.model,
        )
        return {"agent_decisions": decisions, "failures": failures, "llm_call_count": call_count, "critic_result": {"decision": "skip"}}

    call_count += 1
    usage_records.append({"stage": "critic", "prompt_tokens": critic.prompt_tokens, "completion_tokens": critic.completion_tokens})
    decisions = record_decision(
        decisions,
        stage="critic",
        decision=critic.output.decision,
        reason="; ".join(critic.output.reasons) or "critic 검토를 통과했습니다.",
        provider=critic.provider,
        model=critic.model,
        latency_ms=critic.latency_ms,
    )
    result_payload: dict[str, Any] = {
        "decision": critic.output.decision,
        "reasons": critic.output.reasons,
        "revision_guidance": critic.output.revision_guidance,
        "provider": critic.provider,
        "model": critic.model,
    }
    if critic.output.decision != "revise" or call_count >= 4:
        return {
            "agent_decisions": decisions,
            "failures": failures,
            "llm_call_count": call_count,
            "critic_result": result_payload,
            "critic_usage": {"prompt_tokens": critic.prompt_tokens, "completion_tokens": critic.completion_tokens},
            "llm_usage_records": usage_records,
        }

    # revise는 critic guidance를 반영하는 마지막 LLM 수정 기회다. 이후 verify가 최종 가드를 담당한다.
    risk_flags = list(state.get("risk_flags", []))
    revise_prompt = build_revise_prompt(state["interpretation_result"].prompt, critic.output)
    revised = await interpret(
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
        prompt_override=revise_prompt,
    )
    call_count += 0 if revised.provider == "template" else 1
    extend_unique(risk_flags, revised.flags)
    usage_records.append({"stage": "revise", "prompt_tokens": revised.prompt_tokens, "completion_tokens": revised.completion_tokens})
    result_payload["revised"] = revised.provider != "template"
    return {
        "interpretation_result": revised,
        "risk_flags": risk_flags,
        "verdict": revised.verdict,
        "interpretation": revised.interpretation,
        "llm_verdict_label": revised.verdict_label,
        "llm_provider": revised.provider,
        "llm_model": revised.model,
        "llm_latency_ms": int(state.get("llm_latency_ms", 0)) + revised.latency_ms + critic.latency_ms,
        "llm_usage": {
            "prompt_tokens": sum(item["prompt_tokens"] for item in usage_records if item.get("prompt_tokens") is not None) or None,
            "completion_tokens": sum(item["completion_tokens"] for item in usage_records if item.get("completion_tokens") is not None) or None,
        },
        "llm_usage_records": usage_records,
        "agent_decisions": decisions,
        "failures": failures,
        "llm_call_count": call_count,
        "critic_revision_used": True,
        "critic_result": result_payload,
    }
