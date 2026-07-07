from src.agents.fundamental.report.period import period_basis, period_labels


def test_period_labels_mark_interim_reports():
    assert period_labels(["2023", "2024", "2025", "2026"], "11013") == [
        "2023 1Q",
        "2024 1Q",
        "2025 1Q",
        "2026 1Q",
    ]


def test_period_basis_warns_llm_about_interim_reports():
    basis = period_basis("2026", "11013", "1분기보고서")

    assert basis["is_interim"] is True
    assert basis["description"] == "2026 1Q 1분기보고서 기준"
    assert "연간 실적처럼 표현하지 말고" in basis["llm_instruction"]
