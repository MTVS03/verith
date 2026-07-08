"""Supervisor 입출력 typed 계약 (schema-first).

Supervisor 는 사용자 질문을 해석하고, 필요 시 backend 종목 정본으로 context 를 보강한 뒤,
**5개 서브에이전트 모두**에 대해 실행용 task envelope 를 생성한다. 자유 텍스트가 아니라 이 모듈의
구조화된 모델로만 결과를 표현한다.

경계: 이 모듈은 backend DB 를 import 하지 않는다. 종목 식별은 resolver HTTP 경계로만 하고,
ticker/corp_code 를 임의로 만들지 않는다(context 의 stock_code 는 resolver 결과에서만 온다).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 5개 에이전트 — 항상 이 고정 순서로 fan-out(누락 없음).
AgentType = Literal["fundamental", "technical", "news", "flow", "industry"]
AGENT_ORDER: tuple[AgentType, ...] = ("fundamental", "technical", "news", "flow", "industry")

# resolver 호출 결과 요약 상태. not_found 와 error(tool-error)·not_attempted 를 절대 섞지 않는다.
ResolutionStatus = Literal[
    "resolved",       # 단일 종목 확정
    "ambiguous",      # 후보 다수 — 단일 확정 아님
    "not_found",      # 정상 200 도메인 결과: 종목 context 없음
    "not_attempted",  # 비종목 질문 등으로 resolver 를 호출하지 않음
    "error",          # tool-error(timeout·연결·5xx) — not_found 와 다르다
]

# resolver 호출이 도구 장애로 실패한 종류(도메인 not_found 와 구분).
ResolverErrorKind = Literal["timeout", "connection", "backend_error", "invalid_response"]

# can_run 판정에 대한 단일 사유 코드(성공/실패 공통). 자유 텍스트가 아니라 코드값으로 표현한다.
ReasonCode = Literal[
    "stock_resolved",       # 종목 확정 → 실행 가능
    "no_stock_required",    # 종목 없이도 실행 가능(news/industry)
    "stock_not_resolved",   # 종목 의존 agent인데 resolve 미시도/미확정
    "stock_ambiguous",      # 종목 후보 다수 → 단일 확정 필요
    "stock_not_found",      # 종목 의존 agent인데 not_found
    "resolver_unavailable", # 종목 의존 agent인데 resolver tool-error
]


class StockContext(BaseModel):
    """agent 에 내려주는 최소 공통 종목 context. 미해결이면 전부 None."""

    model_config = ConfigDict(extra="forbid")

    stock_code: str | None = None
    stock_name: str | None = None
    market: str | None = None


class StockCandidate(BaseModel):
    """ambiguous 시 후보(표시용). matched_text/match_type 등 backend 세부에는 결합하지 않는다."""

    model_config = ConfigDict(extra="forbid")

    stock_code: str
    stock_name: str
    market: str | None = None


class ResolverError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ResolverErrorKind


class Resolution(BaseModel):
    """resolver 사용 여부와 결과. status 로 not_found/not_attempted/error 를 구분한다."""

    model_config = ConfigDict(extra="forbid")

    used_stock_resolver: bool
    status: ResolutionStatus
    stock: StockContext | None = None
    candidates: list[StockCandidate] = Field(default_factory=list)
    error: ResolverError | None = None


class TaskEnvelope(BaseModel):
    """한 agent 실행용 봉투. supervisor 는 자연어 query 와 공통 stock context 까지만 책임진다
    (agent 내부 세부 파라미터는 조립하지 않는다)."""

    model_config = ConfigDict(extra="forbid")

    agent_type: AgentType
    rewritten_query: str
    context: StockContext
    can_run: bool
    reason: ReasonCode


class SupervisorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    request_id: str | None = None
    trace_id: str | None = None


class SupervisorDecision(BaseModel):
    """supervisor 최종 산출. tasks 는 항상 5개(AGENT_ORDER)."""

    model_config = ConfigDict(extra="forbid")

    original_query: str            # 원본 질문 절대 보존
    resolution: Resolution
    tasks: list[TaskEnvelope]
