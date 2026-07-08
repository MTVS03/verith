"""Supervisor runtime 조립 — planning + execution 을 한 번에 흘린다.

`run_analysis` 는 로직을 재구현하지 않고 기존 `run_supervisor()`(planning) → `run_tasks()`(execution)
만 순서대로 호출한다. endpoint/스크립트는 deps·resolver 를 주입하고 이 함수를 부르기만 한다.

`to_response_dict` 는 ExecutionResult 를 JSON-safe dict 로 직렬화한다(agent 출력은 이종 —
pydantic 이면 model_dump, dict/기타는 그대로). HTML·카드 조립은 하지 않는다(상위/프론트 책임).
"""

from __future__ import annotations

from typing import Any

from src.supervisor.execution.adapters import AgentAdapter, ExecutionDeps
from src.supervisor.execution.schemas import AgentResult, ExecutionResult
from src.supervisor.execution.executor import run_tasks
from src.supervisor.planning.fallback_lookup import FallbackLookupProtocol
from src.supervisor.planning.interpret import QueryClassifier
from src.supervisor.planning.resolve_client import ResolverProtocol
from src.supervisor.schemas import SupervisorInput
from src.supervisor.planning.planner import run_supervisor


def run_analysis(
    inp: SupervisorInput,
    *,
    resolver: ResolverProtocol | None = None,
    fallback: FallbackLookupProtocol | None = None,
    adapters: dict[str, AgentAdapter] | None = None,
    deps: ExecutionDeps | None = None,
    classifier: QueryClassifier | None = None,
) -> ExecutionResult:
    """planning → execution. 원본 query 보존, 항상 5 tasks / 5 results.

    fallback 은 canonical resolver not_found 일 때만 planner 가 쓰는 보조 lookup(주입식)."""
    decision = run_supervisor(inp, resolver=resolver, fallback=fallback, classifier=classifier)
    return run_tasks(decision, adapters=adapters, deps=deps)


def _output_json(output: Any) -> Any:
    """agent 원출력 → JSON-safe. pydantic 이면 model_dump(mode=json), 그 외는 그대로 둔다."""
    if output is None:
        return None
    dump = getattr(output, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return output


def _result_json(result: AgentResult) -> dict[str, Any]:
    return {
        "agent_type": result.agent_type,
        "status": result.status,
        "reason": result.reason,
        "can_run": result.can_run,
        "context": result.context.model_dump(),
        "rewritten_query": result.rewritten_query,
        "output": _output_json(result.output) if result.status == "success" else None,
        "error": (
            {"type": result.error.type, "message": result.error.message}
            if result.error is not None
            else None
        ),
    }


def to_response_dict(execution: ExecutionResult) -> dict[str, Any]:
    """endpoint 응답용 JSON-safe dict. tasks·results 는 항상 5개 고정 순서."""
    return {
        "original_query": execution.original_query,
        "resolution": execution.resolution.model_dump(),
        "tasks": [t.model_dump() for t in execution.tasks],
        "results": [_result_json(r) for r in execution.results],
    }
