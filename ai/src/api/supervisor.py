"""상위 Supervisor 내부 HTTP endpoint.

**내부 전용** — `/internal` prefix(technical endpoint 관례). 외부(backend/내부 테스트)가 supervisor 를
HTTP 로 호출한다. endpoint 는 **orchestration 만** 한다: 입력 검증 → request_id/trace_id/as_of 수용·생성
→ deps(resolver·llm·fetcher·cache·trace_sink) 주입 → 기존 `run_analysis`(planning+execution) 호출 →
JSON 직렬화. 질문 해석·stock resolve·agent adapter 를 여기서 재구현하지 않는다.

동기 실행 계층(run_tasks; fundamental adapter 는 내부적으로 asyncio.run)을 `run_in_threadpool` 로
돌려 event loop 를 막지 않고 running-loop 충돌도 피한다. 상위 전체 deadline·병렬화는 후속(설계만).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from src.api.dependencies import (
    LlmClientFactory,
    get_adapters,
    get_cache,
    get_fetcher,
    get_llm_client,
    get_resolver,
    get_trace_sink,
)
from src.api.errors import AppError
from src.supervisor.execution.adapters import AgentAdapter, ExecutionDeps
from src.supervisor.planning.resolve_client import ResolverProtocol
from src.supervisor.runtime import run_analysis, to_response_dict
from src.supervisor.schemas import SupervisorInput

router = APIRouter(prefix="/internal/supervisor", tags=["supervisor-internal"])

_SERVICE_VERSION = "0.1.0"


class SupervisorAnalyzeRequest(BaseModel):
    """상위 supervisor 요청. 원문 query 는 보존된다. request_id/trace_id/as_of 는 선택(없으면 생성)."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=300)
    request_id: str | None = None
    trace_id: str | None = None
    as_of: datetime | None = None


@router.get("/health")
def health() -> dict[str, str]:
    """router liveness — 실 연결(backend/OpenAI/KIS) 검사 없음, 네트워크 호출 없음."""
    return {"status": "ok", "service": "supervisor", "version": _SERVICE_VERSION}


def _gen_id() -> str:
    return uuid.uuid4().hex


@router.post("/analyze")
async def analyze(
    body: SupervisorAnalyzeRequest,
    make_llm: LlmClientFactory = Depends(get_llm_client),
    fetcher=Depends(get_fetcher),
    cache=Depends(get_cache),
    trace_sink=Depends(get_trace_sink),
    resolver: ResolverProtocol = Depends(get_resolver),
    adapters: dict[str, AgentAdapter] = Depends(get_adapters),
) -> dict:
    """planning + execution 을 한 번 흘려 5 tasks / 5 results 를 반환한다.

    request_id/trace_id 는 요청 값이 있으면 그대로, 없으면 여기서 생성한다(더 이상 adapter 내부 임시
    fallback 에 의존하지 않는다). as_of 는 요청 값 또는 현재 UTC 시각. 이 값들을 ExecutionDeps 로
    명시 주입한다 — adapter 는 의존성을 만들지 않고 받기만 한다.
    """
    request_id = body.request_id or _gen_id()
    trace_id = body.trace_id or _gen_id()
    as_of = body.as_of or datetime.now(UTC)

    # technical llm_client 는 endpoint(dependency 계층)가 만든다. config 오류(502)면 None 으로 두어
    # technical 만 실패 격리되고 나머지 agent 는 계속 진행한다(부분 성공).
    try:
        llm_client = make_llm(None)
    except AppError:
        llm_client = None

    deps = ExecutionDeps(
        technical_llm_client=llm_client,
        technical_fetcher=fetcher,
        technical_cache=cache,
        technical_trace_sink=trace_sink,
        request_id=request_id,
        trace_id=trace_id,
        now=as_of,
    )
    inp = SupervisorInput(query=body.query, request_id=request_id, trace_id=trace_id)

    execution = await run_in_threadpool(
        run_analysis, inp, resolver=resolver, adapters=adapters, deps=deps
    )
    response = to_response_dict(execution)
    response["request_id"] = request_id
    response["trace_id"] = trace_id
    response["as_of"] = as_of.isoformat()
    return response
