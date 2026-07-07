from src.agents.fundamental.verify.consistency import EPS_MISMATCH_FLAG, validate_eps_consistency


def test_validate_eps_consistency_accepts_matching_annual_eps() -> None:
    flags, notes = validate_eps_consistency(
        {"eps": {"value": -100.0}},
        {"dividend": {"dart_eps": -101.0, "source_endpoint": "alotMatter", "rcept_no": "20260301000001"}},
        "11011",
    )

    assert flags == []
    assert notes[0]["code"] == "CONSISTENCY_EPS_MATCH"


def test_validate_eps_consistency_flags_annual_mismatch() -> None:
    flags, notes = validate_eps_consistency(
        {"eps": {"value": -48.0}},
        {"dividend": {"dart_eps": -67.0, "source_endpoint": "alotMatter", "rcept_no": "20260301000001"}},
        "11011",
    )

    assert flags == [EPS_MISMATCH_FLAG]
    assert notes[0]["calculated_eps"] == -48.0
    assert notes[0]["dart_eps"] == -67.0


def test_validate_eps_consistency_skips_interim_report_period_mismatch() -> None:
    flags, notes = validate_eps_consistency(
        {"eps": {"value": 10.0}},
        {"dividend": {"dart_eps": 100.0}},
        "11013",
    )

    assert flags == []
    assert notes[0]["code"] == "CONSISTENCY_EPS_SKIPPED_PERIOD_MISMATCH"
