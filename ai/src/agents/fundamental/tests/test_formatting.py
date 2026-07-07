from src.agents.fundamental.core.contract import Evidence
from src.agents.fundamental.report.formatting import (
    attach_display_fields,
    format_krw,
    format_krw_compact,
    format_metric_value,
    format_number,
)


def test_format_krw_uses_korean_large_units_for_report_amounts():
    assert format_krw(23_671_759_000_000) == "23조 6,717억 5,900만원"
    assert format_krw(-1_234_567_890) == "-12억 3,456만 7,890원"


def test_format_krw_keeps_small_per_share_values_readable():
    assert format_krw(-4585.0) == "-4,585원"
    assert format_krw(125306.31) == "125,306.31원"


def test_format_krw_compact_rounds_to_eok_for_trend_labels():
    assert format_krw_compact(5_354_844_754_963) == "5조 3,548억원"
    assert format_krw_compact(-123_456_789_000) == "-1,235억원"


def test_format_metric_value_handles_units_and_missing_values():
    assert format_metric_value(12.345, "%") == "12.35%"
    assert format_metric_value(None, "원") == "산출 불가"
    assert format_metric_value(None, "%") == "산출 불가"
    assert format_number(1000) == "1,000"


def test_attach_display_fields_enriches_response_payload_parts():
    ratios = {"revenue": {"value": 23_671_759_000_000, "unit": "원"}}
    trend = {"revenue": [23_671_759_000_000], "op_income": [575_387_000_000], "roe": [0.28]}
    evidence = [
        Evidence(
            claim="매출",
            metric="revenue",
            value=23_671_759_000_000,
            unit="원",
            fiscal_year="2025",
            rcept_no="20260301000001",
            account_ids=["ifrs-full_Revenue"],
            source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260301000001",
        )
    ]

    attach_display_fields(ratios, trend, evidence)

    assert ratios["revenue"]["display_value"] == "23조 6,717억 5,900만원"
    assert trend["display"]["op_income"] == ["5,754억원"]
    assert trend["display"]["roe"] == ["0.28%"]
    assert evidence[0].display_value == "23조 6,717억 5,900만원"
