"""종목 정본 경계 client — backend `POST /api/stocks/resolve` (HTTP 전용).

AI supervisor 는 backend DB 를 직접 만지지 않는다. 종목 식별은 이 client 를 통해서만 한다.
핵심 계약: **tool-error(timeout·연결·5xx·형식오류)는 도메인 not_found 와 절대 섞지 않는다.**
- 정상 200(resolved/ambiguous/not_found) → `ResolveResult` 반환.
- 빈 query 422 → 도메인 not_found 로 취급(장애 아님).
- timeout/연결/5xx/파싱실패 → `ResolverToolError`(kind) 로 올림 → supervisor 가 status="error" 로 매핑.

테스트는 실 네트워크 대신 `httpx.MockTransport` 또는 fake resolver 를 주입한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx

from src.supervisor.config import BACKEND_BASE_URL, RESOLVER_PATH, RESOLVER_TIMEOUT, USER_AGENT
from src.supervisor.schemas import ResolverErrorKind, StockCandidate, StockContext

# resolver 도메인 결과(성공 응답). tool-error 는 여기 들어오지 않고 예외로 분리된다.
ResolveStatus = Literal["resolved", "ambiguous", "not_found"]


class ResolverToolError(RuntimeError):
    """resolver 호출 자체가 실패(도구 장애). not_found(정상 도메인 결과)와 구분하기 위한 예외."""

    def __init__(self, kind: ResolverErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind: ResolverErrorKind = kind


@dataclass
class ResolveResult:
    status: ResolveStatus
    stock: StockContext | None = None
    candidates: list[StockCandidate] = field(default_factory=list)


class ResolverProtocol(Protocol):
    """supervisor 가 의존하는 최소 경계. 실제 client 나 fake 모두 이 시그니처를 따른다."""

    def resolve(self, query: str) -> ResolveResult:
        """도메인 결과 반환. 도구 장애면 ResolverToolError 를 던진다."""
        ...


def _parse_ok(body: object) -> ResolveResult:
    """backend 200 응답 body → ResolveResult. 형식이 어긋나면 invalid_response tool-error."""
    if not isinstance(body, dict):
        raise ResolverToolError("invalid_response", "resolver 응답이 object 가 아님")
    status = body.get("status")
    if status not in ("resolved", "ambiguous", "not_found"):
        raise ResolverToolError("invalid_response", "resolver status 값이 계약 밖")

    stock: StockContext | None = None
    raw_stock = body.get("stock")
    if status == "resolved":
        if not isinstance(raw_stock, dict) or not raw_stock.get("stock_code"):
            raise ResolverToolError("invalid_response", "resolved 인데 stock 이 없음")
        stock = StockContext(
            stock_code=str(raw_stock["stock_code"]),
            stock_name=raw_stock.get("stock_name"),
            market=raw_stock.get("market"),
        )

    candidates: list[StockCandidate] = []
    for cand in body.get("candidates") or []:
        if isinstance(cand, dict) and cand.get("stock_code"):
            candidates.append(
                StockCandidate(
                    stock_code=str(cand["stock_code"]),
                    stock_name=str(cand.get("stock_name") or ""),
                    market=cand.get("market"),
                )
            )
    return ResolveResult(status=status, stock=stock, candidates=candidates)


class StockResolverClient:
    """BACKEND_BASE_URL 기준으로 resolve 를 한 번 호출한다(호출당 client 생성). 실 네트워크 — 수동/런타임."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float | None = None,
        path: str | None = None,
    ) -> None:
        self._base_url = (base_url or BACKEND_BASE_URL).rstrip("/")
        self._timeout = timeout if timeout is not None else RESOLVER_TIMEOUT
        self._path = path or RESOLVER_PATH
        # 테스트가 MockTransport 를 주입할 수 있도록 transport 를 열어둔다(실 네트워크 회피).
        self._transport: httpx.BaseTransport | None = None

    def with_transport(self, transport: httpx.BaseTransport) -> StockResolverClient:
        """테스트 훅 — httpx.MockTransport 주입."""
        self._transport = transport
        return self

    def resolve(self, query: str) -> ResolveResult:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        try:
            with httpx.Client(
                base_url=self._base_url, timeout=self._timeout, transport=self._transport
            ) as client:
                resp = client.post(self._path, json={"query": query}, headers=headers)
        except httpx.TimeoutException as exc:
            raise ResolverToolError("timeout", "resolver timeout") from exc
        except httpx.HTTPError as exc:  # 연결 실패 등 전송 오류
            raise ResolverToolError("connection", "resolver 연결 실패") from exc

        status = resp.status_code
        if status == 422:
            # 빈 query 정규화 — 종목 context 없음(도메인 not_found), 장애 아님.
            return ResolveResult(status="not_found")
        if status >= 500:
            raise ResolverToolError("backend_error", f"resolver 5xx({status})")
        if status >= 400:
            raise ResolverToolError("backend_error", f"resolver 4xx({status})")
        try:
            body = resp.json()
        except ValueError as exc:
            raise ResolverToolError("invalid_response", "resolver JSON 파싱 실패") from exc
        return _parse_ok(body)
