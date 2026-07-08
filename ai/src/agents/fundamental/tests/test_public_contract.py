from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agents.fundamental.core.contract import FundamentalAgentInput
from src.agents.fundamental.core.query_interpreter import interpret_query, to_fundamental_request


@pytest.mark.parametrize(
    ("query", "expected_intent"),
    [
        ("수익성과 마진, ROE를 봐줘", "profitability"),
        ("부채와 유동성 기준으로 안정성 확인", "stability"),
        ("매출 증가와 성장 추세", "growth"),
        ("PER PBR 밸류와 저평가 여부", "valuation"),
        ("재무 상태 봐줘", "fundamental_health"),
    ],
)
def test_query_interpreter_intent_rules(query: str, expected_intent: str) -> None:
    result = interpret_query(query)

    assert result.intent == expected_intent


def test_query_interpreter_uses_defaults_when_no_rule_matches() -> None:
    result = interpret_query("재무 상태 간단히 봐줘")

    assert result.report_mode == "annual"
    assert result.years == 4
    assert result.fs_div == "CFS"
    assert result.intent == "fundamental_health"
    assert set(result.defaulted_fields) == {"report_mode", "years", "fs_div", "intent"}


def test_query_interpreter_handles_compound_query_and_clamps_years() -> None:
    result = interpret_query("최근 9년 연결 기준 수익성 ROE를 봐줘")

    assert result.report_mode == "annual"
    assert result.years == 6
    assert result.fs_div == "CFS"
    assert result.intent == "profitability"
    assert result.applied_rules == [
        "years:n_years",
        "report_mode:annual_recent_nyears_override",
        "fs_div:consolidated",
        "intent:profitability",
    ]


def test_query_interpreter_standalone_financial_statement() -> None:
    result = interpret_query("별도 기준 2개년 부채 안정성 확인")

    assert result.fs_div == "OFS"
    assert result.years == 2
    assert result.intent == "stability"


def test_public_input_validates_ticker_and_blank_values() -> None:
    with pytest.raises(ValidationError):
        FundamentalAgentInput(request_id="req", trace_id="trace", ticker="A05930", query="재무")

    with pytest.raises(ValidationError):
        FundamentalAgentInput(request_id="req", trace_id=" ", ticker="005930", query="재무")


def test_public_input_adapter_builds_internal_request() -> None:
    public_input = FundamentalAgentInput(
        request_id="req-1",
        trace_id="trace-1",
        ticker="005930",
        query="최신 별도 3년 성장 분석",
    )

    request, interpretation = to_fundamental_request(public_input)

    assert request.request_id == "req-1"
    assert request.trace_id == "trace-1"
    assert request.ticker == "005930"
    assert request.report_mode == "latest"
    assert request.fs_div == "OFS"
    assert request.years == 3
    assert request.intent == "growth"
    assert interpretation.report_mode == "latest"


@pytest.mark.parametrize(
    ("query", "expected_report_mode", "expected_years", "expected_rule"),
    [
        ("최근 3년 매출 성장률", "annual", 3, "report_mode:annual_recent_nyears_override"),
        ("최근 실적 어때", "latest", 4, "report_mode:recent_keyword"),
        ("최근 3년 분기 흐름", "latest", 3, "report_mode:explicit_latest_keyword"),
        ("최신 3개년", "latest", 3, "report_mode:explicit_latest_keyword"),
    ],
)
def test_query_interpreter_recent_nyears_regression(
    query: str,
    expected_report_mode: str,
    expected_years: int,
    expected_rule: str,
) -> None:
    result = interpret_query(query)

    assert result.report_mode == expected_report_mode
    assert result.years == expected_years
    assert expected_rule in result.applied_rules
