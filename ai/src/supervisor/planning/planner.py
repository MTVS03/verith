"""Supervisor 진입점 — 질문 해석 + 조건부 종목 resolve + 5개 agent fan-out.

`run_supervisor` 는 사용자 질문을 해석하고, 필요할 때만 backend 종목 정본으로 context 를 보강한 뒤,
**5개 agent 모두**에 대해 실행 가능 여부까지 포함한 task envelope 를 생성한다. 분석·집계·랭킹·투자의견은
하지 않는다(§3). backend DB 를 직접 만지지 않고 resolver 경계(주입)만 쓴다.

deterministic 우선: 판정·템플릿은 규칙 기반이며, resolver 는 주입식이라 테스트에서 실 네트워크가 없다.
"""

from __future__ import annotations

from src.supervisor.planning.fallback_lookup import (
    FallbackLookupError,
    FallbackLookupProtocol,
    FallbackResult,
    _normalize,
)
from src.supervisor.planning.fallback_observer import (
    FallbackEvent,
    FallbackObserver,
    NullFallbackObserver,
)
from src.supervisor.planning.interpret import QueryClassifier, interpret
from src.supervisor.planning.policy import context_for, decide
from src.supervisor.planning.resolve_client import ResolveResult, ResolverProtocol, ResolverToolError
from src.supervisor.planning.rewrite import rewrite
from src.supervisor.schemas import (
    AGENT_ORDER,
    Resolution,
    ResolverError,
    StockContext,
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


def _emit_fallback_event(
    observer: FallbackObserver,
    query: str,
    status: str,
    result: FallbackResult | None,
) -> None:
    """fallback 시도 1건을 관측자에 기록(secret-safe — raw query 아님, 길이만)."""
    meta = result.meta if result is not None else None
    observer.record(
        FallbackEvent(
            attempted=True,
            final_status=status,  # type: ignore[arg-type]  # ResolutionStatus 부분집합
            final_source=(meta.final_source if meta else None),
            source_hits=(dict(meta.source_hits) if meta else {}),
            match_types=(list(meta.match_types) if meta else []),
            candidate_count=(len(result.candidates) if result is not None else 0),
            query_len=len(query),
            query_norm_len=len(_normalize(query)),
        )
    )


def _apply_fallback(
    query: str, fallback: FallbackLookupProtocol, observer: FallbackObserver
) -> Resolution:
    """canonical not_found 일 때만 호출되는 보조 경로. **ephemeral resolve 만, persistent write 절대 없음.**

    - high-confidence 단일 → status=resolved + persisted=False ephemeral stock(source=fallback_lookup).
    - 후보 다수 → ambiguous(자동선택 금지). stock 없음.
    - 그 외/도구 장애 → not_found 유지(canonical 결과를 error 로 바꾸지 않는다).
    어느 경우든 used_fallback_lookup=True(시도했음) 로 표기하고, 관측 event 1건을 남긴다."""
    try:
        result: FallbackResult = fallback.lookup(query)
    except FallbackLookupError:
        # fallback 은 보조 — 실패해도 canonical not_found 를 유지한다(장애로 승격하지 않음).
        _emit_fallback_event(observer, query, "not_found", None)
        return Resolution(used_stock_resolver=True, used_fallback_lookup=True, status="not_found")

    if result.status == "resolved" and result.stock is not None:
        # 이번 요청용 임시 context — persisted=False 로 정본 승격을 금지한다(agent 전달은 허용).
        ephemeral = StockContext(
            stock_code=result.stock.stock_code,
            stock_name=result.stock.stock_name,
            market=result.stock.market,
            source="fallback_lookup",
            persisted=False,
        )
        resolution = Resolution(
            used_stock_resolver=True,
            used_fallback_lookup=True,
            status="resolved",
            stock=ephemeral,
            source="fallback_lookup",
            persisted=False,
        )
    elif result.status == "ambiguous" and result.candidates:
        # 후보가 여럿이면 임의 선택하지 않는다(정답 모르면 ambiguous 유지).
        resolution = Resolution(
            used_stock_resolver=True,
            used_fallback_lookup=True,
            status="ambiguous",
            candidates=result.candidates,
            source="fallback_lookup",
        )
    else:
        resolution = Resolution(used_stock_resolver=True, used_fallback_lookup=True, status="not_found")

    _emit_fallback_event(observer, query, resolution.status, result)
    return resolution


def run_supervisor(
    inp: SupervisorInput,
    *,
    resolver: ResolverProtocol | None = None,
    fallback: FallbackLookupProtocol | None = None,
    observer: FallbackObserver | None = None,
    classifier: QueryClassifier | None = None,
) -> SupervisorDecision:
    """상위 orchestration. 원본 query 를 보존하고 항상 5개 task 를 반환한다.

    resolver 는 필요할 때만 호출한다(§7.1). resolver=None 이면 resolve 를 시도하지 않는다
    (비종목 경로 또는 resolver 미주입 환경).

    fallback lookup 은 **canonical resolver 가 not_found 일 때만** 보조로 시도한다(주입식, 미주입이면
    건너뜀). resolved/ambiguous/error/not_attempted 에서는 자동으로 타지 않는다 — fallback 은 canonical 을
    대체하지 않는 보조 경로다. 결과는 항상 persisted=False ephemeral(정본 승격 금지)."""
    original_query = inp.query
    plan = interpret(original_query, classifier=classifier)

    if plan.should_resolve and resolver is not None:
        resolution = _resolve(original_query, resolver)
        # canonical not_found 일 때만 보조 lookup(대체 아님, 보조).
        if resolution.status == "not_found" and fallback is not None:
            resolution = _apply_fallback(original_query, fallback, observer or NullFallbackObserver())
    else:
        # 비종목 질문이거나 resolver 미주입 → 시도하지 않음(장애 아님). fallback 도 타지 않음.
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
