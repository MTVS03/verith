import json
from pathlib import Path

from src.agents.fundamental.normalize.standardize import standardize_year_rows


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_lgchem_prefers_common_basic_eps_over_preferred_eps():
    rows = json.loads((FIXTURES / "lgchem_2025_cfs_rows.json").read_text(encoding="utf-8"))

    metrics = standardize_year_rows(rows, "2025")

    assert metrics["basic_eps"].value == -23244.0
    assert metrics["basic_eps"].account_id == "ifrs-full_BasicEarningsLossPerShare"
    assert metrics["revenue"].value == 45932167000000.0
    assert metrics["operating_income"].value == 1180900000000.0
    assert metrics["liabilities"].value == 53956116000000.0
