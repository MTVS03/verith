"""adapter 매핑 테스트 (fake agent 모듈 주입 — 실 agent·네트워크 없음).

각 agent 모듈을 sys.modules 로 대체해, adapter 가 TaskEnvelope 를 agent 공개 입력으로 어떻게
매핑하는지만 검증한다(agent 내부 로직에 의존하지 않는다). agent 패키지 __init__ 은 전부 비어 있어
leaf 주입이 안전하다.
"""

from __future__ import annotations

import sys
import types

import pytest

from src.supervisor.execution.adapters import (
    AdapterConfigError,
    ExecutionDeps,
    FlowAdapter,
    FundamentalAdapter,
    IndustryAdapter,
    NewsAdapter,
    TechnicalAdapter,
)
from src.supervisor.schemas import AgentType, StockContext, TaskEnvelope


def _task(agent_type: AgentType, *, rewritten="RW", stock_code="005930", stock_name="삼성전자"):
    return TaskEnvelope(
        agent_type=agent_type,
        rewritten_query=rewritten,
        context=StockContext(stock_code=stock_code, stock_name=stock_name, market="KOSPI"),
        can_run=True,
        reason="stock_resolved",
    )


def _inject(monkeypatch, name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, name, mod)
    return mod


def test_news_adapter_maps_question_only(monkeypatch):
    calls: list[str] = []
    _inject(monkeypatch, "src.agents.news.graph",
            run_query=lambda q: calls.append(q) or {"report": True})
    out = NewsAdapter().run(_task("news", rewritten="뉴스질문"), ExecutionDeps())
    assert calls == ["뉴스질문"] and out == {"report": True}


def test_flow_adapter_maps_stock_context(monkeypatch):
    seen: dict = {}

    def _run(query="", stock_name=None, ticker=None, base_date=None):
        seen.update(query=query, stock_name=stock_name, ticker=ticker)
        return "flow-out"

    _inject(monkeypatch, "src.agents.flow.agent", run=_run)
    out = FlowAdapter().run(_task("flow", rewritten="수급질문"), ExecutionDeps())
    assert out == "flow-out"
    assert seen == {"query": "수급질문", "stock_name": "삼성전자", "ticker": "005930"}


def test_technical_adapter_maps_ticker_and_query(monkeypatch):
    captured: dict = {}

    class _Input:
        def __init__(self, **kw):
            captured.update(kw)

    def _run(agent_input, *, llm_client, fetcher=None, trace_id=None,
             trace_sink=None, cache=None, deadline=None):
        captured["llm"] = llm_client
        return "tech-out"

    _inject(monkeypatch, "src.agents.technical.schemas.contracts", TechnicalAgentInput=_Input)
    _inject(monkeypatch, "src.agents.technical.agent", run_technical_agent=_run)
    out = TechnicalAdapter().run(
        _task("technical", rewritten="차트질문"), ExecutionDeps(technical_llm_client="LLM")
    )
    assert out == "tech-out"
    assert captured["ticker"] == "005930" and captured["query"] == "차트질문"
    assert captured["llm"] == "LLM"


def test_technical_adapter_requires_llm_client():
    # llm_client 미주입이면 import 전에 즉시 AdapterConfigError.
    with pytest.raises(AdapterConfigError):
        TechnicalAdapter().run(_task("technical"), ExecutionDeps())


def test_technical_adapter_rejects_out_of_scope_ticker():
    # resolved ≠ technical runnable: BATTERY_TICKERS 밖(삼성전자 005930)은 KIS/OpenAI 이전에
    # OutOfScopeTickerError 로 거절된다(실 네트워크 없음). 현재 MVP 범위 정책 — 버그 아님.
    from src.agents.technical.services.kis_client import OutOfScopeTickerError

    with pytest.raises(OutOfScopeTickerError):
        TechnicalAdapter().run(
            _task("technical", stock_code="005930", stock_name="삼성전자"),
            ExecutionDeps(technical_llm_client=object()),  # 범위 검사가 llm 사용보다 먼저라 dummy 로 충분
        )


def test_fundamental_adapter_maps_ticker_corp_name(monkeypatch):
    captured: dict = {}

    class _Req:
        def __init__(self, **kw):
            captured.update(kw)

    async def _analyze(req, *, use_cache=True):
        captured["use_cache"] = use_cache
        return "fund-out"

    _inject(monkeypatch, "src.agents.fundamental.core.contract", FundamentalRequest=_Req)
    _inject(monkeypatch, "src.agents.fundamental.graph", analyze_fundamental=_analyze)
    out = FundamentalAdapter().run(_task("fundamental"), ExecutionDeps(request_id="rid"))
    assert out == "fund-out"
    assert captured["ticker"] == "005930" and captured["corp_name"] == "삼성전자"
    assert captured["request_id"] == "rid"


def test_industry_adapter_uses_injected_app():
    class _App:
        def __init__(self):
            self.seen = None

        def invoke(self, state):
            self.seen = state
            return {"answer": "산업답"}

    app = _App()
    out = IndustryAdapter().run(
        _task("industry", rewritten="산업질문", stock_code=None, stock_name=None),
        ExecutionDeps(industry_app=app),
    )
    assert out == "산업답" and app.seen == {"question": "산업질문"}
