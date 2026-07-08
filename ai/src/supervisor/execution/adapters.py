"""agent adapter — TaskEnvelope → 각 agent 공개 진입점 매핑 (얇게).

원칙(§adapter): TaskEnvelope 를 해당 agent 공개 입력으로 매핑 → 호출 → 결과 반환. **그 외 금지**
(내부 계산 재구현·query 재해석·ticker/corp_code 생성·backend 조회·임의 fallback 분석). agent 별 공개
입력 차이는 여기서만 최소 흡수한다. agent 모듈 import 는 run() 안에서 지연 로딩(무거운 의존성·순환
방지, 테스트 monkeypatch 용이).

경계: corp_code 를 만들지 않는다. fundamental 이 corp_code 를 후속에서 해결한다(이 계층은 ticker만 전달).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from src.supervisor.schemas import AgentType, TaskEnvelope


class AdapterConfigError(RuntimeError):
    """adapter 실행에 필요한 의존성이 주입되지 않음(예: technical llm_client)."""


@dataclass
class ExecutionDeps:
    """각 agent 호출에 필요한 최소 의존성. 실행 계층이 주입한다(하드코딩·전역 생성 금지)."""

    technical_llm_client: Any = None
    technical_fetcher: Any = None
    technical_cache: Any = None          # Redis OHLCV 캐시(선택)
    technical_trace_sink: Any = None     # trace sink(선택)
    technical_deadline: Any = None       # technical 내부 예산(선택) — 상위 deadline 은 후속
    fundamental_use_cache: bool = True
    industry_graph: Any = None       # 미주입 시 adapter 가 build
    industry_app: Any = None         # 미리 컴파일된 그래프 주입(테스트/재사용)
    request_id: str | None = None
    trace_id: str | None = None
    now: datetime | None = None      # technical as_of 등 결정성 주입점

    def rid(self) -> str:
        return self.request_id or "supervisor-exec"

    def tid(self) -> str:
        return self.trace_id or "supervisor-exec"

    def as_of(self) -> datetime:
        return self.now or datetime.now(UTC)


class AgentAdapter(Protocol):
    """실행 계층이 의존하는 최소 경계. 성공 시 agent 원출력 반환, 실패 시 예외."""

    def run(self, task: TaskEnvelope, deps: ExecutionDeps) -> Any:
        ...


class TechnicalAdapter:
    """technical 공개 진입: ticker + query (llm_client 필요)."""

    def run(self, task: TaskEnvelope, deps: ExecutionDeps) -> Any:
        if deps.technical_llm_client is None:
            raise AdapterConfigError("technical adapter: llm_client 미주입")
        from src.agents.technical.agent import run_technical_agent
        from src.agents.technical.schemas.contracts import TechnicalAgentInput

        agent_input = TechnicalAgentInput(
            ticker=task.context.stock_code,
            query=task.rewritten_query,
            request_id=deps.rid(),
            as_of=deps.as_of(),
        )
        return run_technical_agent(
            agent_input,
            llm_client=deps.technical_llm_client,
            fetcher=deps.technical_fetcher,
            trace_id=deps.tid(),
            trace_sink=deps.technical_trace_sink,
            cache=deps.technical_cache,
            deadline=deps.technical_deadline,
        )


class FundamentalAdapter:
    """fundamental 공개 진입: ticker + query — 비동기 그래프. 세부 파라미터는 agent가 해석한다."""

    def run(self, task: TaskEnvelope, deps: ExecutionDeps) -> Any:
        import asyncio

        from src.agents.fundamental.core.contract import FundamentalAgentInput
        from src.agents.fundamental.graph import analyze_fundamental_public

        public_input = FundamentalAgentInput(
            request_id=deps.rid(),
            trace_id=deps.tid(),
            ticker=task.context.stock_code,
            query=task.rewritten_query,
        )
        return asyncio.run(analyze_fundamental_public(public_input, use_cache=deps.fundamental_use_cache))


class FlowAdapter:
    """flow 공개 진입: stock context(stock_name/ticker) + query. base_date 등은 flow 내부 책임."""

    def run(self, task: TaskEnvelope, deps: ExecutionDeps) -> Any:
        from src.agents.flow.agent import run as flow_run

        return flow_run(
            query=task.rewritten_query,
            stock_name=task.context.stock_name,
            ticker=task.context.stock_code,
        )


class NewsAdapter:
    """news 공개 진입: question 하나. 종목 context 는 보조일 뿐 필수 아님."""

    def run(self, task: TaskEnvelope, deps: ExecutionDeps) -> Any:
        from src.agents.news.graph import run_query

        return run_query(task.rewritten_query)


class IndustryAdapter:
    """industry 공개 진입: question 하나(Neo4j 그래프 필요). app/graph 주입 가능."""

    def run(self, task: TaskEnvelope, deps: ExecutionDeps) -> Any:
        question = {"question": task.rewritten_query}
        if deps.industry_app is not None:
            return deps.industry_app.invoke(question).get("answer")

        from src.agents.industry.agent import build_agent
        from src.agents.industry.config import get_neo4j_graph

        graph = deps.industry_graph or get_neo4j_graph()
        try:
            app = build_agent(graph)
            final = app.invoke(question)
            return final.get("answer")
        finally:
            if deps.industry_graph is None:  # 우리가 만든 그래프만 닫는다.
                graph.close()


def default_adapters() -> dict[AgentType, AgentAdapter]:
    """실사용 기본 adapter 레지스트리(5개). 테스트는 fake 로 교체 주입한다."""
    return {
        "fundamental": FundamentalAdapter(),
        "technical": TechnicalAdapter(),
        "news": NewsAdapter(),
        "flow": FlowAdapter(),
        "industry": IndustryAdapter(),
    }
