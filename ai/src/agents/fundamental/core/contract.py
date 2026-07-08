import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


_TICKER_RE = re.compile(r"\d{6}")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FundamentalAgentInput(_StrictModel):
    request_id: str
    trace_id: str
    ticker: str
    query: str

    @field_validator("ticker")
    @classmethod
    def ticker_must_be_six_digits(cls, value: str) -> str:
        if not _TICKER_RE.fullmatch(value):
            raise ValueError("ticker must be exactly 6 digits")
        return value

    @field_validator("request_id", "trace_id", "query")
    @classmethod
    def value_must_not_be_blank(cls, value: str, info) -> str:
        if not value or not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value


class FundamentalRequest(BaseModel):
    request_id: str
    trace_id: str
    ticker: str
    corp_name: str | None = None
    intent: Literal["fundamental_health", "profitability", "stability", "growth", "valuation"] = "fundamental_health"
    fs_div: Literal["CFS", "OFS"] = "CFS"
    report_mode: Literal["annual", "latest"] = "annual"
    years: int = Field(default=4, ge=1, le=6)

    @field_validator("ticker")
    @classmethod
    def ticker_must_be_six_digits(cls, value: str) -> str:
        if len(value) != 6 or not value.isdigit():
            raise ValueError("ticker must be a 6-digit stock code")
        return value


class EvidenceAccount(BaseModel):
    account_id: str
    account_nm: str
    sj_div: str
    amount: float
    currency: str
    role: str
    fiscal_year: str | None = None
    rcept_no: str | None = None
    source_url: str | None = None


class Evidence(BaseModel):
    claim: str
    metric: str
    value: float
    unit: str
    display_value: str | None = None
    fiscal_year: str
    rcept_no: str
    account_ids: list[str] = Field(default_factory=list)
    accounts: list[EvidenceAccount] = Field(default_factory=list)
    source_url: str


class FundamentalResponse(BaseModel):
    agent: Literal["fundamental"] = "fundamental"
    request_id: str
    ticker: str
    corp_name: str
    verdict: str
    verdict_label: Literal["strong", "moderate", "weak", "insufficient_data"]
    confidence: float = Field(ge=0.0, le=1.0)
    score: int = Field(ge=0, le=100)
    score_breakdown: dict[str, Any]
    analyst_plan: dict[str, Any] = Field(default_factory=dict)
    evidence_graph: dict[str, Any] = Field(default_factory=dict)
    retrieval_context: dict[str, Any] = Field(default_factory=dict)
    ratios: dict[str, Any]
    trend: dict[str, Any]
    insights: dict[str, Any] = Field(default_factory=dict)
    interpretation: str
    evidence: list[Evidence]
    risk_flags: list[str]
    report_html: str
    meta: dict[str, Any]
