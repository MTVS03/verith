"""테스트용 fake resolver / fallback lookup (실 네트워크 없음)."""

from __future__ import annotations

from src.supervisor.planning.fallback_lookup import (
    FallbackLookupError,
    FallbackResult,
)
from src.supervisor.planning.resolve_client import ResolveResult, ResolverToolError
from src.supervisor.schemas import ResolverErrorKind, StockCandidate, StockContext


class FakeResolver:
    """미리 지정한 결과를 돌려주거나 tool-error 를 던진다. 호출 여부/횟수를 기록한다."""

    def __init__(
        self,
        *,
        result: ResolveResult | None = None,
        raise_kind: ResolverErrorKind | None = None,
    ) -> None:
        self._result = result
        self._raise_kind = raise_kind
        self.calls: list[str] = []

    def resolve(self, query: str) -> ResolveResult:
        self.calls.append(query)
        if self._raise_kind is not None:
            raise ResolverToolError(self._raise_kind, "fake tool error")
        assert self._result is not None, "FakeResolver 에 result 또는 raise_kind 를 줘야 함"
        return self._result


def resolved(stock_code: str, stock_name: str, market: str | None = "KOSPI") -> ResolveResult:
    return ResolveResult(
        status="resolved",
        stock=StockContext(stock_code=stock_code, stock_name=stock_name, market=market),
    )


def not_found() -> ResolveResult:
    return ResolveResult(status="not_found")


def ambiguous(*codes: tuple[str, str]) -> ResolveResult:
    return ResolveResult(
        status="ambiguous",
        candidates=[StockCandidate(stock_code=c, stock_name=n) for c, n in codes],
    )


class FakeFallback:
    """미리 지정한 FallbackResult 를 돌려주거나 FallbackLookupError 를 던진다. 호출 여부를 기록한다."""

    def __init__(
        self,
        *,
        result: FallbackResult | None = None,
        raise_error: bool = False,
    ) -> None:
        self._result = result
        self._raise_error = raise_error
        self.calls: list[str] = []

    def lookup(self, query: str) -> FallbackResult:
        self.calls.append(query)
        if self._raise_error:
            raise FallbackLookupError("fake fallback tool error")
        assert self._result is not None, "FakeFallback 에 result 또는 raise_error 를 줘야 함"
        return self._result


def fb_resolved(stock_code: str, stock_name: str, market: str | None = "KOSPI") -> FallbackResult:
    return FallbackResult(
        status="resolved",
        stock=StockContext(stock_code=stock_code, stock_name=stock_name, market=market),
    )


def fb_not_found() -> FallbackResult:
    return FallbackResult(status="not_found")


def fb_ambiguous(*codes: tuple[str, str]) -> FallbackResult:
    return FallbackResult(
        status="ambiguous",
        candidates=[StockCandidate(stock_code=c, stock_name=n) for c, n in codes],
    )
