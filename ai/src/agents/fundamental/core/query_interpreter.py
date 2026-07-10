from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from .contract import FundamentalAgentInput, FundamentalRequest


Intent = Literal[
    "fundamental_health", "profitability", "stability", "growth", "valuation"
]
FsDiv = Literal["CFS", "OFS"]
ReportMode = Literal["annual", "latest"]

_YEARS_RE = re.compile(r"(?P<years>\d+)\s*(?:개년|년)")
_QUARTERLY_KEYWORDS = ("분기", "이번 분기", "분기보고서")
_INTENT_RULES: tuple[tuple[Intent, tuple[str, ...]], ...] = (
    ("profitability", ("수익성", "마진", "roe", "ROE", "이익률")),
    ("stability", ("부채", "안정성", "유동", "건전성", "레버리지", "차입")),
    ("growth", ("성장", "매출 증가")),
    ("valuation", ("밸류", "per", "pbr", "PER", "PBR", "저평가", "고평가")),
)


class QueryInterpretation(BaseModel):
    intent: Intent = "fundamental_health"
    fs_div: FsDiv = "CFS"
    report_mode: ReportMode = "annual"
    years: int = Field(default=4, ge=1, le=6)
    applied_rules: list[str] = Field(default_factory=list)
    defaulted_fields: list[str] = Field(default_factory=list)


def _clamp_years(value: int) -> int:
    return min(max(value, 1), 6)


def interpret_query(query: str) -> QueryInterpretation:
    text = query.strip()
    lower_text = text.casefold()
    applied_rules: list[str] = []
    defaulted_fields: list[str] = []

    years = 4
    years_match = _YEARS_RE.search(text)
    if years_match is not None:
        years = _clamp_years(int(years_match.group("years")))
        applied_rules.append("years:n_years")
    else:
        defaulted_fields.append("years")

    report_mode: ReportMode = "annual"
    has_quarterly_keyword = any(keyword in text for keyword in _QUARTERLY_KEYWORDS)
    if has_quarterly_keyword:
        report_mode = "latest"
        applied_rules.append("report_mode:quarterly_keyword")
    else:
        defaulted_fields.append("report_mode")

    fs_div: FsDiv = "CFS"
    has_standalone = "별도" in text
    has_consolidated = "연결" in text
    if has_standalone and not has_consolidated:
        fs_div = "OFS"
        applied_rules.append("fs_div:standalone")
    elif has_consolidated and not has_standalone:
        fs_div = "CFS"
        applied_rules.append("fs_div:consolidated")
    else:
        defaulted_fields.append("fs_div")

    matched_intents: list[Intent] = [
        candidate
        for candidate, keywords in _INTENT_RULES
        if any(keyword.casefold() in lower_text for keyword in keywords)
    ]
    intent: Intent = "fundamental_health"
    if len(matched_intents) == 1:
        intent = matched_intents[0]
        applied_rules.append(f"intent:{intent}")
    elif len(matched_intents) >= 2:
        applied_rules.append("intent:multi_axis_comprehensive")
    else:
        defaulted_fields.append("intent")

    return QueryInterpretation(
        intent=intent,
        fs_div=fs_div,
        report_mode=report_mode,
        years=years,
        applied_rules=applied_rules,
        defaulted_fields=defaulted_fields,
    )


def to_fundamental_request(
    public_input: FundamentalAgentInput,
) -> tuple[FundamentalRequest, QueryInterpretation]:
    interpretation = interpret_query(public_input.query)
    return (
        FundamentalRequest(
            request_id=public_input.request_id,
            trace_id=public_input.trace_id,
            ticker=public_input.ticker,
            intent=interpretation.intent,
            fs_div=interpretation.fs_div,
            report_mode=interpretation.report_mode,
            years=interpretation.years,
        ),
        interpretation,
    )
