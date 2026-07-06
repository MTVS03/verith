from src.agents.fundamental.data.regular_disclosure import ShareCountData
from src.agents.fundamental.normalize.standardize import MetricValue
from src.agents.fundamental.ratios.calculators import _safe_ratio, calculate_ratios, yoy
from src.agents.fundamental.ratios.scorer import score_financials


def metric(value: float, account_id: str = "test", account_nm: str | None = None, sj_div: str = "BS") -> MetricValue:
    return MetricValue(
        value=value,
        fiscal_year="2025",
        rcept_no="20260301000001",
        account_id=account_id,
        account_nm=account_nm or account_id,
        sj_div=sj_div,
        currency="KRW",
    )


def test_safe_ratio_rejects_missing_zero_and_negative_denominator():
    assert _safe_ratio(None, 10) is None
    assert _safe_ratio(10, None) is None
    assert _safe_ratio(10, 0) is None
    assert _safe_ratio(10, -5) is None


def test_yoy_rejects_negative_previous_period():
    assert yoy(10, -5) is None
    assert yoy(-5, 10) is None
    assert yoy(15, 10) == 50.0


def test_growth_marks_profit_to_loss_as_not_meaningful():
    ratios, _, flags = calculate_ratios(
        {
            "2024": {"operating_income": metric(100), "revenue": metric(1000)},
            "2025": {"operating_income": metric(-55), "revenue": metric(1100)},
        }
    )

    assert ratios["operating_income_growth"]["value"] is None
    assert ratios["operating_income_growth"]["status"] == "not_meaningful"
    assert ratios["operating_income_growth"]["display_value"] == "적자전환"
    assert "NOT_MEANINGFUL_OPERATING_INCOME_GROWTH" in flags


def test_missing_metrics_emit_missing_flags():
    ratios, _, flags = calculate_ratios({"2025": {"revenue": metric(100)}})

    assert ratios["operating_margin"]["value"] is None
    assert "MISSING_OPERATING_MARGIN" in flags
    assert "MISSING_BPS" in flags


def test_ratio_evidence_contains_account_level_amounts_and_roles():
    _, evidence, flags = calculate_ratios(
        {
            "2025": {
                "profit_loss": metric(30_000_000, "ifrs-full_ProfitLoss", "Profit loss", "IS"),
                "equity": metric(1_000_000_000, "ifrs-full_Equity", "Equity", "BS"),
            }
        }
    )

    assert "MISSING_ROE" not in flags
    roe_evidence = next(item for item in evidence if item.metric == "roe")
    assert [account.role for account in roe_evidence.accounts] == ["numerator", "denominator"]
    assert [account.account_nm for account in roe_evidence.accounts] == ["Profit loss", "Equity"]
    assert [account.sj_div for account in roe_evidence.accounts] == ["IS", "BS"]
    assert [account.amount for account in roe_evidence.accounts] == [30_000_000, 1_000_000_000]


def test_bps_uses_dart_issued_share_count():
    ratios, evidence, flags = calculate_ratios(
        {"2025": {"equity": metric(1_000_000, "ifrs-full_Equity")}},
        share_count=ShareCountData(
            issued_shares=100,
            distributed_shares=90,
            treasury_shares=10,
            share_class="보통주",
            basis="common_issued_shares",
            rcept_no="20260301000002",
            stlm_dt="2025-12-31",
        ),
    )

    assert ratios["bps"]["value"] == 10000
    assert ratios["bps"]["issued_shares"] == 100
    assert "MISSING_BPS" not in flags
    assert any(item.metric == "bps" and "stockTotqySttus:istc_totqy" in item.account_ids for item in evidence)
    bps_evidence = next(item for item in evidence if item.metric == "bps")
    assert [account.role for account in bps_evidence.accounts] == ["equity", "share_count"]
    assert bps_evidence.accounts[0].amount == 1_000_000
    assert bps_evidence.accounts[1].amount == 100


def test_score_boundaries_and_insufficient_data():
    base = {
        "roe": {"value": 15},
        "operating_margin": {"value": 12},
        "debt_ratio": {"value": 80},
        "current_ratio": {"value": 180},
        "revenue_growth": {"value": 20},
        "operating_income_growth": {"value": 30},
    }
    assert score_financials(base)[2] == "strong"

    moderate = base | {
        "roe": {"value": 8},
        "operating_margin": {"value": 7},
        "debt_ratio": {"value": 250},
        "current_ratio": {"value": 100},
        "revenue_growth": {"value": 0},
        "operating_income_growth": {"value": 0},
    }
    assert score_financials(moderate)[2] == "moderate"

    insufficient = base | {"roe": {"value": None}, "operating_margin": {"value": None}}
    assert score_financials(insufficient)[2] == "insufficient_data"
