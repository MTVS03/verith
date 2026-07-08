"""Supervisor 진입점 — 질문 해석 + 조건부 종목 resolve + 5개 agent fan-out.

`run_supervisor` 는 사용자 질문을 해석하고, 필요할 때만 backend 종목 정본으로 context 를 보강한 뒤,
**5개 agent 모두**에 대해 실행 가능 여부까지 포함한 task envelope 를 생성한다. 분석·집계·랭킹·투자의견은
하지 않는다(§3). backend DB 를 직접 만지지 않고 resolver 경계(주입)만 쓴다.

deterministic 우선: 판정·템플릿은 규칙 기반이며, resolver 는 주입식이라 테스트에서 실 네트워크가 없다.
"""

from __future__ import annotations

from src.supervisor.interpret import QueryClassifier, interpret
from src.supervisor.policy import context_for, decide
from src.supervisor.resolve_client import ResolveResult, ResolverProtocol, ResolverToolError
from src.supervisor.rewrite import rewrite
from src.supervisor.schemas import (
    AGENT_ORDER,
    Resolution,
    ResolverError,
    SupervisorDecision,
    SupervisorInput,
    TaskEnvelope,
)


def _resolve(query: str, resolver: ResolverProtocol) -> Resolution:
    """resolver 를 호출해 Resolution 으로 매핑. tool-error 는 status='error'(not_found 와 구분)."""
    try:
        result: ResolveResult = resolver.resolve(query)
    except ResolverToolError as exc:
        return Resolution(
            used_stock_resolver=True,
            status="error",
            error=ResolverError(kind=exc.kind),
        )
    return Resolution(
        used_stock_resolver=True,
        status=result.status,
        stock=result.stock if result.status == "resolved" else None,
        candidates=result.candidates,
    )


def run_supervisor(
    inp: SupervisorInput,
    *,
    resolver: ResolverProtocol | None = None,
    classifier: QueryClassifier | None = None,
) -> SupervisorDecision:
    """상위 orchestration. 원본 query 를 보존하고 항상 5개 task 를 반환한다.

    resolver 는 필요할 때만 호출한다(§7.1). resolver=None 이면 resolve 를 시도하지 않는다
    (비종목 경로 또는 resolver 미주입 환경)."""
    original_query = inp.query
    plan = interpret(original_query, classifier=classifier)

    if plan.should_resolve and resolver is not None:
        resolution = _resolve(original_query, resolver)
    else:
        # 비종목 질문이거나 resolver 미주입 → 시도하지 않음(장애 아님).
        resolution = Resolution(used_stock_resolver=False, status="not_attempted")

    context = context_for(resolution)
    tasks: list[TaskEnvelope] = []
    for agent_type in AGENT_ORDER:
        can_run, reason = decide(agent_type, resolution)
        tasks.append(
            TaskEnvelope(
                agent_type=agent_type,
                rewritten_query=rewrite(agent_type, context, original_query),
                context=context,
                can_run=can_run,
                reason=reason,
            )
        )

    return SupervisorDecision(
        original_query=original_query,
        resolution=resolution,
        tasks=tasks,
    )
