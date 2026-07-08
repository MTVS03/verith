from __future__ import annotations

from typing import Any, TypedDict

from .contract import Evidence, FundamentalRequest, FundamentalResponse


class FundamentalAgentState(TypedDict, total=False):
    """LangGraph 노드가 공유하는 상태 계약.

    숫자·점수·라벨은 calculate/verify/report 경로에서만 신뢰하고,
    planner/critic은 정성적 계획과 검토 결과만 이 상태에 더한다.
    """

    request: FundamentalRequest
    use_cache: bool
    corp_code: str
    corp_name: str
    corp_code_resolution: dict[str, Any]
    input_interpretation: dict[str, Any]
    years: list[str]
    fs_div: str
    reprt_code: str
    reprt_name: str
    report_mode: str
    period_basis: dict[str, Any]
    dart_calls: int
    source_records: list[Any]
    retrieval_summary: dict[str, Any]
    data_status: str
    data_status_reason: str
    risk_flags: list[str]
    yearly_metrics: dict[str, dict[str, Any]]
    share_count: Any
    insights: dict[str, Any]
    ratios: dict[str, Any]
    evidence: list[Evidence]
    consistency_notes: list[dict[str, Any]]
    evidence_graph: dict[str, Any]
    analysis_plan: dict[str, Any]
    analyst_plan: dict[str, Any]
    selected_paths: list[dict[str, Any]]
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
    llm_usage: dict[str, int | None]
    llm_usage_records: list[dict[str, Any]]
    llm_guard_violations: list[str]
    verification_summary: dict[str, Any]
    cost_summary: dict[str, Any]
    confidence: float
    agent_decisions: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    run_context: dict[str, Any]
    llm_call_count: int
    planner_usage: dict[str, int | None]
    critic_usage: dict[str, int | None]
    critic_result: dict[str, Any]
    critic_revision_used: bool
    meta: dict[str, Any]
    response: FundamentalResponse
    node_trace: list[dict[str, Any]]


def extend_unique(target: list[str], values: list[str]) -> list[str]:
    target.extend(value for value in values if value not in target)
    return target
