from __future__ import annotations

from typing import Any, TypedDict

from .contract import Evidence, FundamentalRequest, FundamentalResponse


class FundamentalAgentState(TypedDict, total=False):
    request: FundamentalRequest
    use_cache: bool
    corp_code: str
    corp_name: str
    years: list[str]
    fs_div: str
    reprt_code: str
    reprt_name: str
    report_mode: str
    period_basis: dict[str, Any]
    dart_calls: int
    source_records: list[Any]
    retrieval_summary: dict[str, Any]
    risk_flags: list[str]
    yearly_metrics: dict[str, dict[str, Any]]
    share_count: Any
    insights: dict[str, Any]
    ratios: dict[str, Any]
    evidence: list[Evidence]
    consistency_notes: list[dict[str, Any]]
    evidence_graph: dict[str, Any]
    analyst_plan: dict[str, Any]
    retrieval_context: dict[str, Any]
    trend: dict[str, Any]
    score: int
    score_breakdown: dict[str, Any]
    label: str
    interpretation_result: Any
    verdict: str
    interpretation: str
    llm_verdict_label: str | None
    llm_provider: str
    llm_model: str
    llm_latency_ms: int
    llm_guard_violations: list[str]
    verification_summary: dict[str, Any]
    confidence: float
    meta: dict[str, Any]
    response: FundamentalResponse
    node_trace: list[dict[str, Any]]


def extend_unique(target: list[str], values: list[str]) -> list[str]:
    target.extend(value for value in values if value not in target)
    return target
