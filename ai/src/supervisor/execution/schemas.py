"""실행 계층 result envelope (dataclass — agent 출력은 이종이라 pydantic 대신 Any 보관).

planning(run_supervisor)이 만든 5개 TaskEnvelope 를 실제 실행한 뒤, **항상 5개 고정 순서**의
AgentResult 로 정리한다. 프론트/상위 계층이 5카드를 동일 구조로 렌더할 수 있게 한다.

status 3종:
- success: agent 호출 성공(output 보유)
- skipped: can_run=false 라 호출하지 않음(reason=planning reason 코드)
- failed: 호출했으나 예외로 실패(error 구조화, secret-safe). resolve tool-error 와는 다른 층이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from src.supervisor.schemas import AgentType, Resolution, StockContext, TaskEnvelope

ExecutionStatus = Literal["success", "skipped", "failed"]


@dataclass
class ExecutionError:
    """실행 실패의 구조화 표현. traceback·raw payload 는 담지 않는다(secret-safe)."""

    type: str
    message: str


@dataclass
class AgentResult:
    agent_type: AgentType
    status: ExecutionStatus
    reason: str                 # planning reason 코드(success/skipped) 또는 실행 코드(failed)
    can_run: bool               # planning 판정 스냅샷
    context: StockContext       # task 스냅샷
    rewritten_query: str        # task 스냅샷
    output: Any = None          # success 시 agent 원출력(이종)
    error: ExecutionError | None = None  # failed 시


@dataclass
class ExecutionResult:
    """실행 계층 최종 산출. planning 산출(original_query/resolution/tasks)을 그대로 보존하고
    results 는 항상 5개(AGENT_ORDER 순서)."""

    original_query: str
    resolution: Resolution
    tasks: list[TaskEnvelope]
    results: list[AgentResult]
