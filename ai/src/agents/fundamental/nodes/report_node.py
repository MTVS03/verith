from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..core.contract import FundamentalResponse
from ..core.failures import record_failure
from ..core.run_history import append_history, recent_stats
from ..emit.html_builder import build_report_html
from ..report.formatting import attach_display_fields
from ..report.schema_builder import build_erd_payload
from ..core.state import FundamentalAgentState


def _insufficient_response(state: FundamentalAgentState) -> dict[str, Any]:
    # collect에서 데이터가 막혀도 상위 서비스는 동일한 FundamentalResponse JSON을 받는다.
    request = state["request"]
    reason = state.get("data_status_reason", "분석 가능한 데이터가 부족합니다.")
    risk_flags = state.get("risk_flags", [])
    failures = list(state.get("failures", []))
    if state.get("data_status") == "unsupported_ticker":
        failures = record_failure(
            failures,
            failure_type="unsupported_ticker",
            stage="collect",
            message=reason,
            retryable=False,
        )
    elif state.get("data_status") == "empty_data":
        failures = record_failure(
            failures,
            failure_type="empty_data",
            stage="collect",
            message=reason,
            retryable=True,
        )
    meta = {
        "llm_provider": "template",
        "llm_model": "rule-based",
        "llm_guard_violations": [],
        "latency_ms": 0,
        "dart_calls": state.get("dart_calls", 0),
        "fs_div": state.get("fs_div", request.fs_div),
        "reprt_code": state.get("reprt_code", ""),
        "reprt_name": state.get("reprt_name", ""),
        "report_mode": state.get("report_mode", request.report_mode),
        "period_basis": state.get("period_basis", {}),
        "fresh_dart": request.report_mode == "latest",
        "retrieval_summary": state.get("retrieval_summary", {}),
        "verification_summary": {
            "binding_passed": True,
            "consistency_passed": True,
            "guard_passed": True,
            "verdict_stable": True,
            "outcome": "insufficient_data",
            "reasons": [state.get("data_status", "insufficient_data")],
            "regen_count": 0,
        },
        "cost_summary": {"llm_calls": 0, "prompt_tokens": None, "completion_tokens": None, "dart_network_calls": 0, "probe_calls": 0},
        "corp_code": state.get("corp_code", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trace_id": request.trace_id,
        "node_trace": state.get("node_trace", []),
        "workflow": ["collect", "report"],
        "agent_decisions": state.get("agent_decisions", []),
        "failures": failures,
        "run_context": {"recent_stats": recent_stats()},
    }
    verdict = f"{reason} 현재 입력만으로 재무 상태를 판정하지 않습니다."
    response = FundamentalResponse(
        request_id=request.request_id,
        ticker=request.ticker,
        corp_name=state.get("corp_name", request.corp_name or request.ticker),
        verdict=verdict,
        verdict_label="insufficient_data",
        confidence=0.3,
        score=0,
        score_breakdown={
            "score_type": "absolute_financial_health",
            "label_display": "데이터 제한",
            "score_explanation": reason,
        },
        analyst_plan={"section_order": ["data_limits"], "section_briefs": {"data_limits": reason}},
        evidence_graph={"nodes": [], "edges": [], "sections": []},
        retrieval_context={"ordered_evidence_briefs": [reason], "metric_claims": []},
        ratios={},
        trend={"years": [], "revenue": [], "op_income": [], "roe": []},
        insights={},
        interpretation=reason,
        evidence=[],
        risk_flags=risk_flags,
        report_html=f"<section><h2>{state.get('corp_name', request.ticker)}</h2><p>{reason}</p></section>",
        meta=meta,
    )
    append_history(
        {
            "trace_id": request.trace_id,
            "request_id": request.request_id,
            "ticker": request.ticker,
            "corp_name": response.corp_name,
            "report_mode": request.report_mode,
            "score": response.score,
            "label": response.verdict_label,
            "llm_provider": "template",
            "llm_model": "rule-based",
            "latency_ms": 0,
            "llm_calls": 0,
            "failures": failures,
        }
    )
    return {"meta": meta, "response": response}


def report_node(state: FundamentalAgentState) -> dict[str, Any]:
    if state.get("data_status") in {"unsupported_ticker", "empty_data"}:
        return _insufficient_response(state)

    request = state["request"]
    ratios = state["ratios"]
    trend = state["trend"]
    evidence = state["evidence"]
    meta = {
        # meta는 운영 관측과 저장 미리보기 전용이다. 프론트 핵심 렌더링은 최상위 JSON 필드를 우선한다.
        "llm_provider": state["llm_provider"],
        "llm_model": state["llm_model"],
        "llm_guard_violations": state.get("llm_guard_violations", []),
        "latency_ms": state["llm_latency_ms"],
        "dart_calls": state["dart_calls"],
        "fs_div": state["fs_div"],
        "reprt_code": state["reprt_code"],
        "reprt_name": state["reprt_name"],
        "report_mode": state["report_mode"],
        "period_basis": state.get("period_basis", {}),
        "fresh_dart": state["request"].report_mode == "latest",
        "retrieval_summary": state.get("retrieval_summary", {}),
        "verification_summary": state.get("verification_summary", {}),
        "cost_summary": state.get("cost_summary", {}),
        "corp_code": state["corp_code"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trace_id": request.trace_id,
        "node_trace": state.get("node_trace", []),
        "workflow": ["collect", "normalize", "calculate", "evidence", "plan", "interpret", "critic", "verify", "report"],
        "agent_decisions": state.get("agent_decisions", []),
        "failures": state.get("failures", []),
        "run_context": {
            "recent_stats": recent_stats(),
            "llm_call_count": state.get("llm_call_count", 0),
            "critic_revision_used": state.get("critic_revision_used", False),
            "planner_usage": state.get("planner_usage", {}),
            "critic_usage": state.get("critic_usage", {}),
        },
        "critic_result": state.get("critic_result", {}),
    }
    erd_payload = build_erd_payload(
        request_id=request.request_id,
        trace_id=request.trace_id,
        ticker=request.ticker,
        corp_name=state["corp_name"],
        corp_code=state["corp_code"],
        bsns_year=int(state["years"][-1]),
        fs_div=state["fs_div"],
        reprt_code=state["reprt_code"],
        verdict=state["verdict"],
        confidence=state["confidence"],
        score=state["score"],
        label=state["label"],
        ratios=ratios,
        evidence=evidence,
        trend=trend,
        interpretation=state["interpretation"],
        interpretation_source=state["llm_provider"],
        risk_flags=state["risk_flags"],
        verification=state.get("verification_summary", {}),
        retrieval_summary=state.get("retrieval_summary", {}),
    )
    meta["erd_payload"] = erd_payload

    attach_display_fields(ratios, trend, evidence)
    report_html = build_report_html(
        corp_name=state["corp_name"],
        ticker=request.ticker,
        score=state["score"],
        label=state["label"],
        confidence=state["confidence"],
        ratios=ratios,
        trend=trend,
        interpretation=state["interpretation"],
        evidence=evidence,
        risk_flags=state["risk_flags"],
        insights=state.get("insights", {}),
        score_breakdown=state["score_breakdown"],
        analyst_plan=state.get("analyst_plan", {}),
        evidence_graph=state.get("evidence_graph", {}),
        meta=meta,
    )
    response = FundamentalResponse(
        request_id=request.request_id,
        ticker=request.ticker,
        corp_name=state["corp_name"],
        verdict=state["verdict"],
        verdict_label=state["label"],
        confidence=state["confidence"],
        score=state["score"],
        score_breakdown=state["score_breakdown"],
        analyst_plan=state.get("analyst_plan", {}),
        evidence_graph=state.get("evidence_graph", {}),
        retrieval_context=state.get("retrieval_context", {}),
        ratios=ratios,
        trend=trend,
        insights=state.get("insights", {}),
        interpretation=state["interpretation"],
        evidence=evidence,
        risk_flags=state["risk_flags"],
        report_html=report_html,
        meta=meta,
    )
    append_history(
        {
            "trace_id": request.trace_id,
            "request_id": request.request_id,
            "ticker": request.ticker,
            "corp_name": state["corp_name"],
            "report_mode": request.report_mode,
            "score": state["score"],
            "label": state["label"],
            "llm_provider": state["llm_provider"],
            "llm_model": state["llm_model"],
            "latency_ms": state["llm_latency_ms"],
            "llm_calls": state.get("llm_call_count", 0),
            "prompt_tokens": (state.get("cost_summary") or {}).get("prompt_tokens"),
            "completion_tokens": (state.get("cost_summary") or {}).get("completion_tokens"),
            "guard_violations": state.get("llm_guard_violations", []),
            "failures": state.get("failures", []),
        }
    )
    return {"meta": meta, "response": response}
