from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from .state import FundamentalAgentState

NodeResult = dict[str, Any]
NodeCallable = Callable[[FundamentalAgentState], NodeResult | Awaitable[NodeResult]]


@contextmanager
def node_span(_name: str) -> Iterator[None]:
    yield


def _span_record(name: str, started_at: datetime, started: float, status: str, error: BaseException | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "name": name,
        "started_at": started_at.isoformat(),
        "duration_ms": round((perf_counter() - started) * 1000, 2),
        "status": status,
    }
    if error is not None:
        record["error_type"] = type(error).__name__
    return record


class NodeExecutionError(RuntimeError):
    def __init__(self, node_name: str, trace: list[dict[str, Any]], original: BaseException) -> None:
        super().__init__(f"{node_name} failed: {type(original).__name__}: {original}")
        self.node_name = node_name
        self.trace = trace
        self.original = original


async def run_traced_node(name: str, node: NodeCallable, state: FundamentalAgentState) -> NodeResult:
    trace = list(state.get("node_trace", []))
    started_at = datetime.now(timezone.utc)
    started = perf_counter()
    try:
        result_or_awaitable = node(state)
        result = await result_or_awaitable if inspect.isawaitable(result_or_awaitable) else result_or_awaitable
    except Exception as exc:
        trace.append(_span_record(name, started_at, started, "error", exc))
        raise NodeExecutionError(name, trace, exc) from exc

    trace.append(_span_record(name, started_at, started, "ok"))
    result = dict(result)
    result["node_trace"] = trace
    meta = result.get("meta")
    response = result.get("response")
    if isinstance(meta, dict):
        meta["node_trace"] = trace
    if response is not None and hasattr(response, "meta") and isinstance(response.meta, dict):
        response.meta["node_trace"] = trace
    return result


def traced_node(name: str, node: NodeCallable) -> Callable[[FundamentalAgentState], Awaitable[NodeResult]]:
    async def _wrapped(state: FundamentalAgentState) -> NodeResult:
        return await run_traced_node(name, node, state)

    return _wrapped
