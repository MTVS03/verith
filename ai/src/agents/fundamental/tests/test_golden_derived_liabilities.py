import json
from pathlib import Path

from src.agents.fundamental.normalize.standardize import standardize_year_rows
from src.agents.fundamental.ratios.calculators import calculate_ratios


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_derives_liabilities_when_total_liabilities_row_is_missing():
    rows = json.loads((FIXTURES / "synthetic_derived_liabilities_rows.json").read_text(encoding="utf-8"))

    metrics = standardize_year_rows(rows, "2025")

    expected = metrics["equity_and_liabilities"].value - metrics["equity"].value
    assert metrics["liabilities"].value == expected
    assert metrics["liabilities"].account_id.startswith("derived:")

    ratios, _, flags = calculate_ratios({"2025": metrics})
    assert "DERIVED_LIABILITIES" in flags
    assert ratios["debt_ratio"]["value"] == 142.16


def test_equity_and_liabilities_is_not_mapped_as_liabilities():
    rows = json.loads((FIXTURES / "synthetic_derived_liabilities_rows.json").read_text(encoding="utf-8"))

    metrics = standardize_year_rows(rows, "2025")

    assert metrics["equity_and_liabilities"].account_id == "ifrs-full_EquityAndLiabilities"
    assert metrics["liabilities"].account_id != "ifrs-full_EquityAndLiabilities"
