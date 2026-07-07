import re

from src.agents.fundamental.core.contract import Evidence
from src.agents.fundamental.emit.html_builder import _value_tone_class, build_report_html


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
            display_value="6조 5,000억원",
        )
    ]


def _html(
    audience: str = "user",
    *,
    corp_name: str = "포스코퓨처엠",
    score: int = 47,
    label: str = "moderate",
    interpretation: str = "매출 6조 5,000억원과 임의 숫자 123억원을 함께 점검합니다.",
    verification_summary: dict[str, object] | None = None,
) -> str:
    return build_report_html(
        corp_name=corp_name,
        ticker="003670",
        score=score,
        label=label,
        confidence=0.85,
        ratios={
            "debt_ratio": {
                "label": "부채비율",
                "category": "안정성",
                "value": 102.65,
                "unit": "%",
                "status": "available",
            },
            "operating_income_growth": {
                "label": "영업이익 성장률",
                "category": "성장성",
                "value": None,
                "unit": "%",
                "display_value": "흑자 기조 회복(저기저)",
                "status": "not_meaningful",
                "direction": "low_base",
                "reason": "전기 영업이익이 당기 매출 대비 1% 미만의 낮은 기저라 성장률을 %로 표시하지 않습니다.",
            },
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
        interpretation=interpretation,
        evidence=_evidence(),
        evidence_graph={
            "nodes": [
                {"id": "filing:20260501000001", "type": "filing", "rcept_no": "20260501000001"},
                {"id": "account:revenue", "type": "account", "account_nm": "매출액"},
                {"id": "metric:revenue", "type": "metric", "metric": "revenue", "label": "매출"},
            ],
            "edges": [
                {"from": "filing:20260501000001", "to": "account:revenue", "relation": "contains_account"},
                {"from": "account:revenue", "to": "metric:revenue", "relation": "calculates"},
            ],
        },
        analyst_plan={
            "section_order": ["growth", "stability"],
            "section_briefs": {"growth": "저기저 회복", "stability": "부채비율 점검"},
        },
        risk_flags=["NOT_MEANINGFUL_OPERATING_INCOME_GROWTH"],
        meta={
            "reprt_name": "1분기보고서",
            "llm_provider": "template",
            "llm_guard_violations": [],
            "period_basis": {
                "report_name": "1분기보고서",
                "description": "2026 1Q 1분기보고서 기준",
                "is_interim": True,
            },
            "retrieval_summary": {"financial_network_calls": 1},
            "verification_summary": verification_summary
            if verification_summary is not None
            else {
                "outcome": "passed",
                "binding_passed": True,
                "consistency_passed": True,
                "guard_passed": True,
                "verdict_stable": True,
            },
            "erd_payload": {
                "fundamental_report": {"id": "report-1", "data_status": "partial_with_flags"},
                "report_ratios": [{"ratio_name": "roe"}],
                "report_evidence": [{"account_id": "ifrs-full_Revenue"}],
                "report_verification": {"outcome": "passed"},
            },
        },
        audience=audience,  # type: ignore[arg-type]
    )


def test_build_report_html_user_view_uses_design_system_and_hides_debug_sections():
    html = _html("user")

    assert "class=\"vfr-report\"" in html
    assert "--vfr-bg" in html
    assert "@media (prefers-color-scheme: dark)" in html
    assert "font-variant-numeric:tabular-nums" in html
    assert "Pretendard" in html
    assert "class=\"vfr-gauge vfr-label-moderate\"" in html
    assert "aria-label=\"절대 재무점수 47점, 중립\"" in html
    assert "점수 구성" in html
    assert "데이터 신뢰도" in html
    assert "코드 계산 · 결정론" in html
    assert "LLM 생성 · 근거 연결" in html
    assert "style=" not in html
    assert "data-trend=" not in html
    assert "Analyst Frame" not in html
    assert "DART Source Policy" not in html
    assert "저장 계약" not in html
    assert "Evidence Graph Mermaid" not in html
    assert "흑자 기조 회복(저기저)" in html
    assert "4,451.47%" not in html
    assert "매출·영업이익 추세" in html
    assert "ROE" in html
    assert 'target="_blank" rel="noopener"' in html
    assert "@import" not in html
    assert "<script" not in html.lower()
    assert "fonts.googleapis" not in html


def test_build_report_html_debug_view_includes_score_gauge():
    html = _html("debug")

    assert "class=\"vfr-gauge vfr-label-moderate\"" in html
    assert "aria-label=\"절대 재무점수 47점, 중립\"" in html


def test_score_gauge_needle_does_not_cross_score_text_area():
    # 게이지 바늘이 중앙 텍스트를 관통했던 회귀를 좌표로 고정한다.
    for score in (0, 47, 50, 100):
        html = _html(score=score)
        line = re.search(
            r'<line class="vfr-gauge-needle" x1="(?P<x1>[\d.]+)" y1="(?P<y1>[\d.]+)" x2="(?P<x2>[\d.]+)" y2="(?P<y2>[\d.]+)"',
            html,
        )
        score_text = re.search(r'<text class="vfr-gauge-score vfr-num" x="120" y="(?P<y>[\d.]+)"', html)
        assert line is not None
        assert score_text is not None

        needle_bottom = max(float(line.group("y1")), float(line.group("y2")))
        score_text_top = float(score_text.group("y")) - 34
        assert needle_bottom < score_text_top


def test_insufficient_data_gauge_uses_gray_mode_without_needle():
    html = _html(score=0, label="insufficient_data")

    assert "class=\"vfr-gauge vfr-gauge-insufficient\"" in html
    assert "데이터 제한" in html
    assert '<line class="vfr-gauge-needle"' not in html


def test_interpretation_highlights_only_bound_display_values():
    html = _html()

    assert '<b class="vfr-hl-num">6조 5,000억원</b>' in html
    assert '<b class="vfr-hl-num">123억원</b>' not in html


def test_interpretation_highlighter_does_not_nest_partial_display_tokens():
    # display 토큰이 부분 문자열로 겹쳐도 <b>가 중첩되면 안 된다.
    html = build_report_html(
        corp_name="테스트",
        ticker="000000",
        score=50,
        label="moderate",
        confidence=0.8,
        ratios={
            "revenue": {
                "label": "매출",
                "category": "성장성",
                "value": 650_000_000_000,
                "unit": "원",
                "display_value": "6,500억원",
                "status": "available",
            },
            "short_revenue": {
                "label": "부분 토큰",
                "category": "검증",
                "value": 500,
                "unit": "억원",
                "display_value": "500억원",
                "status": "available",
            },
        },
        trend={"years": [], "revenue": [], "op_income": [], "roe": []},
        interpretation="매출 6,500억원을 확인했습니다.",
        evidence=[],
        risk_flags=[],
    )

    assert '<b class="vfr-hl-num">6,500억원</b>' in html
    assert '<b class="vfr-hl-num">6,<b class="vfr-hl-num">500억원</b></b>' not in html


def test_build_report_html_escapes_dynamic_text_and_keeps_no_raw_script():
    html = _html(
        corp_name='"><img src=x onerror=alert(1)>',
        interpretation='<script>alert(1)</script> 매출 6조 5,000억원',
    )

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert '"><img src=x onerror=alert(1)>' not in html
    assert "&quot;&gt;&lt;img src=x onerror=alert(1)&gt;" in html


def test_evidence_jump_links_match_evidence_card_ids():
    html = _html()

    assert 'href="#vfr-ev-revenue"' in html
    assert 'id="vfr-ev-revenue"' in html


def test_verified_badge_is_shown_only_when_verification_summary_passed():
    passed = _html()
    failed = _html(verification_summary={"outcome": "failed", "guard_passed": False})
    missing = _html(verification_summary={})

    assert "검증됨" in passed
    assert "검증됨" not in failed
    assert "검증됨" not in missing


def test_build_report_html_debug_view_includes_internal_sections_and_mermaid():
    html = _html("debug")

    assert "data-audience=\"debug\"" in html
    assert "내부 검수용 · Verification Gate" in html
    assert "내부 검수용 · DART Source Policy" in html
    assert "내부 검수용 · 저장 계약" in html
    assert "내부 검수용 · Analyst Frame" in html
    assert "내부 검수용 · Evidence Graph Mermaid" in html
    assert "contains_account" in html
    assert "calculates" in html


def test_metric_value_tone_keeps_debt_ratio_102_neutral():
    assert _value_tone_class("debt_ratio", {"value": 102.65, "unit": "%", "status": "available"}) == "vfr-tone-muted"
    assert _value_tone_class("debt_ratio", {"value": 260.0, "unit": "%", "status": "available"}) == "vfr-tone-negative"
    assert _value_tone_class("current_ratio", {"value": 130.0, "unit": "%", "status": "available"}) == "vfr-tone-positive"


def test_growth_metric_tone_uses_korean_market_colors():
    assert _value_tone_class("revenue_growth", {"value": 3.2, "unit": "%", "status": "available"}) == "vfr-tone-up"
    assert _value_tone_class("revenue_growth", {"value": -10.4, "unit": "%", "status": "available"}) == "vfr-tone-down"
