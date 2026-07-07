"""배선 스모크 테스트 — run() 그래프의 분기·재시도·후퇴가 실제로 작동하나.

원리: "흐름만 테스트, 외부는 가짜."
  외부 경계 2곳(KIS=fetch_supply_demand, OpenAI=explain)만 monkeypatch로 바꿔치기하고,
  흐름의 부품(compute·verify_signals·verify_interpretation·라우팅·재시도 카운터·render)은
  전부 진짜로 둔다. 실제 KIS·OpenAI 호출 0회 → 무과금·무네트워크·결정론.

  게이트 판정 자체의 정확성은 test_verify / test_verify_interpretation 이 담당한다.
  여기서 검증하는 건 '판정에 배선이 어떻게 반응하나'(분기·재시도·후퇴)뿐이다.
"""

import sys
from datetime import date
from pathlib import Path

# 네임스페이스 패키지(PEP 420) — src 를 경로에 넣어 agents.flow.* 를 import.
_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from fixtures import df_foreign_5day_streak  # noqa: E402

from agents.flow import config  # noqa: E402
from agents.flow import graph  # noqa: E402
from agents.flow.schemas import AgentInput, GateResult, SupplyDemandState  # noqa: E402


def _initial():
    """손으로 만든 초기 상태. fetch가 가짜라 base_date는 실제 조회에 안 쓰인다."""
    return SupplyDemandState(
        input=AgentInput(query="", stock_name="삼성전자", ticker="005930"),
        base_date=date(2026, 7, 3),
    )


def _get(final, key):
    """invoke 결과에서 값 꺼내기. langgraph는 한 번도 안 쓰인 채널(예: explain을
    건너뛴 경로의 interpretation)을 결과에 안 넣으므로, 없으면 None(스키마 기본값)."""
    return final.get(key) if isinstance(final, dict) else getattr(final, key, None)


def _fake_fetch(base_date, ticker):
    """KIS 경계 대체 — 유효한 fixture df + 시장명(원본 형식) 반환(네트워크 회피)."""
    return df_foreign_5day_streak, "KOSPI200"


def _fake_fetch_quotes(base_date, ticker):
    """KIS 시세 경계 대체 — None(소진율·시세 모두 '주장 없음' 경로, 네트워크 회피).
    규칙7·8 본검사는 test_ownership/test_price_daily 담당 — 스모크는 배선만."""
    return None


# 팩트와 무관하게 게이트3 규칙3(개인 오귀속)에 걸리는 문장 → 진짜 게이트3가 매번 실패.
_GATE3_FAILING = "개인과 외국인 간에 엇갈린 흐름을 보였다."


def test_A_gate2_failure_skips_explain_and_renders_placeholder(monkeypatch):
    """게이트2 실패 → explain 건너뛰고 render, 해석 없이 placeholder."""
    monkeypatch.setattr(graph, "fetch_supply_demand", _fake_fetch)
    monkeypatch.setattr(graph, "fetch_daily_quotes", _fake_fetch_quotes)
    # 게이트2 판정을 강제 실패(탐지 로직은 test_verify 담당, 여기선 배선 반응만).
    monkeypatch.setattr(
        graph, "verify_signals",
        lambda df, signals, ownership=None, quotes=None: GateResult(
            gate=2, passed=False, failures=["강제 실패(테스트)"]),
    )
    calls = {"explain": 0}

    def fake_explain(signals, gate2, meta):
        calls["explain"] += 1
        return "이 문장은 호출되면 안 된다"

    monkeypatch.setattr(graph, "explain", fake_explain)

    final = graph.build_graph().invoke(_initial())

    assert calls["explain"] == 0                          # explain 구조적으로 건너뜀
    assert _get(final, "interpretation") is None
    assert "해석 생략" in _get(final, "html")               # placeholder 렌더
    assert _get(final, "gate2").passed is False


def test_B_gate3_persistent_failure_retries_up_to_limit(monkeypatch):
    """게이트3가 계속 실패 → explain이 정확히 (1 + 상한)회만 호출되고 멈춤(무한 루프 없음)."""
    monkeypatch.setattr(graph, "fetch_supply_demand", _fake_fetch)
    monkeypatch.setattr(graph, "fetch_daily_quotes", _fake_fetch_quotes)
    calls = {"explain": 0}

    def fake_explain(signals, gate2, meta):
        calls["explain"] += 1
        return _GATE3_FAILING

    monkeypatch.setattr(graph, "explain", fake_explain)

    graph.build_graph().invoke(_initial())

    assert calls["explain"] == 1 + config.MAX_EXPLAIN_RETRIES   # 첫 1 + 재시도 2 = 3


def test_C_gate3_exhaustion_falls_back_to_placeholder(monkeypatch):
    """재시도 소진 후 → 해석 없이 render 후퇴(placeholder), 틀린 해석은 안 실림."""
    monkeypatch.setattr(graph, "fetch_supply_demand", _fake_fetch)
    monkeypatch.setattr(graph, "fetch_daily_quotes", _fake_fetch_quotes)
    monkeypatch.setattr(graph, "explain", lambda signals, gate2, meta: _GATE3_FAILING)

    final = graph.build_graph().invoke(_initial())

    assert _get(final, "gate3").passed is False            # 최종 게이트3 미통과
    assert "해석 생략" in _get(final, "html")               # placeholder 후퇴
    assert _GATE3_FAILING not in _get(final, "html")       # 틀린 해석은 안 실림
