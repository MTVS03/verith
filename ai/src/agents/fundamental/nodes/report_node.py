from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..core.contract import FundamentalResponse
from ..emit.html_builder import build_report_html
from ..report.formatting import attach_display_fields
from ..report.schema_builder import build_erd_payload
from ..core.state import FundamentalAgentState


def _insufficient_response(state: FundamentalAgentState) -> dict[str, Any]:
    request = state["request"]
    reason = state.get("data_status_reason", "분석 가능한 데이터가 부족합니다.")
    risk_flags = state.get("risk_flags", [])
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
    return {"meta": meta, "response": response}


def report_node(state: FundamentalAgentState) -> dict[str, Any]:
    if state.get("data_status") in {"unsupported_ticker", "empty_data"}:
        return _insufficient_response(state)

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
        "cost_summary": state.get("cost_summary", {}),
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
    return {"meta": meta, "response": response}
