"""Stock Resolver API 스키마.

원문 query 는 응답에 되돌려주지 않는다(§7 보안). status/reason 만 제공해 사용자 노출 문구는
Frontend/Chat 계층이 만든다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MatchType = Literal["stock_code", "stock_name", "alias", "ambiguous_group"]
ResolveStatus = Literal["resolved", "ambiguous", "not_found"]
ResolveReason = Literal[
    "exact_match",
    "multiple_stocks",
    "conflicting_identifiers",
    "ambiguous_alias",
    "unknown_identifier",  # 원문에 stocks 에 없는 6자리 코드가 있음(조용히 무시 금지)
    "no_match",
]


class StockResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=300)


class ResolvedStock(BaseModel):
    stock_code: str
    stock_name: str
    market: str | None


class StockCandidate(BaseModel):
    stock_code: str
    stock_name: str
    market: str | None
    matched_text: str
    match_type: MatchType


class StockResolveResponse(BaseModel):
    status: ResolveStatus
    reason: ResolveReason
    stock: ResolvedStock | None = None
    candidates: list[StockCandidate] = Field(default_factory=list)
