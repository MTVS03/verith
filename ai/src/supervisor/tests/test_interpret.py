"""질문 해석 + resolve-gate 휴리스틱 테스트."""

from __future__ import annotations

import pytest

from src.supervisor.planning.interpret import Interpretation, interpret


@pytest.mark.parametrize(
    "query",
    [
        "삼성전자 차트 어때?",       # 차트 액션
        "카카오 수급 보여줘",         # 수급 액션
        "LG에너지솔루션 재무 분석해줘",  # 재무 액션
        "005930 지금 어때?",         # 6자리 코드
        "외국인이 삼성전자를 왜 계속 사는 거야?",  # 외국인(수급)
        "삼성전자 어때?",            # 신호 없음 → bare 종목 가정(안전 resolve)
    ],
)
def test_company_queries_should_resolve(query):
    assert interpret(query).should_resolve is True


@pytest.mark.parametrize(
    "query",
    [
        "2차전지 산업 전망 알려줘",   # 산업
        "반도체 업황 어때?",         # 업황
        "오늘 시장 분위기 어때?",     # 시장/분위기
        "코스피 지수 전망",          # 시장
    ],
)
def test_industry_market_queries_skip_resolve(query):
    assert interpret(query).should_resolve is False


def test_injected_classifier_overrides_heuristic():
    class _Always:
        def classify(self, query: str) -> Interpretation:
            return Interpretation(question_kind="general", should_resolve=False)

    # 휴리스틱이라면 resolve 대상이지만, 주입 분류기가 우선한다.
    assert interpret("삼성전자 차트 어때?", classifier=_Always()).should_resolve is False
