"""AI(fundamental) 응답 계약의 backend 미러 스키마."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class FundamentalErdPayloadMirror(_Lenient):
    fundamental_report: dict[str, Any]
    report_ratios: list[dict[str, Any]] = Field(default_factory=list)
    report_evidence: list[dict[str, Any]] = Field(default_factory=list)
    report_interpretation: dict[str, Any]
    report_verification: dict[str, Any]
    report_insights: list[dict[str, Any]] = Field(default_factory=list)
    report_filing_snippets: list[dict[str, Any]] = Field(default_factory=list)


class FundamentalMetaMirror(_Lenient):
    trace_id: str = Field(min_length=1)
    erd_payload: FundamentalErdPayloadMirror


class FundamentalAgentOutputMirror(_Lenient):
    request_id: str = Field(min_length=1)
    ticker: str = Field(pattern=r"^\d{6}$")
    corp_name: str = Field(min_length=1)
    verdict: str
    verdict_label: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    score: int = Field(ge=0, le=100)
    score_breakdown: dict[str, Any] = Field(default_factory=dict)
    ratios: dict[str, Any] = Field(default_factory=dict)
    trend: dict[str, Any] = Field(default_factory=dict)
    insights: dict[str, Any] = Field(default_factory=dict)
    interpretation: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    report_html: str
    meta: FundamentalMetaMirror
