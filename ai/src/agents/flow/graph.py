"""flow 그래프 조립 — 부품을 검증 경계로 잇는 배선(LangGraph).

원리: "노드 경계 = 검증 경계, 그래프가 판정, 노드는 실행."
  df(검증 안 된 원재료)는 collect 노드 지역변수로만 살고, 상태엔 검증된
  signals·gate2만 오른다. 게이트 통과 여부에 따른 분기(다음에 뭘 할지)는
  조건부 엣지(그래프)가 판정하고, 각 노드는 자기 일만 한다.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from . import config
from .core.kis_client import fetch_foreign_ownership, fetch_supply_demand
from .core.signals import compute_signals
from .core.verify_interpretation import verify_interpretation
from .core.verify_rules import verify_signals
from .nodes.explain import explain
from .render.builder import build_report
from .schemas import SupplyDemandState


def _meta(state: SupplyDemandState) -> dict:
    """표시·해석용 메타 조립. input+base_date+market 로 만든다.

    ticker 후퇴 기본값 없음(조각2) — collect_node 가 진입에서 이미 보장했다.
    """
    return {
        "stock_name": state.input.stock_name,
        "ticker": state.input.ticker,
        "base_date": state.base_date.isoformat() if state.base_date else None,
        "market": state.market,   # KIS 원본 그대로 — 없으면 None(템플릿이 칩 생략)
    }


# ── 노드 ──────────────────────────────────────────────────
def collect_node(state: SupplyDemandState) -> dict:
    """수집 + 계산 + 게이트2. df·ownership 은 이 함수 지역변수로만 존재(밖으로 안 나감).

    KIS/네트워크 예외는 삼키지 않고 그대로 전파한다(규약: 연쇄 시도 없이 멈춤).
    한도소진율은 심화 축이라 ENABLE_ADVANCED 가 꺼져 있으면 아예 조회하지 않는다
    (추가 API 호출 절약 + 플래그 하나로 심화 전체가 꺼지는 단일 스위치).
    """
    ticker = state.input.ticker
    if not ticker:
        # 조용한 기본값 대체 금지(조각2) — 엉뚱한 종목 데이터에 다른 제목이
        # 붙는 사고를 구조로 차단. 종목명→티커 해석은 게이트1(조각3) 소관.
        raise ValueError("ticker 가 없습니다 — 호출부가 6자리 종목코드를 지정해야 합니다.")
    df, market = fetch_supply_demand(state.base_date, ticker)  # 원재료 — 지역 한정
    ownership = (
        fetch_foreign_ownership(state.base_date, ticker)
        if config.ENABLE_ADVANCED else None
    )
    signals = compute_signals(df, ownership)
    gate2 = verify_signals(df, signals, ownership)
    # market 은 표시 전용 원본 문자열(숫자 아님) — 게이트2 대상이 아니다.
    return {"signals": signals, "gate2": gate2, "market": market}


def explain_node(state: SupplyDemandState) -> dict:
    """해석 생성. 재진입(이미 해석이 있던 경우)이면 재시도이므로 카운터 +1."""
    retries = state.explain_retries
    if state.interpretation is not None:                 # 앞선 시도가 있었다 → 재시도
        retries += 1
    interpretation = explain(state.signals, state.gate2, _meta(state))
    return {"interpretation": interpretation, "explain_retries": retries}


def gate3_node(state: SupplyDemandState) -> dict:
    """게이트3 — 해석↔팩트 대조. 판정만 상태에 올린다."""
    gate3 = verify_interpretation(state.interpretation, state.signals)
    return {"gate3": gate3}


def render_node(state: SupplyDemandState) -> dict:
    """표시 전용. '통과분만 넘긴다' 판정은 그래프가 이미 했으므로, 여기선
    gate3 통과 시에만 interpretation을 싣고 아니면 None(placeholder). 가공 없음."""
    passed3 = state.gate3 is not None and state.gate3.passed
    interpretation = state.interpretation if passed3 else None
    html = build_report(state.signals, state.gate2, _meta(state), interpretation)
    return {"html": html}


# ── 조건부 엣지(게이트 분기) ───────────────────────────────
def route_after_collect(state: SupplyDemandState) -> str:
    """게이트2 통과면 해석으로, 실패면 해석 건너뛰고 바로 render(팩트만)."""
    return "explain" if (state.gate2 and state.gate2.passed) else "render"


def route_after_gate3(state: SupplyDemandState) -> str:
    """게이트3 통과 → render. 실패 → 상한 내면 재시도, 상한 초과면 render 후퇴.

    두 탈출구(통과 / 상한 초과)가 무한 루프를 막는다. 상한은 MAX_EXPLAIN_RETRIES.
    """
    if state.gate3 and state.gate3.passed:
        return "render"
    if state.explain_retries < config.MAX_EXPLAIN_RETRIES:
        return "explain"                                 # 재시도
    return "render"                                      # 해석 생략 후퇴


# ── 그래프 조립 ────────────────────────────────────────────
def build_graph():
    """노드·엣지를 엮어 컴파일된 그래프를 반환한다."""
    g = StateGraph(SupplyDemandState)
    g.add_node("collect", collect_node)
    g.add_node("explain", explain_node)
    g.add_node("verify_explanation", gate3_node)
    g.add_node("render", render_node)

    g.add_edge(START, "collect")
    g.add_conditional_edges(
        "collect", route_after_collect,
        {"explain": "explain", "render": "render"},
    )
    g.add_edge("explain", "verify_explanation")
    g.add_conditional_edges(
        "verify_explanation", route_after_gate3,
        {"explain": "explain", "render": "render"},
    )
    g.add_edge("render", END)
    return g.compile()
