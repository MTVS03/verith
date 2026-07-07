from src.agents.fundamental.api_test.ask_agent import (
    render_agent_markdown,
    resolve_latest_mode_from_question,
    resolve_ticker_from_question,
    resolve_years_from_question,
)
from src.agents.fundamental.core.contract import FundamentalResponse


def test_resolve_ticker_from_korean_question():
    assert resolve_ticker_from_question("LG에너지솔루션 최근 4개년 재무 분석해줘") == "373220"
    assert resolve_ticker_from_question("삼성SDI 리포트 만들어줘") == "006400"
    assert resolve_ticker_from_question("엔켐은 재무 상태 어때?") == "348370"


def test_resolve_years_from_question():
    assert resolve_years_from_question("최근 3개년으로 봐줘") == 3
    assert resolve_years_from_question("6년치 분석") == 6
    assert resolve_years_from_question("10년치 분석") == 6
    assert resolve_years_from_question("그냥 분석해줘") == 4


def test_resolve_latest_mode_from_question():
    assert resolve_latest_mode_from_question("최신 공시로 다시 분석해줘")
    assert resolve_latest_mode_from_question("캐시 없이 fresh 하게 봐줘")
    assert resolve_latest_mode_from_question("그냥 분석해줘") is False


def test_render_agent_markdown_includes_source_policy_and_storage_contract():
    response = FundamentalResponse(
        request_id="req-1",
        ticker="003670",
        corp_name="포스코퓨처엠",
        verdict="재무 체력은 약한 편입니다.",
        verdict_label="weak",
        confidence=0.85,
        score=37,
        score_breakdown={},
        ratios={
            "roe": {"label": "ROE", "display_value": "0.14%"},
        },
        trend={},
        interpretation="DART 기반 해석입니다.",
        evidence=[],
        risk_flags=[],
        report_html="<section></section>",
        meta={
            "llm_provider": "qwen",
            "llm_model": "qwen-test",
            "reprt_name": "1분기보고서",
            "reprt_code": "11013",
            "report_mode": "latest",
            "fresh_dart": True,
            "workflow": ["collect", "report"],
            "retrieval_summary": {
                "policy": "live_check_with_ttl_cache",
                "financial_network_calls": 1,
                "financial_cache_hits": 0,
                "financial_stale_refreshes": 0,
                "financial_bypassed_cache": 1,
                "financial_sources": [
                    {
                        "bsns_year": 2026,
                        "reprt_code": "11013",
                        "fs_div": "CFS",
                        "cache_status": "bypass",
                        "row_count": 42,
                        "rcept_nos": ["20260501000001"],
                    }
                ],
            },
            "verification_summary": {
                "binding_passed": True,
                "consistency_passed": True,
                "guard_passed": True,
                "verdict_stable": True,
                "outcome": "passed",
                "reasons": [],
                "regen_count": 0,
                "initial_provider": "qwen",
                "final_provider": "qwen",
            },
            "erd_payload": {
                "fundamental_report": {
                    "id": "report-1",
                    "data_status": "normal",
                },
                "report_ratios": [{"ratio_name": "roe"}],
                "report_evidence": [{"account_id": "ifrs-full_ProfitLoss"}],
                "report_verification": {"outcome": "passed"},
            },
        },
    )

    markdown = render_agent_markdown("포스코퓨처엠 최신 공시 기준 재무 리포트 만들어줘", response)

    assert "## DART Source Policy" in markdown
    assert "network calls: 1" in markdown
    assert "2026 11013 CFS: bypass" in markdown
    assert "## Verification Gate" in markdown
    assert "verdict_stable: True" in markdown
    assert "## Storage Contract" in markdown
    assert "report_id: report-1" in markdown
