from src.agents.fundamental.verify.stability import assess_verdict_stability, infer_verdict_label


def test_assess_verdict_stability_accepts_explicit_label() -> None:
    result = assess_verdict_stability("재무 체력이 양호하다는 표현이 섞였습니다.", "weak", "weak")

    assert result.verdict_stable is True
    assert result.outcome == "passed"


def test_assess_verdict_stability_flags_explicit_label_mismatch() -> None:
    result = assess_verdict_stability("재무 체력이 약한 편입니다.", "weak", "strong")

    assert result.verdict_stable is False
    assert result.outcome == "guarded"
    assert "verdict_label_language_mismatch" in result.reasons


def test_assess_verdict_stability_falls_back_to_language_when_label_missing() -> None:
    result = assess_verdict_stability("재무 체력이 약한 편입니다.", "weak")

    assert result.verdict_stable is True


def test_infer_verdict_label_handles_insufficient_data_before_weak_terms() -> None:
    assert infer_verdict_label("데이터가 제한되어 판단하기 어렵습니다.") == "insufficient_data"
