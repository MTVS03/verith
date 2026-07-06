"""LangGraph orchestration 전용 테스트 (`feat/technical-langgraph-orchestration`).

`run()`의 내부가 LangGraph StateGraph로 바뀌어도 (1) 기존과 동일 output, (2) 주입 의존성이 state로
전달, (3) allowlist/deadline/trace 정책 유지, (4) state에 secret/raw 미저장을 검증한다.
기존 fixture(ScriptedLlm·DAILY 등)는 test_technical_supervisor에서 재사용한다. **네트워크 없음.**
"""

from __future__ import annotations

import time

import pytest

from src.agents.technical.observability.trace_logger import InMemoryTraceSink, TraceLogger
from src.agents.technical.runtime.deadline import Deadline, DeadlineExceeded
from src.agents.technical.schemas.contracts import TechnicalAgentInput, TechnicalAgentOutput
from src.agents.technical.schemas.enums import DataStatus
from src.agents.technical.services.kis_client import OutOfScopeTickerError
from src.agents.technical.supervisor import technical_graph as tg
from src.agents.technical.supervisor import technical_supervisor as sup
from src.agents.technical.tests import test_technical_supervisor as st

_HAPPY = [st.NORM_OK, st.FOCUS_OK, st.INTERP_BAD, st.INTERP_BAD]  # template fallback → 정상 완료


def _fetcher(t, *, end_date=None):
    return {"D": st.DAILY, "W": st.WEEKLY, "M": st.MONTHLY}


@pytest.fixture(autouse=True)
def _intraday_off(monkeypatch):
    monkeypatch.setattr(sup, "INTRADAY_FETCH_ENABLED", False)


def _state(responses, *, daily=None, cache=None, deadline=None, sink=None):
    """graph.invoke용 초기 state(run()이 만드는 것과 동일 구조)."""
    trace = TraceLogger(sink, trace_id="t")
    d = daily if daily is not None else st.DAILY

    def fetcher(t, *, end_date=None):
        return {"D": d, "W": st.WEEKLY, "M": st.MONTHLY}
    return {
        "payload": st._input(), "trace_id": "t", "llm_client": st.ScriptedLlm(responses),
        "fetcher": fetcher, "cache": cache, "trace": trace, "deadline": deadline,
        "intraday_candles": None, "intraday_fetcher": None,
    }


# ── graph build/캐시 ──────────────────────────────────────────────────────────
def test_build_graph_is_cached():
    assert tg.build_technical_graph() is tg.build_technical_graph()  # module-level 캐시


# ── happy path: graph.invoke → 정상 output schema ─────────────────────────────
def test_graph_happy_output():
    final = tg.build_technical_graph().invoke(_state(_HAPPY))
    out = final["output"]
    assert isinstance(out, TechnicalAgentOutput)
    assert out.data_status == DataStatus.NORMAL and out.trace_id == "t"
    assert {p.period.value for p in out.charts} >= {"3m", "1y", "5y"}


# ── parity: run() 경로와 graph.invoke output 동일 ─────────────────────────────
def test_run_matches_graph_output():
    run_out = sup.run(st._input(), llm_client=st.ScriptedLlm(_HAPPY), fetcher=_fetcher, trace_id="t")
    graph_out = tg.build_technical_graph().invoke(_state(_HAPPY))["output"]
    assert run_out.model_dump() == graph_out.model_dump()  # 완전 동일 output


# ── 주입 의존성이 state로 전달됨 ──────────────────────────────────────────────
def test_injected_llm_used_not_created():
    st_state = _state(_HAPPY)
    llm = st_state["llm_client"]
    tg.build_technical_graph().invoke(st_state)
    assert llm.prompts                                   # 주입 fake가 실제로 호출됨(새 client 생성 아님)


def test_injected_cache_used_skips_fetcher():
    calls = {"n": 0}

    def fetch(t, *, end_date=None):
        calls["n"] += 1
        return {"D": st.DAILY, "W": st.WEEKLY, "M": st.MONTHLY}
    state = _state(_HAPPY, cache=st._FakeCache(st._DWM_FRESH))
    state["fetcher"] = fetch
    out = tg.build_technical_graph().invoke(state)["output"]
    assert calls["n"] == 0 and out.source == "KIS"       # fresh 캐시 사용 → fetcher 미호출


def test_injected_trace_sink_receives_events():
    sink = InMemoryTraceSink()
    tg.build_technical_graph().invoke(_state(_HAPPY, sink=sink))
    kinds = [(e["node"], e["event_type"]) for e in sink.events]
    # graph 노드들이 기존 trace node를 그대로 emit(순서 유지)
    for node in ("normalize_question", "focus_analysis", "data_collect",
                 "regime_classify", "chart_generate", "interpret_report"):
        assert (node, "node_start") in kinds and (node, "node_end") in kinds


# ── allowlist는 graph 이전(run 레벨)에서 차단 ─────────────────────────────────
def test_allowlist_blocks_before_graph():
    llm = st.ScriptedLlm([])
    bad = TechnicalAgentInput(ticker="999999", query="q", request_id="r", as_of=st.AS_OF)
    with pytest.raises(OutOfScopeTickerError):
        sup.run(bad, llm_client=llm, fetcher=_fetcher, trace_id="t")
    assert llm.prompts == []                             # OpenAI 미호출


# ── data_limited / regime_unavailable parity ──────────────────────────────────
def test_graph_data_limited_output():
    out = tg.build_technical_graph().invoke(_state([st.NORM_OK, st.FOCUS_OK], daily=[]))["output"]
    assert out.data_status == DataStatus.DATA_LIMITED and out.signal is None and out.charts == []


def test_graph_regime_unavailable_output():
    short = st._series(40, day_stride=1, start="2023-01-02")  # < MIN_DAILY_BARS
    out = tg.build_technical_graph().invoke(_state([st.NORM_OK, st.FOCUS_OK], daily=short))["output"]
    assert out.data_status == DataStatus.REGIME_UNAVAILABLE and out.signal is None
    assert {p.period.value for p in out.charts} >= {"3m", "1y", "5y"}


# ── deadline: graph 노드에서 DeadlineExceeded 전파 ────────────────────────────
def test_deadline_propagates_from_graph():
    expired = Deadline(expires_at=time.monotonic() - 1)
    with pytest.raises(DeadlineExceeded):
        tg.build_technical_graph().invoke(_state(_HAPPY, deadline=expired))


# ── state 위생: raw prompt/response/secret 미저장 ─────────────────────────────
def test_state_has_no_secret_keys():
    final = tg.build_technical_graph().invoke(_state(_HAPPY))
    for k in final:
        assert not any(h in k.lower() for h in ("prompt", "response", "api_key", "token", "secret"))
    # 저장된 llm_client는 주입 fake 그대로(내부에서 새 OpenAI client를 만들지 않음)
    assert isinstance(final["llm_client"], st.ScriptedLlm)
    # INTERP_BAD raw 문구가 output 직렬화에 남지 않음(template fallback으로 대체)
    assert "흥미롭습니다" not in final["output"].model_dump_json()
