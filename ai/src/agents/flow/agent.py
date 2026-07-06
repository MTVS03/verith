"""flow 에이전트 진입점 — 초기 상태 구성 → 그래프 실행 → AgentOutput.

M1: 삼성전자·확정 거래일(2026-07-03) 하드코딩. 일반화(종목·날짜)는 M2.
"""

from __future__ import annotations

from datetime import date

from . import config
from .graph import build_graph
from .schemas import AgentInput, AgentOutput, SupplyDemandState

# M1 기준일: 오늘은 장중 미확정(KIS TIME LIMIT)이라 확정된 과거 거래일로 고정.
_M1_BASE_DATE = date(2026, 7, 3)

# 그래프는 조립 비용이 있으니 모듈 로드 시 1회 컴파일해 재사용.
_GRAPH = build_graph()


def _get(final, key):
    """langgraph invoke 결과가 dict든 pydantic 객체든 같은 방식으로 값 꺼내기."""
    return final[key] if isinstance(final, dict) else getattr(final, key)


def run(
    query: str = "",
    stock_name: str = config.TARGET_NAME,
    ticker: str = config.TARGET_TICKER,
    base_date: date = _M1_BASE_DATE,
) -> AgentOutput:
    """수급 리포트를 생성해 AgentOutput으로 반환한다.

    query(사용자 원문)는 상태에만 담고 LLM 프롬프트엔 넣지 않는다(인젝션 방어).
    """
    # ── 초기 상태 구성 ───────────────────────────────────
    # input: 팀 입력 계약(AgentInput). base_date: M1 확정일.
    # report_id 는 SupplyDemandState 가 진입 시 자동 발급(uuid4).
    initial = SupplyDemandState(
        input=AgentInput(query=query, stock_name=stock_name, ticker=ticker),
        base_date=base_date,
    )

    # ── 그래프 실행 ──────────────────────────────────────
    final = _GRAPH.invoke(initial)

    # ── 결과에서 산출물 꺼내 출력 계약으로 ───────────────
    # html 은 render 노드가 채운 값. report_id 는 흐름을 관통한 상관관계 ID.
    return AgentOutput(
        report_id=_get(final, "report_id"),
        html=_get(final, "html"),
        meta={
            "stock_name": stock_name,
            "ticker": ticker,
            "base_date": base_date.isoformat(),
        },
    )
