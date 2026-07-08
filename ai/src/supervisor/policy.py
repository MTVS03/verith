"""can_run / reason 정책 (결정론 표).

5개 agent 는 항상 task 를 받는다(고정 fan-out). 종목 의존 여부에 따라 실행 가능 판정이 갈린다.
- 종목 의존(technical/fundamental/flow): 단일 종목이 확정(resolved)돼야 실행 가능.
- 종목 선택(news/industry): 종목이 없어도 질문형으로 실행 가능.

**tool-error(status=error)는 not_found 와 다른 reason(resolver_unavailable)으로 내려** 프론트가
"일시적 장애"와 "종목 없음"을 구분할 수 있게 한다.
"""

from __future__ import annotations

from src.supervisor.schemas import AgentType, ReasonCode, Resolution, StockContext

# 종목 축이 사실상 필수인 agent.
STOCK_DEPENDENT: frozenset[AgentType] = frozenset({"technical", "fundamental", "flow"})
# 종목 없이도 질문형으로 실행 가능한 agent.
STOCK_OPTIONAL: frozenset[AgentType] = frozenset({"news", "industry"})

# 종목 의존 agent 가 실행 불가일 때, resolution.status → reason 코드.
_BLOCKED_REASON: dict[str, ReasonCode] = {
    "ambiguous": "stock_ambiguous",
    "not_found": "stock_not_found",
    "not_attempted": "stock_not_resolved",
    "error": "resolver_unavailable",
}


def decide(agent_type: AgentType, resolution: Resolution) -> tuple[bool, ReasonCode]:
    """agent 의 (can_run, reason) 을 결정론적으로 판정한다."""
    if resolution.status == "resolved":
        return True, "stock_resolved"
    if agent_type in STOCK_OPTIONAL:
        return True, "no_stock_required"
    # 종목 의존 agent + 종목 미확정 → 실행 불가, 사유는 status 로 구분(장애 vs 없음 vs 미시도).
    return False, _BLOCKED_REASON[resolution.status]


def context_for(resolution: Resolution) -> StockContext:
    """task context — 확정 종목이 있으면 그 context, 아니면 빈 context(모두 None)."""
    if resolution.status == "resolved" and resolution.stock is not None:
        return resolution.stock
    return StockContext()
