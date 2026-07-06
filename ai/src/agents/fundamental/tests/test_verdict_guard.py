from src.agents.fundamental.core.contract import Evidence
from src.agents.fundamental.verify.verdict_guard import guard_llm_output


RATIOS = {
    "roe": {"value": 3.25, "unit": "%"},
    "debt_ratio": {"value": 142.16, "unit": "%"},
}
EVIDENCE = [
    Evidence(
        claim="ROE 3.25",
        metric="roe",
        value=3.25,
        unit="%",
        fiscal_year="2025",
        rcept_no="20260301000001",
        account_ids=["ifrs-full_ProfitLoss"],
        source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260301000001",
    )
]


def test_guard_accepts_bound_numbers_and_disclaimer():
    result = guard_llm_output(
        "재무점수 45점 기준으로 보통 수준입니다.",
        "ROE는 3.25%, 부채비율은 142.16%입니다. 본 분석은 투자 권유가 아닙니다.",
        RATIOS,
        EVIDENCE,
        score=45,
    )

    assert result.ok


def test_guard_rejects_altered_number():
    result = guard_llm_output(
        "재무점수 45점 기준입니다.",
        "ROE는 99.9%입니다.",
        RATIOS,
        EVIDENCE,
        score=45,
    )

    assert not result.ok
    assert any("99.9" in violation for violation in result.violations)


def test_guard_allows_common_benchmark_thresholds():
    result = guard_llm_output(
        "부채비율은 100% 기준선을 상회합니다.",
        "ROE는 3.25%입니다.",
        RATIOS,
        EVIDENCE,
        score=45,
    )

    assert result.ok


def test_guard_rejects_investment_language():
    result = guard_llm_output(
        "매수 의견입니다.",
        "목표주가를 제시합니다.",
        RATIOS,
        EVIDENCE,
        score=45,
    )

    assert not result.ok


def test_guard_rejects_unsupported_metric():
    result = guard_llm_output(
        "보통 수준입니다.",
        "PER은 낮은 편입니다.",
        RATIOS,
        EVIDENCE,
        score=45,
    )

    assert not result.ok
    assert "unsupported metric mentioned: PER" in result.violations


def test_guard_allows_shareholder_value_wording():
    result = guard_llm_output(
        "보통 수준입니다.",
        "주주가치 제고 여력은 재무 안정성 회복 속도에 좌우됩니다.",
        RATIOS,
        EVIDENCE,
        score=45,
    )

    assert result.ok


def test_guard_rejects_target_price_expression():
    result = guard_llm_output(
        "보통 수준입니다.",
        "목표주가 10만원을 제시합니다.",
        RATIOS,
        EVIDENCE,
        score=45,
    )

    assert not result.ok
    assert "forbidden investment expression" in result.violations


def test_guard_rejects_per_with_korean_suffix():
    result = guard_llm_output(
        "보통 수준입니다.",
        "PER 10배는 낮은 편입니다.",
        RATIOS,
        EVIDENCE,
        score=45,
    )

    assert not result.ok
    assert "unsupported metric mentioned: PER" in result.violations


def test_guard_allows_percent_point_change_as_derived_expression():
    result = guard_llm_output(
        "보통 수준입니다.",
        "영업이익률은 전년 대비 20%p 상승했습니다.",
        RATIOS,
        EVIDENCE,
        score=45,
    )

    assert result.ok
