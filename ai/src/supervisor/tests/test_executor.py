"""실행 계층 테스트 (fake adapter, 실 네트워크·실 agent 없음)."""

from __future__ import annotations

from src.supervisor.agent_adapters import ExecutionDeps
from src.supervisor.executor import run_tasks
from src.supervisor.schemas import AGENT_ORDER, SupervisorInput
from src.supervisor.supervisor import run_supervisor
from src.supervisor.tests._fakes import FakeResolver, not_found, resolved


class FakeAdapter:
    def __init__(self, *, output=None, exc: Exception | None = None) -> None:
        self.output = output
        self.exc = exc
        self.calls: list = []

    def run(self, task, deps):
        self.calls.append(task)
        if self.exc is not None:
            raise self.exc
        return self.output


def _all_fake(**overrides):
    reg = {a: FakeAdapter(output=f"{a}-ok") for a in AGENT_ORDER}
    reg.update(overrides)
    return reg


def _resolved_decision(query="삼성전자 차트 어때?"):
    return run_supervisor(SupervisorInput(query=query), resolver=FakeResolver(result=resolved("005930", "삼성전자")))


def _results_by_agent(exec_result):
    return {r.agent_type: r for r in exec_result.results}


def test_five_results_fixed_order_all_success():
    decision = _resolved_decision()
    adapters = _all_fake()
    out = run_tasks(decision, adapters=adapters)
    assert [r.agent_type for r in out.results] == list(AGENT_ORDER)   # 고정 순서
    for r in out.results:
        assert r.status == "success" and r.output == f"{r.agent_type}-ok"


def test_can_run_false_is_skipped_without_calling_agent():
    # not_found → technical/fundamental/flow skipped, news/industry 실행.
    decision = run_supervisor(SupervisorInput(query="삼성전자 수급 보여줘"), resolver=FakeResolver(result=not_found()))
    adapters = _all_fake()
    out = run_tasks(decision, adapters=adapters)
    by = _results_by_agent(out)
    for a in ("technical", "fundamental", "flow"):
        assert by[a].status == "skipped" and by[a].reason == "stock_not_found"
        assert adapters[a].calls == []                                # 절대 호출 안 함
    for a in ("news", "industry"):
        assert by[a].status == "success" and adapters[a].calls        # 정상 호출


def test_one_agent_failure_does_not_break_others():
    decision = _resolved_decision()
    boom = FakeAdapter(exc=RuntimeError("technical boom"))
    out = run_tasks(decision, adapters=_all_fake(technical=boom))
    by = _results_by_agent(out)
    assert by["technical"].status == "failed"
    assert by["technical"].reason == "execution_failed"
    assert by["technical"].error.type == "RuntimeError"
    assert "technical boom" in by["technical"].error.message
    for a in ("fundamental", "news", "flow", "industry"):
        assert by[a].status == "success"                              # 부분 성공 허용


def test_failure_message_is_secret_safe():
    decision = _resolved_decision()
    leaky = FakeAdapter(exc=RuntimeError("line1\nSECRET=abcdef\n" + "x" * 500))
    out = run_tasks(decision, adapters=_all_fake(technical=leaky))
    msg = _results_by_agent(out)["technical"].error.message
    assert "\n" not in msg and len(msg) <= 300                        # 개행 제거·길이 상한


def test_envelope_preserves_planning_output():
    decision = _resolved_decision()
    out = run_tasks(decision, adapters=_all_fake())
    assert out.original_query == decision.original_query
    assert out.resolution is decision.resolution
    assert out.tasks is decision.tasks
    assert len(out.results) == 5


def test_result_snapshots_task_context_and_query():
    decision = _resolved_decision()
    out = run_tasks(decision, adapters=_all_fake())
    by_task = {t.agent_type: t for t in decision.tasks}
    for r in out.results:
        t = by_task[r.agent_type]
        assert r.rewritten_query == t.rewritten_query
        assert r.context == t.context
        assert r.can_run == t.can_run


def test_non_stock_query_runs_only_optional_agents():
    decision = run_supervisor(SupervisorInput(query="2차전지 산업 전망 알려줘"), resolver=None)
    adapters = _all_fake()
    out = run_tasks(decision, adapters=adapters)
    by = _results_by_agent(out)
    assert by["news"].status == "success" and by["industry"].status == "success"
    for a in ("technical", "fundamental", "flow"):
        assert by[a].status == "skipped" and adapters[a].calls == []


def test_missing_adapter_is_failed_not_crash():
    decision = _resolved_decision()
    partial = {a: FakeAdapter(output="ok") for a in AGENT_ORDER if a != "flow"}
    out = run_tasks(decision, adapters=partial)
    flow = _results_by_agent(out)["flow"]
    assert flow.status == "failed" and flow.error.type == "NoAdapter"


def test_deps_passed_through_to_adapter():
    decision = _resolved_decision()
    seen = {}

    class RecordingAdapter:
        def run(self, task, deps):
            seen["rid"] = deps.rid()
            return "ok"

    run_tasks(decision, adapters=_all_fake(technical=RecordingAdapter()),
              deps=ExecutionDeps(request_id="req-123"))
    assert seen["rid"] == "req-123"
