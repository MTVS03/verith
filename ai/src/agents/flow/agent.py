"""flow 에이전트 진입점 — 초기 상태 구성 → 그래프 실행 → AgentOutput.

종목은 일반화됨(조각2): ticker 인자로 임의 종목 지정. 기본값(삼성전자)은
개발 편의(데모·수동 실행)일 뿐이고, 데이터 경로(그래프·어댑터)에는 기본값이
없다. base_date 자동 산출은 조각3.
"""

from __future__ import annotations

import re
from datetime import date

from . import config
from .graph import build_graph
from .schemas import AgentInput, AgentOutput, SupplyDemandState

# M1 기준일: 오늘은 장중 미확정(KIS TIME LIMIT)이라 확정된 과거 거래일로 고정.
_M1_BASE_DATE = date(2026, 7, 3)

# 최소 방어(조각2): 6자리 종목코드 형식. 형식 불량은 실전 API 호출 하나를
# 태우고 알 수 없는 KIS 에러로 나타나므로 호출 전에 차단한다.
# 종목명→티커 해석·stock_name↔ticker 정합 검증은 게이트1(조각3) 소관.
_TICKER_RE = re.compile(r"\d{6}")

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
    # ── 최소 방어: ticker 형식 (자세한 이유는 _TICKER_RE 주석) ──
    if not ticker or not _TICKER_RE.fullmatch(str(ticker)):
        raise ValueError(f"ticker 는 6자리 종목코드여야 합니다 (받은 값: {ticker!r}).")

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
