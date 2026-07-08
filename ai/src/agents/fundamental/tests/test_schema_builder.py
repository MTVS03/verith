from __future__ import annotations

from src.agents.fundamental.core.contract import Evidence, EvidenceAccount
from src.agents.fundamental.report.schema_builder import build_erd_payload


# 출처: backend/db/models/fundamental/*.py (AI 테스트에서는 backend import 금지)
FUNDAMENTAL_REPORT_COLUMNS = {
    "id",
    "request_id",
    "stock_code",
    "corp_code",
    "bsns_year",
    "years",
    "fs_div",
    "report_mode",
    "reprt_code",
    "reprt_name",
    "period_label",
    "verdict_label",
    "verdict",
    "fin_score",
    "confidence",
    "data_status",
    "risk_flags",
    "score_breakdown",
    "report_html",
    "llm_provider",
    "llm_model",
    "llm_latency_ms",
    "dart_calls",
    "trace_id",
    "as_of",
    "created_at",
    "meta",
}
REPORT_RATIO_COLUMNS = {
    "id",
    "report_id",
    "ratio_name",
    "label",
    "category",
    "fiscal_year",
    "fiscal_period",
    "value",
    "unit",
    "display_value",
    "status",
    "reason",
    "formula",
    "basis",
}
REPORT_EVIDENCE_COLUMNS = {
    "id",
    "report_id",
    "ratio_id",
    "metric",
    "claim",
    "rcept_no",
    "bsns_year",
    "fiscal_period",
    "sj_div",
    "account_id",
    "account_nm",
    "amount",
    "unit",
    "display_value",
    "source_url",
    "role",
    "raw",
}
REPORT_INTERPRETATION_COLUMNS = {
    "id",
    "report_id",
    "interpretation",
    "interpretation_source",
    "provider",
    "model",
    "prompt_meta",
}
REPORT_VERIFICATION_COLUMNS = {
    "id",
    "report_id",
    "binding_passed",
    "consistency_passed",
    "verdict_stable",
    "outcome",
    "regen_count",
    "evidence_count",
    "guard_violations",
    "flags",
}
REPORT_INSIGHT_COLUMNS = {"id", "report_id", "insight_type", "source_endpoint", "rcept_no", "payload"}


def test_build_erd_payload_maps_report_ratios_evidence_and_verification() -> None:
    evidence = [
        Evidence(
            claim="roe 3.0",
            metric="roe",
            value=3.0,
            unit="%",
            fiscal_year="2025",
            rcept_no="20260301000001",
            account_ids=["ifrs-full_ProfitLoss", "ifrs-full_Equity"],
            accounts=[
                EvidenceAccount(
                    account_id="ifrs-full_ProfitLoss",
                    account_nm="Profit loss",
                    sj_div="IS",
                    amount=30_000_000,
                    currency="KRW",
                    role="numerator",
                    fiscal_year="2025",
                    rcept_no="20260301000001",
                    source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260301000001",
                ),
                EvidenceAccount(
                    account_id="ifrs-full_Equity",
                    account_nm="Equity",
                    sj_div="BS",
                    amount=1_000_000_000,
                    currency="KRW",
                    role="denominator",
                    fiscal_year="2025",
                    rcept_no="20260301000001",
                    source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260301000001",
                ),
            ],
            source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260301000001",
        )
    ]

    payload = build_erd_payload(
        request_id="req-1",
        trace_id="trace-1",
        ticker="051910",
        corp_name="LG화학",
        corp_code="00356361",
        bsns_year=2025,
        fs_div="CFS",
        reprt_code="11011",
        reprt_name="사업보고서",
        report_mode="annual",
        years_count=3,
        verdict="재무 체력은 보통 수준입니다.",
        confidence=0.85,
        score=45,
        label="moderate",
        score_breakdown={"score_type": "absolute_financial_health"},
        ratios={
            "roe": {
                "value": 3.0,
                "fiscal_year": "2025",
                "unit": "%",
                "label": "ROE",
                "category": "수익성",
                "status": "available",
            }
        },
        evidence=evidence,
        trend={
            "years": ["2023", "2024", "2025"],
            "revenue": [100_000_000, 120_000_000, 130_000_000],
            "op_income": [10_000_000, 12_000_000, 15_000_000],
            "roe": [1.1, 2.2, 3.0],
        },
        insights={
            "dividend": {
                "source_endpoint": "alotMatter",
                "rcept_no": "20260301000001",
                "status": "available",
            }
        },
        interpretation="ROE와 안정성을 함께 확인합니다.",
        interpretation_source="qwen",
        risk_flags=[],
        verification={
            "binding_passed": True,
            "consistency_passed": True,
            "verdict_stable": True,
            "outcome": "passed",
            "regen_count": 0,
            "guard_violations": [],
        },
        retrieval_summary={"policy": "live_check_with_ttl_cache"},
        report_html="<section>재무 리포트</section>",
        llm_provider="qwen",
        llm_model="Qwen3",
        llm_latency_ms=123,
        dart_calls=4,
        meta={"trace_id": "trace-1", "erd_payload": {"must": "be stripped"}},
    )

    assert set(payload["fundamental_report"]) == FUNDAMENTAL_REPORT_COLUMNS
    assert payload["report_ratios"]
    assert all(set(item) == REPORT_RATIO_COLUMNS for item in payload["report_ratios"])
    assert payload["report_evidence"]
    assert all(set(item) == REPORT_EVIDENCE_COLUMNS for item in payload["report_evidence"])
    assert set(payload["report_interpretation"]) == REPORT_INTERPRETATION_COLUMNS
    assert set(payload["report_verification"]) == REPORT_VERIFICATION_COLUMNS
    assert payload["report_insights"]
    assert all(set(item) == REPORT_INSIGHT_COLUMNS for item in payload["report_insights"])
    assert payload["report_filing_snippets"] == []

    assert payload["fundamental_report"]["stock_code"] == "051910"
    assert payload["fundamental_report"]["corp_code"] == "00356361"
    assert payload["fundamental_report"]["fs_div"] == "CFS"
    assert payload["fundamental_report"]["reprt_code"] == "11011"
    assert payload["fundamental_report"]["years"] == 3
    assert payload["fundamental_report"]["report_mode"] == "annual"
    assert payload["fundamental_report"]["reprt_name"] == "사업보고서"
    assert payload["fundamental_report"]["period_label"] == "2025"
    assert payload["fundamental_report"]["score_breakdown"]["score_type"] == "absolute_financial_health"
    assert payload["fundamental_report"]["report_html"] == "<section>재무 리포트</section>"
    assert payload["fundamental_report"]["llm_provider"] == "qwen"
    assert payload["fundamental_report"]["llm_model"] == "Qwen3"
    assert payload["fundamental_report"]["llm_latency_ms"] == 123
    assert payload["fundamental_report"]["dart_calls"] == 4
    assert "erd_payload" not in payload["fundamental_report"]["meta"]
    assert payload["fundamental_report"]["data_status"] == "normal"
    ratio_rows = payload["report_ratios"]
    assert ratio_rows[0]["ratio_name"] == "roe"
    assert ratio_rows[0]["formula"] == "profit_loss / equity * 100"
    trend_rows = [
        item
        for item in ratio_rows
        if item["ratio_name"] in {"revenue", "op_income", "roe"} and item["basis"] == {"source": "trend"}
    ]
    assert {(item["ratio_name"], item["fiscal_year"]) for item in trend_rows} == {
        ("revenue", 2023),
        ("revenue", 2024),
        ("revenue", 2025),
        ("op_income", 2023),
        ("op_income", 2024),
        ("op_income", 2025),
        ("roe", 2023),
        ("roe", 2024),
    }
    assert len({item["id"] for item in ratio_rows}) == len(ratio_rows)
    assert len(payload["report_evidence"]) == 2
    assert {item["role"] for item in payload["report_evidence"]} == {"numerator", "denominator"}
    evidence_rows = {item["role"]: item for item in payload["report_evidence"]}
    assert evidence_rows["numerator"]["amount"] == "30000000"
    assert evidence_rows["denominator"]["amount"] == "1000000000"
    assert evidence_rows["numerator"]["amount"] != "3.0"
    assert evidence_rows["numerator"]["sj_div"] == "IS"
    assert evidence_rows["denominator"]["sj_div"] == "BS"
    assert evidence_rows["numerator"]["account_nm"] == "Profit loss"
    assert evidence_rows["denominator"]["account_nm"] == "Equity"
    assert evidence_rows["numerator"]["unit"] == "KRW"
    assert evidence_rows["numerator"]["metric"] == "roe"
    assert evidence_rows["numerator"]["claim"] == "roe 3.0"
    assert evidence_rows["numerator"]["fiscal_period"] == "2025"
    assert evidence_rows["numerator"]["display_value"] is None
    assert evidence_rows["numerator"]["raw"]["account_id"] == "ifrs-full_ProfitLoss"
    assert payload["report_interpretation"]["interpretation_source"] == "qwen"
    assert payload["report_interpretation"]["provider"] == "qwen"
    assert payload["report_interpretation"]["model"] == "Qwen3"
    assert payload["report_verification"]["binding_passed"] is True
    assert payload["report_verification"]["evidence_count"] == 2
    assert payload["report_verification"]["guard_violations"] == []
    assert payload["report_verification"]["flags"] == []
    assert payload["report_insights"][0]["insight_type"] == "dividend"
