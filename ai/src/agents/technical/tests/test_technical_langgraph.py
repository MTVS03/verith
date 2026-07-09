"""LangGraph orchestration 전용 테스트 (`feat/technical-langgraph-orchestration`).

`run()`의 내부가 LangGraph StateGraph로 바뀌어도 (1) 기존과 동일 output, (2) 주입 의존성이 config
(`TechnicalDeps`)로 전달, (3) allowlist/deadline/trace 정책 유지, (4) **정화된 state**(계산 결과만,
원본 query·client 없음)를 검증한다.
기존 fixture(ScriptedLlm·DAILY 등)는 test_technical_supervisor에서 재사용한다. **네트워크 없음.**
"""

from __future__ import annotations

import time

import pytest

from src.agents.technical.observability.trace_logger import InMemoryTraceSink, TraceLogger
from src.agents.technical.runtime.deadline import Deadline, DeadlineExceeded
from src.agents.technical.schemas.contracts import TechnicalAgentInput, TechnicalAgentOutput
from src.agents.technical.schemas.enums import DataStatus
from src.agents.technical.supervisor import technical_graph as tg
from src.agents.technical.supervisor import technical_supervisor as sup
from src.agents.technical.supervisor import pipeline_steps as steps
from src.agents.technical.supervisor.langgraph_state import TechnicalDeps
from src.agents.technical.tests import test_technical_supervisor as st

_HAPPY = [st.NORM_OK, st.FOCUS_OK, st.INTERP_BAD, st.INTERP_BAD]  # template fallback → 정상 완료


def _fetcher(t, *, end_date=None):
    return {"D": st.DAILY, "W": st.WEEKLY, "M": st.MONTHLY}


@pytest.fixture(autouse=True)
def _intraday_off(monkeypatch):
    monkeypatch.setattr(steps, "INTRADAY_FETCH_ENABLED", False)


def _deps(responses, *, daily=None, cache=None, deadline=None, sink=None, fetcher=None):
    """graph invoke용 TechnicalDeps(run()이 만드는 것과 동일). deps는 config로 주입된다(state 아님)."""
    trace = TraceLogger(sink, trace_id="t")
    d = daily if daily is not None else st.DAILY

    def _f(t, *, end_date=None):
        return {"D": d, "W": st.WEEKLY, "M": st.MONTHLY}
    return TechnicalDeps(
        payload=st._input(), trace_id="t", trace=trace, llm_client=st.ScriptedLlm(responses),
        fetcher=fetcher or _f, cache=cache, deadline=deadline,
        intraday_candles=None, intraday_fetcher=None,
    )


def _run(deps):
    """정화된 호출: state는 비우고 주입 의존성은 config['configurable']['deps']로 넘긴다."""
    return tg.build_technical_graph().invoke({}, config={"configurable": {"deps": deps}})


# ── graph build/캐시 ──────────────────────────────────────────────────────────
def test_build_graph_is_cached():
    assert tg.build_technical_graph() is tg.build_technical_graph()  # module-level 캐시


# ── happy path: graph.invoke → 정상 output schema ─────────────────────────────
def test_graph_happy_output():
    final = _run(_deps(_HAPPY))
    out = final["output"]
    assert isinstance(out, TechnicalAgentOutput)
    assert out.data_status == DataStatus.NORMAL and out.trace_id == "t"
    assert {p.period.value for p in out.charts} >= {"3m", "1y", "5y"}


# ── parity: run() 경로와 graph.invoke output 동일 ─────────────────────────────
def test_run_matches_graph_output():
    run_out = sup.run(st._input(), llm_client=st.ScriptedLlm(_HAPPY), fetcher=_fetcher, trace_id="t")
    graph_out = _run(_deps(_HAPPY))["output"]
    assert run_out.model_dump() == graph_out.model_dump()  # 완전 동일 output


# ── 주입 의존성이 state로 전달됨 ──────────────────────────────────────────────
def test_injected_llm_used_not_created():
    deps = _deps(_HAPPY)
    tg.build_technical_graph().invoke({}, config={"configurable": {"deps": deps}})
    assert deps.llm_client.prompts                       # 주입 fake가 실제로 호출됨(새 client 생성 아님)


def test_injected_cache_used_skips_fetcher():
    calls = {"n": 0}

    def fetch(t, *, end_date=None):
        calls["n"] += 1
        return {"D": st.DAILY, "W": st.WEEKLY, "M": st.MONTHLY}
    deps = _deps(_HAPPY, cache=st._FakeCache(st._DWM_FRESH), fetcher=fetch)
    out = _run(deps)["output"]
    assert calls["n"] == 0 and out.source == "KIS"       # fresh 캐시 사용 → fetcher 미호출


def test_injected_trace_sink_receives_events():
    sink = InMemoryTraceSink()
    _run(_deps(_HAPPY, sink=sink))
    kinds = [(e["node"], e["event_type"]) for e in sink.events]
    # graph 노드들이 기존 trace node를 그대로 emit(순서 유지)
    for node in ("normalize_question", "focus_analysis", "data_collect",
                 "regime_classify", "chart_generate", "interpret_report"):
        assert (node, "node_start") in kinds and (node, "node_end") in kinds


# ── 전체 종목 확장: 구 out-of-scope ticker도 gate에 막히지 않고 graph를 통과 ───────────────
def test_expanded_ticker_runs_through_graph():
    llm = st.ScriptedLlm(list(_HAPPY))
    expanded = TechnicalAgentInput(ticker="999999", query="q", request_id="r", as_of=st.AS_OF)
    out = sup.run(expanded, llm_client=llm, fetcher=_fetcher, trace_id="t")
    assert isinstance(out, TechnicalAgentOutput) and out.ticker == "999999"  # 정상 완료(미차단)


# ── data_limited / regime_unavailable parity ──────────────────────────────────
def test_graph_data_limited_output():
    out = _run(_deps([st.NORM_OK, st.FOCUS_OK], daily=[]))["output"]
    assert out.data_status == DataStatus.DATA_LIMITED and out.signal is None and out.charts == []


def test_graph_regime_unavailable_output():
    short = st._series(40, day_stride=1, start="2023-01-02")  # < MIN_DAILY_BARS
    out = _run(_deps([st.NORM_OK, st.FOCUS_OK], daily=short))["output"]
    assert out.data_status == DataStatus.REGIME_UNAVAILABLE and out.signal is None
    assert {p.period.value for p in out.charts} >= {"3m", "1y", "5y"}


# ── deadline: graph 노드에서 DeadlineExceeded 전파 ────────────────────────────
def test_deadline_propagates_from_graph():
    expired = Deadline(expires_at=time.monotonic() - 1)
    with pytest.raises(DeadlineExceeded):
        _run(_deps(_HAPPY, deadline=expired))


# ── state는 정화됨(secret-safe) — 원본 query·runtime client는 state에 없고 config(deps)로만 흐름 ──
def test_state_is_sanitized_no_pii_or_client():
    # 정화 경계: traced state에는 계산 결과만 — 원본 query(PII)·runtime client가 **없다**.
    # 그래서 checkpointer·LangSmith가 state를 직렬화해도 PII·secret이 새지 않는다.
    deps = _deps(_HAPPY)
    final = tg.build_technical_graph().invoke({}, config={"configurable": {"deps": deps}})
    assert "llm_client" not in final and "fetcher" not in final and "cache" not in final  # client 없음
    assert "payload" not in final and "trace" not in final                                # 원본 query·trace 없음
    # 주입 의존성은 config(deps)에만 있고 실제로 사용됨(호출 발생)
    assert deps.llm_client.prompts and deps.payload.query
    # 새 raw prompt/response 필드 없음, output 직렬화에 raw LLM 문구 없음
    assert not any(h in k.lower() for k in final for h in ("prompt", "response", "api_key", "token"))
    assert "흥미롭습니다" not in final["output"].model_dump_json()  # INTERP_BAD raw → template fallback 대체


# ── 단방향 의존: supervisor → technical_graph → pipeline_steps (역방향 import 없음) ──
def _imported_modules(module) -> set:
    import ast
    import pathlib
    names: set = set()
    for node in ast.walk(ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(a.name for a in node.names)  # `from . import X` 대비
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    return names


def test_graph_does_not_import_supervisor():
    imported = _imported_modules(tg)
    assert not any("technical_supervisor" in m for m in imported)  # 순환 결합 제거
    assert "pipeline_steps" in imported                           # steps만 참조


def test_pipeline_steps_does_not_import_graph_or_supervisor():
    # 단방향 강제: pipeline_steps는 leaf만 import — graph/supervisor를 참조하지 않는다
    imported = _imported_modules(steps)
    assert not any(("technical_graph" in m or "technical_supervisor" in m) for m in imported)


def test_graph_node_wrappers_call_pipeline_steps():
    # node wrapper 소스가 steps.<helper>를 호출한다(supervisor private helper 직접 호출 아님)
    import pathlib
    src = pathlib.Path(tg.__file__).read_text(encoding="utf-8")
    assert "steps._collect_ohlcv" in src and "steps._interpret" in src and "steps.check_deadline" in src
    assert "_sup." not in src  # 옛 supervisor 참조 흔적 없음


# ── normalize/focus 실제 별도 node 분리 ───────────────────────────────────────
def test_normalize_focus_are_separate_nodes():
    node_names = set(tg.build_technical_graph().get_graph().nodes)
    assert {"normalize_question", "focus_analysis"} <= node_names   # 두 노드가 분리 존재
    # 실행 시 normalize 결과가 state에 저장되고 focus의 입력으로 쓰인다
    final = _run(_deps(_HAPPY))
    assert final["normalized"].normalized_question                 # 노드 1 산출이 state에 있음


def test_normalize_focus_split_preserves_llm_calls_and_trace():
    # 분리해도 LLM 호출 2회(normalize+focus)·trace 이벤트 순서 유지
    sink = InMemoryTraceSink()
    deps = _deps(_HAPPY, sink=sink)
    _run(deps)
    names = [e["node"] for e in sink.events if e["event_type"] == "node_start"]
    assert names.index("normalize_question") < names.index("focus_analysis") < names.index("data_collect")
    # NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD = interpret까지 4회(normalize 1 + focus 1 + interpret 2)
    assert len(deps.llm_client.prompts) == 4
