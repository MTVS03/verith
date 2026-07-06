from src.agents.fundamental.core.contract import Evidence
from src.agents.fundamental.emit.html_builder import build_report_html


def _evidence() -> list[Evidence]:
    return [
        Evidence(
            claim="매출",
            metric="revenue",
            value=23_671_759_000_000,
            unit="원",
            fiscal_year="2026 1Q",
            rcept_no="20260501000001",
            account_ids=["ifrs-full_Revenue"],
            source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260501000001",
        )
    ]


def test_build_report_html_renders_chart_gate_and_accessible_dart_link():
    html = build_report_html(
        corp_name="LG에너지솔루션",
        ticker="373220",
        score=45,
        label="moderate",
        confidence=0.85,
        ratios={
            "operating_income_growth": {
                "label": "영업이익 성장률",
                "category": "성장성",
                "value": None,
                "unit": "%",
                "display_value": "적자전환",
                "status": "not_meaningful",
            }
        },
        trend={
            "years": ["2025", "2026"],
            "period_labels": ["2025 1Q", "2026 1Q"],
            "revenue": [6_000_000_000_000, 6_500_000_000_000],
            "op_income": [100_000_000_000, -50_000_000_000],
            "roe": [0.3, -1.2],
            "display": {
                "revenue": ["6조원", "6조 5,000억원"],
                "op_income": ["1,000억원", "-500억원"],
                "roe": ["0.30%", "-1.20%"],
            },
        },
        interpretation="1분기 기준으로 수익성 압박이 확인됩니다.",
        evidence=_evidence(),
        evidence_graph={
            "nodes": [
                {"id": "filing:20260501000001", "type": "filing", "rcept_no": "20260501000001"},
                {"id": "metric:revenue", "type": "metric", "metric": "revenue", "label": "매출"},
            ],
            "edges": [{"from": "filing:20260501000001", "to": "metric:revenue", "relation": "supports_metric"}],
        },
        risk_flags=["MISSING_BPS", "NOT_MEANINGFUL_OPERATING_INCOME_GROWTH"],
        meta={
            "reprt_name": "1분기보고서",
            "llm_provider": "template",
            "llm_guard_violations": [],
            "period_basis": {
                "report_name": "1분기보고서",
                "description": "2026 1Q 1분기보고서 기준",
                "is_interim": True,
            },
            "retrieval_summary": {
                "financial_statement_ttl_seconds": 86400,
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
            "erd_payload": {
                "fundamental_report": {
                    "id": "report-1",
                    "data_status": "partial_with_flags",
                },
                "report_ratios": [{"ratio_name": "roe"}],
                "report_evidence": [{"account_id": "ifrs-full_Revenue"}],
                "report_verification": {"outcome": "passed"},
            },
        },
    )

    assert "<svg" in html
    assert "height:320px" in html
    assert "max-width:1440px" in html
    assert 'stroke="#0ea371" stroke-width="3"' in html
    assert "data-trend=" in html
    assert "표로 보기" in html
    assert "증거 연결" in html
    assert "1개" in html
    assert "검증 게이트 통과" in html
    assert 'target="_blank" rel="noopener"' in html
    assert "데이터 신뢰도" in html
    assert "Confidence" not in html
    assert "적자전환" in html
    assert "산출 불가%" not in html
    assert "총자본 기준 BPS" in html
    assert "지배주주지분" not in html
    assert "DART 1분기보고서 기반" not in html
    assert "DART 공시 기반 재무 분석" in html
    assert "DART Source Policy" in html
    assert "network 1" in html
    assert "bypass" in html
    assert "규칙 기반 안전 해석" in html
    assert "저장 계약 미리보기" in html
    assert "@media print" in html
    assert "Evidence Graph Mermaid" in html
    assert "supports_metric" in html
