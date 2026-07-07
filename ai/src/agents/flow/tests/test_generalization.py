"""종목 일반화(조각2) — 조용한 기본값 대체 제거 + market 배관 + 최소 방어.

원리: 위험은 기본값 자체가 아니라 '아래층의 조용한 대체'다 — input.ticker 가
  없을 때 말없이 삼성 데이터를 가져와 다른 종목 제목을 붙이는 사고를
  구조적으로 차단했음을 테스트로 고정한다. market 은 KIS 원본 그대로
  (매핑·가공 없음), 없으면 표기 생략(거짓 표기 금지).
"""

import sys
from datetime import date
from pathlib import Path

import pytest

# 네임스페이스 패키지(PEP 420) — src 를 경로에 넣어 agents.flow.* 를 import.
_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from fixtures import df_foreign_5day_streak  # noqa: E402

from agents.flow import agent  # noqa: E402
from agents.flow import graph  # noqa: E402
from agents.flow.schemas import AgentInput, GateResult, SupplyDemandState  # noqa: E402


def _state(ticker):
    return SupplyDemandState(
        input=AgentInput(query="", stock_name="아무개", ticker=ticker),
        base_date=date(2026, 7, 3),
    )


def _html(final):
    return final["html"] if isinstance(final, dict) else final.html


def test_collect_without_ticker_raises_instead_of_silent_default():
    """ticker 없음 → 삼성으로 조용히 대체하지 않고 즉시 멈춘다(fetch 전 — 네트워크 0)."""
    with pytest.raises(ValueError, match="ticker"):
        graph.collect_node(_state(None))


def test_run_rejects_malformed_ticker():
    """6자리 숫자가 아니면 API 호출 전에 차단(최소 방어 — 정식 검증은 게이트1).

    빈 값·None 은 이제 '종목명→티커 해석' 경로라 여기서 다루지 않는다
    (오프라인 검증은 test_ticker_resolve 가 master 주입으로 담당)."""
    for bad in ("12345", "ABC123"):
        with pytest.raises(ValueError, match="6자리"):
            agent.run(ticker=bad)


def test_market_flows_from_adapter_to_report(monkeypatch):
    """어댑터의 시장명이 원본 그대로 헤더에 실리고, 없으면(None) 표기가 생략된다."""
    monkeypatch.setattr(graph, "fetch_daily_quotes", lambda base_date, ticker: None)
    # 게이트2 강제 실패 → explain 건너뛰고 render (외부 경계 최소화, 헤더는 항상 그려짐)
    monkeypatch.setattr(
        graph, "verify_signals",
        lambda df, signals, ownership=None, quotes=None: GateResult(
            gate=2, passed=False, failures=["강제 실패(테스트)"]),
    )

    monkeypatch.setattr(graph, "fetch_supply_demand",
                        lambda base_date, ticker: (df_foreign_5day_streak, "KSQ150"))
    assert "KSQ150" in _html(graph.build_graph().invoke(_state("247540")))

    monkeypatch.setattr(graph, "fetch_supply_demand",
                        lambda base_date, ticker: (df_foreign_5day_streak, None))
    html = _html(graph.build_graph().invoke(_state("247540")))
    assert "KSQ150" not in html and "KOSPI" not in html   # 모르면 표기 안 함(거짓 금지)
