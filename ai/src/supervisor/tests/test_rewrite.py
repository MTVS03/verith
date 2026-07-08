"""rewritten_query 템플릿 테스트."""

from __future__ import annotations

from src.supervisor.planning.rewrite import rewrite
from src.supervisor.schemas import AGENT_ORDER, StockContext


def test_stock_form_uses_name_and_is_distinct():
    ctx = StockContext(stock_code="051910", stock_name="LG화학", market="KOSPI")
    texts = {a: rewrite(a, ctx, "LG화학 어때?") for a in AGENT_ORDER}
    assert len(set(texts.values())) == 5
    for t in texts.values():
        assert "LG화학" in t


def test_no_stock_dependent_generic_form():
    empty = StockContext()
    assert rewrite("fundamental", empty, "무언가") == "사용자 질문을 재무(실적·수익성·안정성·밸류에이션) 관점에서 분석해줘."
    assert "기술적" in rewrite("technical", empty, "무언가")
    assert "수급" in rewrite("flow", empty, "무언가")


def test_no_stock_optional_preserves_original_query():
    empty = StockContext()
    q = "2차전지 산업 전망 알려줘"
    assert q in rewrite("news", empty, q)
    assert q in rewrite("industry", empty, q)
