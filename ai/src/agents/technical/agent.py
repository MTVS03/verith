"""기술적 분석 에이전트 외부 진입점(얇은 wrapper).

정본: `implementation_plan.md §3`(진입점 2단 분리)·§4. 상위 라우터(`src/ai/api/internal.py`)나
Top Supervisor가 부르는 공식 입구다. **입력 검증 → `technical_supervisor.run` 위임 → 출력 반환**만
하고, 계산·조율·fallback·조립은 전부 `supervisor/technical_supervisor.py`가 맡는다.

경계(technical_coding_guidelines §4.2·§5): node·KIS·LLM·indicator/regime/synthesis/chart를 직접
호출하지 않는다. `llm_client`는 외부 주입만 받는다(OpenAI client 생성·API key·네트워크 코드 없음).
"""

from __future__ import annotations

from typing import Protocol

from .schemas.contracts import TechnicalAgentInput, TechnicalAgentOutput
from .observability.trace_logger import TraceSink
from .supervisor import technical_supervisor
from .supervisor.technical_supervisor import OhlcvFetcher


class LlmClient(Protocol):
    """LLM 호출 경계(구조적 Protocol). 실제 구현은 외부 주입 — agent.py는 client를 만들지 않는다.

    `nodes/_llm_utils`·`interpret_report`의 동일 Protocol을 import하면 계층 경계(§6)가 깨지므로,
    agent.py 안에 최소 정의를 둔다(1메서드 구조 계약이라 어떤 client든 duck-typing으로 호환)."""

    def complete(self, prompt: str) -> str: ...


def run_technical_agent(
    payload: TechnicalAgentInput | dict[str, object],
    *,
    llm_client: LlmClient,
    fetcher: OhlcvFetcher | None = None,
    trace_id: str | None = None,
    trace_sink: TraceSink | None = None,
) -> TechnicalAgentOutput:
    """외부 입력을 검증해 `technical_supervisor.run`에 위임한다.

    payload가 `TechnicalAgentInput`이면 그대로, dict면 `model_validate`로 검증한다(수동 파싱 안 함).
    그 외 타입은 `TypeError`. `fetcher`가 None이면 supervisor 기본 fetcher를 쓰도록 인자를 넘기지
    않는다(얇은 wrapper — 기본값 중복 정의 금지). `llm_client`·`trace_id`는 그대로 전달한다.
    `trace_sink`(선택)도 그대로 전달한다 — agent.py는 sink를 만들지 않고(경로·config 모름) 주입만
    통과시킨다. None이면 supervisor가 Noop으로 동작(기존 동작 불변)."""
    if isinstance(payload, TechnicalAgentInput):
        agent_input = payload
    elif isinstance(payload, dict):
        agent_input = TechnicalAgentInput.model_validate(payload)
    else:
        raise TypeError(
            f"payload는 TechnicalAgentInput 또는 dict여야 합니다: {type(payload).__name__}"
        )

    kwargs = {"llm_client": llm_client, "trace_id": trace_id, "trace_sink": trace_sink}
    if fetcher is not None:  # None이면 supervisor 기본 fetcher 사용(전달 생략)
        kwargs["fetcher"] = fetcher
    return technical_supervisor.run(agent_input, **kwargs)
