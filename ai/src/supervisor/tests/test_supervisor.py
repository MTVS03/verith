"""Supervisor 조율 진입점 테스트 (fake resolver, 실 네트워크 없음)."""

from __future__ import annotations

from src.supervisor.planning.policy import STOCK_DEPENDENT, STOCK_OPTIONAL
from src.supervisor.schemas import AGENT_ORDER, SupervisorInput
from src.supervisor.planning.planner import run_supervisor
from src.supervisor.tests._fakes import FakeResolver, ambiguous, not_found, resolved


def _tasks_by_agent(decision):
    return {t.agent_type: t for t in decision.tasks}


def test_stock_query_resolves_and_makes_five_tasks():
    resolver = FakeResolver(result=resolved("005930", "삼성전자"))
    decision = run_supervisor(SupervisorInput(query="삼성전자 차트 어때?"), resolver=resolver)

    assert resolver.calls == ["삼성전자 차트 어때?"]         # resolve 수행
    assert decision.resolution.status == "resolved"
    assert len(decision.tasks) == 5
    assert [t.agent_type for t in decision.tasks] == list(AGENT_ORDER)
    for t in decision.tasks:
        assert t.can_run is True and t.reason == "stock_resolved"
        assert t.context.stock_code == "005930" and t.context.stock_name == "삼성전자"


def test_non_stock_query_skips_resolver():
    resolver = FakeResolver(result=resolved("000000", "미사용"))
    decision = run_supervisor(SupervisorInput(query="2차전지 산업 전망 알려줘"), resolver=resolver)

    assert resolver.calls == []                              # resolve 미호출(§7.1)
    assert decision.resolution.used_stock_resolver is False
    assert decision.resolution.status == "not_attempted"
    # 종목 선택 agent 는 실행 가능, 종목 의존 agent 는 불가.
    by = _tasks_by_agent(decision)
    for a in STOCK_OPTIONAL:
        assert by[a].can_run is True and by[a].reason == "no_stock_required"
    for a in STOCK_DEPENDENT:
        assert by[a].can_run is False and by[a].reason == "stock_not_resolved"


def test_not_found_is_not_total_failure_keeps_five_tasks():
    resolver = FakeResolver(result=not_found())
    decision = run_supervisor(SupervisorInput(query="삼성전자 수급 보여줘"), resolver=resolver)

    assert decision.resolution.status == "not_found"
    assert len(decision.tasks) == 5
    by = _tasks_by_agent(decision)
    for a in STOCK_DEPENDENT:
        assert by[a].can_run is False and by[a].reason == "stock_not_found"
    for a in STOCK_OPTIONAL:
        assert by[a].can_run is True and by[a].reason == "no_stock_required"


def test_tool_failure_distinct_from_not_found():
    resolver = FakeResolver(raise_kind="timeout")
    decision = run_supervisor(SupervisorInput(query="삼성전자 재무 분석해줘"), resolver=resolver)

    assert decision.resolution.status == "error"            # not_found 와 구분(§7.3)
    assert decision.resolution.error is not None and decision.resolution.error.kind == "timeout"
    by = _tasks_by_agent(decision)
    for a in STOCK_DEPENDENT:
        assert by[a].can_run is False and by[a].reason == "resolver_unavailable"
    for a in STOCK_OPTIONAL:
        assert by[a].can_run is True


def test_ambiguous_blocks_stock_dependent():
    resolver = FakeResolver(result=ambiguous(("006040", "동원산업"), ("049770", "동원F&B")))
    decision = run_supervisor(SupervisorInput(query="동원 수급 어때?"), resolver=resolver)

    assert decision.resolution.status == "ambiguous"
    assert {c.stock_code for c in decision.resolution.candidates} == {"006040", "049770"}
    by = _tasks_by_agent(decision)
    for a in STOCK_DEPENDENT:
        assert by[a].can_run is False and by[a].reason == "stock_ambiguous"
    for a in STOCK_OPTIONAL:
        assert by[a].can_run is True


def test_original_query_preserved():
    q = "삼성전자 차트상 지금 어때?"
    resolver = FakeResolver(result=resolved("005930", "삼성전자"))
    decision = run_supervisor(SupervisorInput(query=q), resolver=resolver)
    assert decision.original_query == q


def test_per_agent_rewritten_query_distinct_and_named():
    resolver = FakeResolver(result=resolved("051910", "LG화학"))
    decision = run_supervisor(SupervisorInput(query="LG화학 어때?"), resolver=resolver)
    rewrites = {t.agent_type: t.rewritten_query for t in decision.tasks}
    assert len(set(rewrites.values())) == 5                  # 관점별로 서로 다름
    for text in rewrites.values():
        assert "LG화학" in text                              # 종목명 주어 반영


def test_five_agents_always_present_even_without_resolver():
    # resolver 미주입이어도 5개 task 는 유지된다(종목 의존 agent 는 미실행).
    decision = run_supervisor(SupervisorInput(query="삼성전자 차트 어때?"), resolver=None)
    assert [t.agent_type for t in decision.tasks] == list(AGENT_ORDER)
    assert decision.resolution.status == "not_attempted"


def test_non_stock_optional_agent_preserves_topic_in_rewrite():
    decision = run_supervisor(SupervisorInput(query="2차전지 산업 전망 알려줘"), resolver=None)
    by = _tasks_by_agent(decision)
    assert "2차전지 산업 전망 알려줘" in by["industry"].rewritten_query
    assert "2차전지 산업 전망 알려줘" in by["news"].rewritten_query
