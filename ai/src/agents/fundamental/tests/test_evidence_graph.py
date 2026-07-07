from src.agents.fundamental.core.contract import Evidence, EvidenceAccount
from src.agents.fundamental.evidence.graph_builder import (
    build_analyst_plan,
    build_evidence_graph,
    build_retrieval_context,
)


def test_evidence_graph_builds_section_briefs_and_metric_claims():
    ratios = {
        "roe": {"label": "ROE", "category": "수익성", "value": -2.5, "unit": "%", "status": "available"},
        "operating_margin": {"label": "영업이익률", "category": "수익성", "value": 5.2, "unit": "%", "status": "available"},
        "debt_ratio": {"label": "부채비율", "category": "안정성", "value": 140.0, "unit": "%", "status": "available"},
        "current_ratio": {"label": "유동비율", "category": "안정성", "value": 90.0, "unit": "%", "status": "available"},
        "eps": {"label": "EPS", "category": "밸류 기초", "value": -4500, "unit": "원", "status": "available"},
    }
    evidence = [
        Evidence(
            claim="ROE -2.5",
            metric="roe",
            value=-2.5,
            unit="%",
            fiscal_year="2025",
            rcept_no="20260301000001",
            account_ids=["ifrs-full_ProfitLoss"],
            accounts=[
                EvidenceAccount(
                    account_id="ifrs-full_ProfitLoss",
                    account_nm="당기순이익",
                    sj_div="IS",
                    amount=-2500.0,
                    currency="KRW",
                    role="numerator",
                    fiscal_year="2025",
                    rcept_no="20260301000001",
                    source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260301000001",
                )
            ],
            source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260301000001",
        )
    ]

    graph = build_evidence_graph(ratios, {}, {}, evidence, ["MISSING_BPS"])
    plan = build_analyst_plan(graph, 37, "weak")
    context = build_retrieval_context(graph, plan)

    assert "profitability" in plan["section_order"]
    assert "data_limits" in plan["section_order"]
    assert any(node.get("metric") == "roe" and node.get("stance") == "caution" for node in graph["nodes"])
    assert any(node["type"] == "account" and node["account_nm"] == "당기순이익" for node in graph["nodes"])
    assert any(node["type"] == "claim" and node["metric"] == "roe" for node in graph["nodes"])
    assert any(edge["relation"] == "contains_account" for edge in graph["edges"])
    assert any(edge["relation"] == "calculates" and edge["role"] == "numerator" for edge in graph["edges"])
    assert any(edge["relation"] == "supports_claim" for edge in graph["edges"])
    assert any(claim["metric"] == "eps" and claim["display_value"] == "-4,500원" for claim in context["metric_claims"])
    assert all("를 중심으로" not in brief for brief in plan["section_briefs"].values())


def test_analyst_plan_prioritizes_requested_intent():
    graph = {
        "sections": [
            {"id": "profitability", "signal": "supportive", "summary": "수익성"},
            {"id": "stability", "signal": "supportive", "summary": "안정성"},
            {"id": "growth", "signal": "supportive", "summary": "성장성"},
            {"id": "valuation_basis", "signal": "supportive", "summary": "밸류"},
        ]
    }

    plan = build_analyst_plan(graph, 50, "moderate", "growth")

    assert plan["section_order"][0] == "growth"
    assert plan["score_context"]["intent"] == "growth"
