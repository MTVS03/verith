from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..core.contract import FundamentalResponse
from ..emit.html_builder import build_report_html
from ..report.formatting import attach_display_fields
from ..report.schema_builder import build_erd_payload
from ..core.state import FundamentalAgentState


def report_node(state: FundamentalAgentState) -> dict[str, Any]:
    request = state["request"]
    ratios = state["ratios"]
    trend = state["trend"]
    evidence = state["evidence"]
    meta = {
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
        "corp_code": state["corp_code"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trace_id": request.trace_id,
        "node_trace": state.get("node_trace", []),
        "workflow": ["collect", "normalize", "calculate", "evidence", "interpret", "verify", "report"],
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
    return {"meta": meta, "response": response}
