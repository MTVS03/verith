"""게이트1(입력 검증 + base_date 산출) — 실패 차단과 18시 규칙의 결정론 검증.

원리: 오늘(장중) 요청은 KIS가 에러 없이 미확정 행을 조용히 준다(실물 확인).
  확정일 보장은 전적으로 게이트1의 몫 — 그 규칙을 now 주입으로 고정한다.
  게이트1 실패는 후퇴(placeholder)가 아니라 예외다(만들 리포트가 없다).
"""

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

# 네임스페이스 패키지(PEP 420) — src 를 경로에 넣어 agents.flow.* 를 import.
_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from fixtures import df_foreign_5day_streak  # noqa: E402

from agents.flow import graph  # noqa: E402
from agents.flow.core.verify_input import verify_input  # noqa: E402
from agents.flow.schemas import AgentInput, SupplyDemandState  # noqa: E402

_KST = ZoneInfo("Asia/Seoul")
_MON_17 = datetime(2026, 7, 6, 17, 0, tzinfo=_KST)   # 월요일 18시 전(장중·미확정)
_MON_19 = datetime(2026, 7, 6, 19, 0, tzinfo=_KST)   # 월요일 18시 후(당일 확정)


def _inp(ticker="005930"):
    return AgentInput(query="", stock_name="삼성전자", ticker=ticker)


def test_rejects_malformed_ticker():
    """형식 불량은 API 호출 전에 차단 (없음·5자리·문자 혼입)."""
    for bad in (None, "12345", "ABC123", ""):
        gate1, _ = verify_input(_inp(bad), date(2026, 7, 3), now=_MON_19)
        assert gate1.passed is False
        assert any("6자리" in f for f in gate1.failures)


def test_rejects_future_and_intraday_base_date():
    """미래 날짜(없는 데이터)와 오늘·18시 전(장중 미확정)은 실패."""
    gate1, _ = verify_input(_inp(), date(2026, 7, 10), now=_MON_19)
    assert gate1.passed is False and any("미래" in f for f in gate1.failures)

    gate1, _ = verify_input(_inp(), date(2026, 7, 6), now=_MON_17)
    assert gate1.passed is False and any("미확정" in f for f in gate1.failures)


def test_accepts_today_after_finalize_and_past_dates():
    """18시 후의 오늘과 과거 날짜는 통과, 명시값은 그대로 쓴다."""
    gate1, bd = verify_input(_inp(), date(2026, 7, 6), now=_MON_19)
    assert gate1.passed is True and bd == date(2026, 7, 6)

    gate1, bd = verify_input(_inp(), date(2026, 7, 3), now=_MON_17)
    assert gate1.passed is True and bd == date(2026, 7, 3)


def test_auto_base_date_follows_18h_rule():
    """자동 산출: 18시 전 → 어제(휴일이어도 KIS 클램프가 처리), 18시 후 → 오늘."""
    _, bd = verify_input(_inp(), None, now=_MON_17)
    assert bd == date(2026, 7, 5)          # 일요일 — 클램프는 KIS 몫(실측)
    _, bd = verify_input(_inp(), None, now=_MON_19)
    assert bd == date(2026, 7, 6)


def test_collect_confirms_base_date_from_response(monkeypatch):
    """collect 가 base_date 를 응답의 마지막 행 날짜로 갱신한다(클램프 반영)."""
    monkeypatch.setattr(graph, "fetch_supply_demand",
                        lambda base_date, ticker: (df_foreign_5day_streak, "KOSPI200"))
    monkeypatch.setattr(graph, "fetch_daily_quotes", lambda base_date, ticker: None)
    state = SupplyDemandState(input=_inp(), base_date=date(2026, 7, 4))  # 토요일 후보
    out = graph.collect_node(state)
    assert out["base_date"] == df_foreign_5day_streak.index[-1].date()


def test_graph_stops_on_gate1_failure():
    """validate 실패 → 후퇴 없이 예외 (fetch 전이라 네트워크 0)."""
    state = SupplyDemandState(input=_inp("12345"), base_date=date(2026, 7, 3))
    with pytest.raises(ValueError, match="게이트1"):
        graph.build_graph().invoke(state)
