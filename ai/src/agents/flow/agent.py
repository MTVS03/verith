"""flow 에이전트 진입점 — 초기 상태 구성 → 그래프 실행 → AgentOutput.

종목은 일반화됨(조각2): ticker 인자로 임의 종목 지정. 기본값(삼성전자)은
개발 편의(데모·수동 실행)일 뿐이고, 데이터 경로(그래프·어댑터)에는 기본값이
없다. base_date 는 자동(조각3): 게이트1이 18시 규칙으로 후보일을 산출하고,
수집 응답의 마지막 행이 확정 거래일이 된다. 입력 검증도 게이트1(validate
노드)로 일원화 — 이 파일에는 검증 로직이 없다.
"""

from __future__ import annotations

from datetime import date

from . import config
from .export.to_json import build_payload
from .graph import build_graph
from .schemas import AgentInput, AgentOutput, SupplyDemandState

# 그래프는 조립 비용이 있으니 모듈 로드 시 1회 컴파일해 재사용.
_GRAPH = build_graph()


def _get(final, key):
    """langgraph invoke 결과가 dict든 pydantic 객체든 같은 방식으로 값 꺼내기.

    한 번도 안 쓰인 채널(예: 게이트2 실패로 explain 을 건너뛴 경로의 gate3)은
    결과 dict 에 아예 없으므로 None 으로 후퇴한다(스키마 기본값과 동일)."""
    return final.get(key) if isinstance(final, dict) else getattr(final, key, None)


def run(
    query: str = "",
    stock_name: str = config.TARGET_NAME,
    ticker: str = config.TARGET_TICKER,
    base_date: date | None = None,
) -> AgentOutput:
    """수급 리포트를 생성해 AgentOutput으로 반환한다.

    base_date=None(기본)이면 게이트1이 18시 규칙으로 후보일을 산출하고,
    수집 후 응답의 마지막 확정 거래일로 확정된다. 명시하면 그 날짜로
    게이트1 검증(미래·장중 미확정 차단)만 거친다.
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
    # base_date 는 collect 가 확정한 실제 거래일(입력 후보일이 아님 — 정직한 메타).
    confirmed = _get(final, "base_date")
    base_date_iso = confirmed.isoformat() if confirmed else None

    # ── JSON 출구 (배선 A): 검증된 state 를 옮겨 담기만 — 재계산·재검증 없음 ──
    payload = build_payload(
        signals=_get(final, "signals"),
        meta={
            "stock_name": stock_name,
            "ticker": ticker,
            "market": _get(final, "market"),
            "base_date": base_date_iso,
        },
        gate1=_get(final, "gate1"),
        gate2=_get(final, "gate2"),
        gate3=_get(final, "gate3"),
        interpretation=_get(final, "interpretation"),
        report_id=_get(final, "report_id"),
    )

    return AgentOutput(
        report_id=_get(final, "report_id"),
        html=_get(final, "html"),
        meta={
            "stock_name": stock_name,
            "ticker": ticker,
            "base_date": base_date_iso,
        },
        payload=payload,
    )
