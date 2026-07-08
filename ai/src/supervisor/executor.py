"""실행 계층 진입점 — SupervisorDecision(tasks[5]) → AgentResult[5].

planning(run_supervisor)과 분리된 execution 층. can_run=true 인 task 만 실제 agent 를 호출하고,
can_run=false 는 호출하지 않고 skipped 로, 호출 실패는 failed 로 격리한다(부분 성공 허용 — 한 agent
실패가 전체를 터뜨리지 않는다). 결과는 항상 5개, AGENT_ORDER 고정 순서.

이번 단계는 **순차 실행**으로 계약·구조를 먼저 안정화한다(병렬화는 후속). backend DB 접근·분석/집계/
랭킹·투자의견 없음. resolve tool-error(planning 층)와 agent execution failure(이 층)는 다른 층이다.
"""

from __future__ import annotations

from collections.abc import Mapping

from src.supervisor.agent_adapters import AgentAdapter, ExecutionDeps, default_adapters
from src.supervisor.execution_schemas import AgentResult, ExecutionError, ExecutionResult
from src.supervisor.schemas import AGENT_ORDER, SupervisorDecision

# 실패 메시지 상한(secret-safe — 짧게, 개행 제거, traceback/raw payload 미노출).
_MESSAGE_MAX = 300


def _safe_message(exc: Exception) -> str:
    return str(exc).replace("\n", " ").strip()[:_MESSAGE_MAX]


def run_tasks(
    decision: SupervisorDecision,
    *,
    adapters: Mapping[str, AgentAdapter] | None = None,
    deps: ExecutionDeps | None = None,
) -> ExecutionResult:
    """5개 task 를 순차 실행해 5개 AgentResult 로 정리한다. planning 산출은 그대로 보존한다."""
    registry = adapters if adapters is not None else default_adapters()
    call_deps = deps if deps is not None else ExecutionDeps()
    by_agent = {t.agent_type: t for t in decision.tasks}

    results: list[AgentResult] = []
    for agent_type in AGENT_ORDER:
        task = by_agent[agent_type]
        snapshot = {
            "agent_type": agent_type,
            "can_run": task.can_run,
            "context": task.context,
            "rewritten_query": task.rewritten_query,
        }

        if not task.can_run:
            # can_run=false 는 절대 agent 를 호출하지 않는다. reason 은 planning 코드 유지.
            results.append(AgentResult(status="skipped", reason=task.reason, **snapshot))
            continue

        adapter = registry.get(agent_type)
        if adapter is None:
            results.append(
                AgentResult(
                    status="failed",
                    reason="execution_failed",
                    error=ExecutionError(type="NoAdapter", message=f"adapter 미등록: {agent_type}"),
                    **snapshot,
                )
            )
            continue

        try:
            output = adapter.run(task, call_deps)
        except Exception as exc:  # noqa: BLE001 — agent 실패 격리(부분 성공 허용)
            results.append(
                AgentResult(
                    status="failed",
                    reason="execution_failed",
                    error=ExecutionError(type=type(exc).__name__, message=_safe_message(exc)),
                    **snapshot,
                )
            )
            continue

        results.append(AgentResult(status="success", reason=task.reason, output=output, **snapshot))

    return ExecutionResult(
        original_query=decision.original_query,
        resolution=decision.resolution,
        tasks=decision.tasks,
        results=results,
    )
