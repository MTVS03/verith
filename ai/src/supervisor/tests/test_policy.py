"""can_run/reason 결정 표 테스트."""

from __future__ import annotations

import pytest

from src.supervisor.planning.policy import STOCK_DEPENDENT, STOCK_OPTIONAL, context_for, decide
from src.supervisor.schemas import AGENT_ORDER, Resolution, ResolverError, StockContext


def _res(status, **kw):
    return Resolution(used_stock_resolver=True, status=status, **kw)


def test_resolved_all_agents_runnable():
    r = _res("resolved", stock=StockContext(stock_code="005930", stock_name="삼성전자", market="KOSPI"))
    for a in AGENT_ORDER:
        can, reason = decide(a, r)
        assert can is True and reason == "stock_resolved"


@pytest.mark.parametrize(
    "status,expected_reason",
    [
        ("not_attempted", "stock_not_resolved"),
        ("not_found", "stock_not_found"),
        ("ambiguous", "stock_ambiguous"),
        ("error", "resolver_unavailable"),
    ],
)
def test_stock_dependent_blocked_reasons(status, expected_reason):
    extra = {"error": ResolverError(kind="timeout")} if status == "error" else {}
    r = _res(status, **extra)
    for a in STOCK_DEPENDENT:
        can, reason = decide(a, r)
        assert can is False and reason == expected_reason
    for a in STOCK_OPTIONAL:
        can, reason = decide(a, r)
        assert can is True and reason == "no_stock_required"


def test_partition_covers_all_agents_without_overlap():
    assert STOCK_DEPENDENT | STOCK_OPTIONAL == set(AGENT_ORDER)
    assert STOCK_DEPENDENT & STOCK_OPTIONAL == set()


def test_context_for_empty_when_not_resolved():
    assert context_for(_res("not_found")).stock_code is None
    r = _res("resolved", stock=StockContext(stock_code="005930", stock_name="삼성전자"))
    assert context_for(r).stock_code == "005930"
