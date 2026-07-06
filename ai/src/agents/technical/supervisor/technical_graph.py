"""Technical Agent 실행 흐름을 LangGraph StateGraph로 표현한다(`feat/technical-langgraph-orchestration`).

**흐름 표현만 바꾼다** — 계산·판단·output schema는 그대로다. 각 node는 기존 supervisor helper를
**그대로 호출하는 얇은 wrapper**이며 새 로직을 만들지 않는다. helper는 `technical_supervisor`에 남아
있고 여기서 `_sup.<name>`으로 참조한다(→ 순환 import는 run()의 lazy import로 끊고, deadline
monkeypatch는 `_sup.check_deadline` 참조로 그대로 동작한다).

trace(`trace_start`/`trace_end`)와 allowlist는 `run()` 레벨에 있고 이 graph는 **그 사이 파이프라인**만
담당한다. deadline stage 문자열·trace node 이름은 기존과 동일하게 유지한다(테스트 계약).

conditional edge는 **2개뿐**: (1) 빈 일봉 → data_limited, (2) regime unavailable → 안전 착지.
그 외 fallback/재생성/template fallback은 helper 내부 로직을 그대로 쓴다. checkpointer는 쓰지 않는다.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from . import technical_supervisor as _sup
from .langgraph_state import TechnicalGraphState
from ..nodes.chart_generate import run_chart_generate
from ..nodes.confidence_calculate import run_confidence_calculate
from ..nodes.indicator_calculate import run_indicator_calculate
from ..nodes.regime_classify import run_regime_classify
from ..nodes.risk_detect import run_risk_detect
from ..nodes.signal_aggregate import run_signal_aggregate
from ..schemas.contracts import RiskSummary, TechnicalAgentOutput
from ..schemas.enums import DataStatus, Regime

# `_sup.<name>`으로 접근하는 심볼(런타임 조회) — 테스트가 sup에 monkeypatch하는 것들과 supervisor가
# 소유한 helper: check_deadline·INTRADAY_FETCH_ENABLED·fetch_minute_ohlcv·_preprocess·_collect_ohlcv·
# _interpret·_to_*·_unavailable_output·_empty_regime·_resolve_intraday·_assemble_intraday·
# _emit_regime_unavailable_skips·_chart_summary·_data_status. (run_* 노드는 위에서 직접 import.)


# ── node wrapper (기존 helper 호출만) ─────────────────────────────────────────
def _n_preprocess(state: TechnicalGraphState) -> dict:
    _sup.check_deadline(state.get("deadline"), "preprocess")
    _normalized, focus = _sup._preprocess(
        state["llm_client"], state["payload"], state["trace"], state.get("deadline"))
    return {"focus": focus}


def _n_data_collect(state: TechnicalGraphState) -> dict:
    deadline, payload = state.get("deadline"), state["payload"]
    _sup.check_deadline(deadline, "data_collect")
    ohlcv, used_stale = _sup._collect_ohlcv(
        payload.ticker, payload.as_of, state["fetcher"], state.get("cache"), state["trace"])
    _sup.check_deadline(deadline, "post_data_collect")
    return {
        "ohlcv": ohlcv, "used_stale": used_stale,
        "daily": ohlcv["D"], "weekly": ohlcv["W"], "monthly": ohlcv["M"],
        "source": "KIS (stale)" if used_stale else "KIS",
    }


def _n_output_data_limited(state: TechnicalGraphState) -> dict:
    # 빈 일봉 → 안전 착지(data_limited-B). 기존 early-return과 동일.
    output = _sup._unavailable_output(
        state["payload"], state["trace_id"], DataStatus.DATA_LIMITED,
        regime=_sup._empty_regime("시세 데이터를 확보하지 못해 국면을 판정하지 않습니다."),
        charts=[], source=state["source"],
    )
    return {"output": output}


def _n_regime_classify(state: TechnicalGraphState) -> dict:
    _sup.check_deadline(state.get("deadline"), "regime_classify")
    with state["trace"].node("regime_classify") as span:
        rr = run_regime_classify(state["daily"], state["weekly"], state["monthly"])
        span.output_summary = {
            "daily_regime": rr.daily_regime.value,
            "final_regime": rr.final_regime.value,
            "alignment_flag": rr.alignment_flag.value,
        }
    return {"regime_result": rr}


def _n_output_regime_unavailable(state: TechnicalGraphState) -> dict:
    # regime 판단 불가 → 노드 6·7·8 skipped + chart 후 안전 착지. 기존 early-return과 동일.
    trace = state["trace"]
    _sup._emit_regime_unavailable_skips(trace)
    with trace.node("chart_generate") as span:
        charts = run_chart_generate(state["daily"], state["weekly"], state["monthly"])
        span.output_summary = _sup._chart_summary(charts)
    output = _sup._unavailable_output(
        state["payload"], state["trace_id"], DataStatus.REGIME_UNAVAILABLE,
        regime=_sup._to_regime_result(state["regime_result"]), charts=charts, source=state["source"],
    )
    return {"output": output}


def _n_indicator_calculate(state: TechnicalGraphState) -> dict:
    _sup.check_deadline(state.get("deadline"), "indicator_calculate")
    with state["trace"].node("indicator_calculate") as span:
        bundle = run_indicator_calculate(state["daily"])
        span.output_summary = {"bar_count": len(state["daily"])}
    return {"bundle": bundle}


def _n_signal_aggregate(state: TechnicalGraphState) -> dict:
    with state["trace"].node("signal_aggregate") as span:
        sr = run_signal_aggregate(state["daily"])
        span.output_summary = {"signal_score": sr.signal_score, "consensus": sr.consensus.value}
    return {"signal_result": sr}


def _n_confidence_calculate(state: TechnicalGraphState) -> dict:
    with state["trace"].node("confidence_calculate") as span:
        conf = run_confidence_calculate(state["signal_result"], state["bundle"], state["regime_result"])
        span.output_summary = {
            "confidence": conf.confidence, "confidence_level": conf.confidence_level.value,
        }
    return {"confidence": conf}


def _n_risk_detect(state: TechnicalGraphState) -> dict:
    with state["trace"].node("risk_detect") as span:
        risks = run_risk_detect(state["signal_result"], state["bundle"], state["regime_result"])
        span.output_summary = {"risk_count": len(risks)}
    return {"risk_items": risks}


def _n_chart_generate(state: TechnicalGraphState) -> dict:
    with state["trace"].node("chart_generate") as span:
        charts = run_chart_generate(state["daily"], state["weekly"], state["monthly"])
        span.output_summary = _sup._chart_summary(charts)
    return {"charts": charts}


def _n_interpret_report(state: TechnicalGraphState) -> dict:
    regime = _sup._to_regime_result(state["regime_result"])
    signal_summary = _sup._to_signal_summary(state["signal_result"], state["confidence"])
    _sup.check_deadline(state.get("deadline"), "interpret_report")
    result = _sup._interpret(
        state["llm_client"], regime=regime, signal=signal_summary,
        signals=state["signal_result"].technical_signals, risks=state["risk_items"],
        focus=state["focus"], trace=state["trace"], deadline=state.get("deadline"),
    )
    return {"regime": regime, "signal_summary": signal_summary, "interpretation": result}


def _n_build_output(state: TechnicalGraphState) -> dict:
    payload, result, rr = state["payload"], state["interpretation"], state["regime_result"]
    technical_signals = _sup._to_technical_signals(state["signal_result"].technical_signals, result.details)
    data_status = DataStatus.STALE_CACHE if state["used_stale"] else _sup._data_status(rr)

    # 선택적 1D intraday(best-effort) — 기존 tail 로직 그대로.
    intraday_fetcher = state.get("intraday_fetcher")
    if intraday_fetcher is None and _sup.INTRADAY_FETCH_ENABLED:
        intraday_fetcher = _sup.fetch_minute_ohlcv
    resolved = _sup._resolve_intraday(
        state.get("intraday_candles"), intraday_fetcher, payload.ticker, payload.as_of)
    intraday_charts, intraday_context = _sup._assemble_intraday(
        resolved, daily=state["daily"], as_of=payload.as_of, final_regime=state["regime"].final_regime)

    output = TechnicalAgentOutput(
        request_id=payload.request_id,
        ticker=payload.ticker,
        as_of=payload.as_of,
        source=state["source"],
        trace_id=state["trace_id"],
        data_status=data_status,
        regime=state["regime"],
        signal=state["signal_summary"],
        technical_signals=technical_signals,
        risk=RiskSummary(items=list(state["risk_items"])),
        charts=list(state["charts"]) + intraday_charts,
        interpretation=result.interpretation,
        verification=result.verification,
        intraday_context=intraday_context,
    )
    return {"output": output}


# ── conditional edge 라우터 (최소 2개) ────────────────────────────────────────
def _route_after_data(state: TechnicalGraphState) -> str:
    return "data_limited" if not state["daily"] else "continue"


def _route_after_regime(state: TechnicalGraphState) -> str:
    return "unavailable" if state["regime_result"].final_regime == Regime.UNAVAILABLE else "continue"


# ── graph build/compile (요청별 state·client를 담지 않음 → module-level 캐시) ──
def _build() -> object:
    g = StateGraph(TechnicalGraphState)
    g.add_node("preprocess", _n_preprocess)
    g.add_node("data_collect", _n_data_collect)
    g.add_node("output_data_limited", _n_output_data_limited)
    g.add_node("regime_classify", _n_regime_classify)
    g.add_node("output_regime_unavailable", _n_output_regime_unavailable)
    g.add_node("indicator_calculate", _n_indicator_calculate)
    g.add_node("signal_aggregate", _n_signal_aggregate)
    g.add_node("confidence_calculate", _n_confidence_calculate)
    g.add_node("risk_detect", _n_risk_detect)
    g.add_node("chart_generate", _n_chart_generate)
    g.add_node("interpret_report", _n_interpret_report)
    g.add_node("build_output", _n_build_output)

    g.add_edge(START, "preprocess")
    g.add_edge("preprocess", "data_collect")
    g.add_conditional_edges("data_collect", _route_after_data,
                            {"data_limited": "output_data_limited", "continue": "regime_classify"})
    g.add_edge("output_data_limited", END)
    g.add_conditional_edges("regime_classify", _route_after_regime,
                            {"unavailable": "output_regime_unavailable", "continue": "indicator_calculate"})
    g.add_edge("output_regime_unavailable", END)
    g.add_edge("indicator_calculate", "signal_aggregate")
    g.add_edge("signal_aggregate", "confidence_calculate")
    g.add_edge("confidence_calculate", "risk_detect")
    g.add_edge("risk_detect", "chart_generate")
    g.add_edge("chart_generate", "interpret_report")
    g.add_edge("interpret_report", "build_output")
    g.add_edge("build_output", END)
    # checkpointer 없음(단일 요청). **금지: state가 정화되기 전까지 checkpointer·persistent memory·
    # LangSmith state tracing을 켜지 않는다** — state에 원본 query(PII)·runtime client가 있어 저장/관측
    # 시 노출된다(langgraph_state.py 보안 경계). known debt: 결합·노드 분리는 후속 브랜치.
    return g.compile()


_COMPILED = None


def build_technical_graph() -> object:
    """compile된 graph를 반환(module-level 캐시). graph 안에 요청별 state·client는 담기지 않는다
    — runtime 의존성은 invoke(state)로만 흐르므로 캐시해도 안전하다."""
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = _build()
    return _COMPILED
