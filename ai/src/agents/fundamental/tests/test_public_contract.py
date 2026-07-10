from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agents.fundamental.core.contract import FundamentalAgentInput
from src.agents.fundamental.core.query_interpreter import (
    interpret_query,
    to_fundamental_request,
)


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
        "fs_div:consolidated",
        "intent:profitability",
    ]
    assert "report_mode" in result.defaulted_fields


def test_query_interpreter_standalone_financial_statement() -> None:
    result = interpret_query("별도 기준 2개년 부채 안정성 확인")

    assert result.fs_div == "OFS"
    assert result.years == 2
    assert result.intent == "stability"


def test_public_input_validates_ticker_and_blank_values() -> None:
    with pytest.raises(ValidationError):
        FundamentalAgentInput(
            request_id="req", trace_id="trace", ticker="A05930", query="재무"
        )

    with pytest.raises(ValidationError):
        FundamentalAgentInput(
            request_id="req", trace_id=" ", ticker="005930", query="재무"
        )


def test_public_input_adapter_builds_internal_request() -> None:
    public_input = FundamentalAgentInput(
        request_id="req-1",
        trace_id="trace-1",
        ticker="005930",
        query="이번 분기 별도 3년 성장 분석",
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
    ("query", "expected_years"),
    [
        # Supervisor 성형 상투어인 bare `최근`이 연간 분석을 분기로 뒤집지 않아야 한다.
        ("최근 실적 어때", 4),
        # 기간을 뜻하는 bare `최신`도 명시적 분기 요청이 아니므로 연간 기본값을 유지한다.
        ("최신 3개년", 3),
    ],
)
def test_query_interpreter_bare_recency_keeps_annual_mode(
    query: str, expected_years: int
) -> None:
    result = interpret_query(query)

    assert result.report_mode == "annual"
    assert result.years == expected_years
    assert "report_mode" in result.defaulted_fields
    assert not any(rule.startswith("report_mode:") for rule in result.applied_rules)


def test_query_interpreter_recent_nyears_keeps_annual_mode() -> None:
    result = interpret_query("최근 3년 매출 성장률")

    assert result.report_mode == "annual"
    assert result.years == 3
    assert "report_mode" in result.defaulted_fields


@pytest.mark.parametrize(
    ("query", "expected_years"),
    [
        ("이번 분기 실적", 4),
        ("최근 3년 분기 흐름", 3),
        ("분기보고서 기준 재무 상태", 4),
    ],
)
def test_query_interpreter_quarterly_keywords_select_latest_mode(
    query: str,
    expected_years: int,
) -> None:
    result = interpret_query(query)

    assert result.report_mode == "latest"
    assert result.years == expected_years
    assert "report_mode:quarterly_keyword" in result.applied_rules
    assert "report_mode" not in result.defaulted_fields


@pytest.mark.parametrize(
    ("query", "expected_years"),
    [("0개년 재무 상태", 1), ("9개년 재무 상태", 6)],
)
def test_query_interpreter_clamps_n_years(query: str, expected_years: int) -> None:
    result = interpret_query(query)

    assert result.years == expected_years


@pytest.mark.parametrize(
    "query",
    [
        "삼성전자의 최근 실적, 수익성, 안정성, 밸류에이션 관점에서 재무 상태를 분석해줘.",
        "배터리 화재 이슈가 실적·수익성·안정성·성장성·밸류에이션에 줄 영향 중심으로…",
        "수익성과 안정성을 점검",
    ],
)
def test_query_interpreter_supervisor_multi_axis_queries_are_comprehensive(
    query: str,
) -> None:
    result = interpret_query(query)

    assert result.intent == "fundamental_health"
    assert result.report_mode == "annual"
    assert "intent:multi_axis_comprehensive" in result.applied_rules
    assert "intent" not in result.defaulted_fields


@pytest.mark.parametrize(
    ("query", "expected_intent"),
    [
        ("부채비율과 재무 안정성을 중심으로 재무 상태를 분석해줘", "stability"),
        ("레버리지 상황을 점검", "stability"),
        ("재무 건전성 전반을 점검", "stability"),
        ("차입 상황을 점검", "stability"),
        ("이익률을 점검", "profitability"),
        ("고평가 여부를 점검", "valuation"),
    ],
)
def test_query_interpreter_conservative_synonyms_select_single_axis(
    query: str,
    expected_intent: str,
) -> None:
    result = interpret_query(query)

    assert result.intent == expected_intent
    assert f"intent:{expected_intent}" in result.applied_rules
    assert "intent:multi_axis_comprehensive" not in result.applied_rules


def test_query_interpreter_latest_prose_keeps_annual_stability() -> None:
    result = interpret_query("최신 재무 상태로 안정성 점검")

    assert result.intent == "stability"
    assert result.report_mode == "annual"
    assert "report_mode" in result.defaulted_fields
