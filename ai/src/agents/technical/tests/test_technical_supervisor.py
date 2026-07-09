"""Technical Supervisor end-to-end 테스트 (test_plan §5.10 SUP-*). fake만 — 실 KIS/LLM 없음."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import pytest

from src.agents.technical.nodes import interpret_report as interp
from src.agents.technical.nodes.confidence_calculate import run_confidence_calculate
from src.agents.technical.nodes.indicator_calculate import run_indicator_calculate
from src.agents.technical.nodes.regime_classify import run_regime_classify
from src.agents.technical.nodes.risk_detect import run_risk_detect
from src.agents.technical.nodes.signal_aggregate import run_signal_aggregate
from src.agents.technical.schemas.contracts import TechnicalAgentInput, TechnicalSignal
from src.agents.technical.schemas.enums import DataStatus, GenerationSource, Regime
from src.agents.technical.schemas.intraday import IntradayCandle, IntradayChartData
from src.agents.technical.schemas.ohlcv import OHLCV
from src.agents.technical.services.kis_client import IntradayFetchResult
from src.agents.technical.supervisor import technical_supervisor as sup
from src.agents.technical.supervisor import pipeline_steps as steps

TICKER = "373220"  # LG에너지솔루션
AS_OF = "2026-06-30T14:30:00+09:00"


def _series(n: int, *, day_stride: int, start: str) -> list[OHLCV]:
    """진동(횡보) OHLCV — sideways/neutral 유도로 정상 흐름을 안정적으로 만든다."""
    d0 = date.fromisoformat(start)
    bars: list[OHLCV] = []
    for i in range(n):
        close = 100.0 + (2.0 if i % 2 else 0.0)
        bars.append(OHLCV(
            date=(d0 + timedelta(days=i * day_stride)).isoformat(),
            open=close, high=close + 1.0, low=close - 1.0, close=close,
            volume=1000 + i, trading_value=2_000_000_000 + i,
        ))
    return bars


DAILY = _series(120, day_stride=1, start="2023-01-02")
WEEKLY = _series(80, day_stride=7, start="2021-01-04")
MONTHLY = _series(36, day_stride=28, start="2020-01-06")

# 선택적 1D intraday 입력(이미 주어진 분봉 — KIS 호출 아님).
INTRADAY_CANDLES = [
    IntradayCandle(
        timestamp=f"2026-06-30T09:{i:02d}:00",
        open=100.0 + i * 0.1, high=100.0 + i * 0.1 + 0.3,
        low=100.0 + i * 0.1 - 0.3, close=100.0 + i * 0.1,
        volume=600 if i == 5 else 120, interval="1min",
    )
    for i in range(10)
]


def _input(query: str = "LG엔솔 지금 사도 돼?") -> TechnicalAgentInput:
    return TechnicalAgentInput(ticker=TICKER, query=query, request_id="req_1", as_of=AS_OF)


NORM_OK = json.dumps(
    {"normalized_question": "LG에너지솔루션의 최근 시세와 기술적 흐름을 확인합니다."}, ensure_ascii=False)
FOCUS_OK = json.dumps(
    {"analysis_focus": ["trend", "momentum"], "focus_summary": "추세와 모멘텀을 확인합니다."},
    ensure_ascii=False)
INTERP_BAD = json.dumps({"interpretation_text": "현재 시장은 흥미롭습니다.", "details": []}, ensure_ascii=False)


class ScriptedLlm:
    """호출 순서대로 응답을 돌려주는 fake. Exception이면 raise. 프롬프트를 기록."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _good_interp_response(daily, weekly, monthly) -> str:
    """결정론 노드로 확정값을 얻어, 검증 통과하는 interpret 응답(코드 fallback 문장)을 만든다."""
    regime_result = run_regime_classify(daily, weekly, monthly)
    bundle = run_indicator_calculate(daily)
    score = run_signal_aggregate(daily)
    conf = run_confidence_calculate(score, bundle, regime_result)
    risks = run_risk_detect(score, bundle, regime_result)
    regime = steps._to_regime_result(regime_result)
    signal_summary = steps._to_signal_summary(score, conf)
    text = interp.fallback_interpretation(regime=regime, signal=signal_summary, risks=risks).text
    details = [
        {"indicator": s.indicator.value,
         "detail": interp.fallback_detail(s.indicator, s.signal, s.metrics).detail}
        for s in score.technical_signals
    ]
    return json.dumps({"interpretation_text": text, "details": details}, ensure_ascii=False)


def _run(responses, *, fetcher=None, trace_id=None, agent_input=None,
         intraday_candles=None, intraday_fetcher=None):
    fetcher = fetcher or (lambda t, *, end_date=None: {"D": DAILY, "W": WEEKLY, "M": MONTHLY})
    return sup.run(agent_input or _input(), llm_client=ScriptedLlm(responses),
                   fetcher=fetcher, trace_id=trace_id,
                   intraday_candles=intraday_candles, intraday_fetcher=intraday_fetcher)


def _minute_fetcher(candles=None, *, previous_close=101.0, latest_price=None,
                    cumulative_volume=None, cumulative_trading_value=None):
    """테스트용 fake intraday fetcher — IntradayFetchResult를 돌려준다(KIS 없음)."""
    result = IntradayFetchResult(
        candles=list(INTRADAY_CANDLES if candles is None else candles),
        previous_close=previous_close, latest_price=latest_price,
        cumulative_volume=cumulative_volume, cumulative_trading_value=cumulative_trading_value,
    )
    return lambda ticker, *, as_of=None, **kw: result


@pytest.fixture(autouse=True)
def _intraday_flag_off(monkeypatch):
    """모든 supervisor 테스트를 결정론적으로 flag OFF에서 시작한다.

    INTRADAY_FETCH_ENABLED가 .env/환경변수로 켜져 있어도(테스트 env override) 기본 fetch가
    실 KIS를 때리지 않도록 강제한다. flag ON을 검증하는 테스트는 각자 True로 override한다.
    """
    monkeypatch.setattr(steps, "INTRADAY_FETCH_ENABLED", False)


# ── SUP-01·02: 정상 출력 · trace_id ─────────────────────────────────────────
def test_sup01_normal_output():
    out = _run([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD], trace_id="trace_x")
    assert out.ticker == TICKER
    assert out.source == "KIS"
    assert out.data_status == DataStatus.NORMAL
    assert out.trace_id == "trace_x"
    assert out.request_id == "req_1"


def test_sup02_trace_id_generated_when_absent():
    out = _run([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD])
    assert isinstance(out.trace_id, str) and out.trace_id


# ── SUP-03: normalize→focus 전달, 원본 query 미전달 ─────────────────────────
def test_sup03_query_not_passed_to_focus():
    client = ScriptedLlm([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD])
    sup.run(_input(query="LG엔솔 지금 사도 돼?"), llm_client=client,
            fetcher=lambda t, *, end_date=None: {"D": DAILY, "W": WEEKLY, "M": MONTHLY}, trace_id="t")
    normalize_prompt, focus_prompt = client.prompts[0], client.prompts[1]
    assert "지금 사도 돼" in normalize_prompt          # 원본 query는 노드 1에만
    assert "지금 사도 돼" not in focus_prompt           # 노드 2에는 전달 안 됨
    assert "LG에너지솔루션의 최근 시세" in focus_prompt  # normalized_question 전달됨


# ── SUP-04·05: 조립 정확성 · 확정값 불변 ────────────────────────────────────
def test_sup04_05_assembly_and_immutable_values():
    regime_result = run_regime_classify(DAILY, WEEKLY, MONTHLY)
    score = run_signal_aggregate(DAILY)
    out = _run([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD])

    # RegimeResult 1:1
    assert out.regime.final_regime == regime_result.final_regime
    assert out.regime.alignment_flag == regime_result.alignment_flag
    # SignalSummary
    assert out.signal.consensus == score.consensus
    assert out.signal.signal_score == score.signal_score
    # TechnicalSignal 확정값 불변(LLM은 detail만)
    by_ind = {s.indicator: s for s in score.technical_signals}
    assert len(out.technical_signals) == len(score.technical_signals)
    for ts in out.technical_signals:
        src = by_ind[ts.indicator]
        assert ts.signal == src.signal
        assert ts.value == src.value
        assert ts.weight == src.weight


# ── SUP-06·07·08: interpret 성공 / 재생성 / 폴백 ────────────────────────────
def test_sup06_interpret_success_llm():
    good = _good_interp_response(DAILY, WEEKLY, MONTHLY)
    out = _run([NORM_OK, FOCUS_OK, good])
    assert out.interpretation.source == GenerationSource.LLM
    assert out.verification.outcome.value == "passed"
    assert out.verification.regen_count == 0


def test_sup07_regenerate_success():
    good = _good_interp_response(DAILY, WEEKLY, MONTHLY)
    out = _run([NORM_OK, FOCUS_OK, INTERP_BAD, good])
    assert out.interpretation.source == GenerationSource.LLM_REGENERATED
    assert out.verification.regen_count == 1
    assert out.verification.outcome.value == "passed"


def test_sup08_template_fallback_after_regen():
    out = _run([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD])
    assert out.interpretation.source == GenerationSource.TEMPLATE_FALLBACK
    assert out.verification.outcome == out.verification.outcome.TEMPLATE_FALLBACK
    assert out.verification.regen_count == 1
    # 폴백이어도 detail은 지표 개수만큼 채워짐
    assert len(out.technical_signals) > 0
    assert all(ts.detail_source == GenerationSource.TEMPLATE_FALLBACK for ts in out.technical_signals)


# ── SUP-09·10: LLM 호출 예외 ────────────────────────────────────────────────
def test_sup09_interpret_call_exception_falls_back():
    out = _run([NORM_OK, FOCUS_OK, TimeoutError("llm down")])
    assert out.interpretation.source == GenerationSource.TEMPLATE_FALLBACK
    assert out.verification.regen_count == 0  # 호출 예외는 재생성 없이 폴백


def test_sup10_preprocess_call_exception_continues():
    good = _good_interp_response(DAILY, WEEKLY, MONTHLY)
    out = _run([TimeoutError("norm down"), TimeoutError("focus down"), good])
    assert out.data_status == DataStatus.NORMAL   # 전처리 실패해도 파이프라인 완주
    assert out.interpretation.source == GenerationSource.LLM


# ── SUP-11·12·13: data/regime unavailable ───────────────────────────────────
def test_sup11_empty_daily_data_limited():
    out = _run([NORM_OK, FOCUS_OK], fetcher=lambda t, *, end_date=None: {"D": [], "W": WEEKLY, "M": MONTHLY})
    assert out.data_status == DataStatus.DATA_LIMITED
    assert out.signal is None
    assert out.risk is None
    assert out.technical_signals == []
    assert out.charts == []
    assert out.interpretation.source == GenerationSource.TEMPLATE_FALLBACK
    assert out.regime.final_regime == Regime.UNAVAILABLE


def test_sup12_regime_unavailable_skips_signal():
    short_daily = _series(40, day_stride=1, start="2023-01-02")  # < MIN_DAILY_BARS(60)
    out = _run([NORM_OK, FOCUS_OK], fetcher=lambda t, *, end_date=None: {"D": short_daily, "W": WEEKLY, "M": MONTHLY})
    assert out.data_status == DataStatus.REGIME_UNAVAILABLE
    assert out.signal is None
    assert out.risk is None
    assert out.technical_signals == []
    assert {"3m", "1y", "5y"} <= {p.period.value for p in out.charts}  # D/W/M 3종 존재(1d는 조건부)


def test_sup13_wm_short_data_limited_but_analyzes():
    weekly_short = _series(5, day_stride=7, start="2025-01-06")   # < MIN_WEEKLY_BARS(12)
    monthly_short = _series(3, day_stride=28, start="2025-01-06")  # < MIN_MONTHLY_BARS(6)
    out = _run([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD],
               fetcher=lambda t, *, end_date=None: {"D": DAILY, "W": weekly_short, "M": monthly_short})
    assert out.data_status == DataStatus.DATA_LIMITED
    assert out.signal is not None            # 일봉 기준 분석 계속
    assert len(out.technical_signals) > 0


# ── SUP-14: value=None 계약 허용 ─────────────────────────────────────────────
def test_sup14_technical_signal_value_none_allowed():
    ts = TechnicalSignal(
        indicator="volume", signal="neutral", value=None, metrics=[],
        detail="거래량은 중립 신호로 확인됩니다.", detail_source=GenerationSource.LLM, weight=0.20)
    assert ts.value is None


# ── SUP-15: fetcher 예외는 전파 ──────────────────────────────────────────────
def test_sup15_fetcher_exception_propagates():
    def boom(_ticker, *, end_date=None):
        raise RuntimeError("KIS down")
    with pytest.raises(RuntimeError):
        _run([NORM_OK, FOCUS_OK], fetcher=boom)


# ── 계약 유효성 · extra field 금지 ──────────────────────────────────────────
def test_output_is_valid_contract_and_no_extra():
    out = _run([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD])
    dumped = out.model_dump()
    assert set(dumped) >= {"request_id", "ticker", "as_of", "source", "trace_id",
                           "data_status", "regime", "signal", "technical_signals",
                           "risk", "charts", "interpretation", "verification"}
    with pytest.raises(Exception):  # extra="forbid"
        TechnicalAgentInput(ticker=TICKER, query="q", request_id="r", as_of=AS_OF, extra_field=1)


# ── SUP-16: H2 granular(부분) fallback — 실패 detail만 template, 나머지 유지 ─
def _partial_bad_response(daily, weekly, monthly, *, bad_indicator="moving_average") -> str:
    """interpretation은 통과하되 한 indicator detail만 실패하는 응답."""
    regime_result = run_regime_classify(daily, weekly, monthly)
    bundle = run_indicator_calculate(daily)
    score = run_signal_aggregate(daily)
    conf = run_confidence_calculate(score, bundle, regime_result)
    risks = run_risk_detect(score, bundle, regime_result)
    regime = steps._to_regime_result(regime_result)
    signal_summary = steps._to_signal_summary(score, conf)
    text = interp.fallback_interpretation(regime=regime, signal=signal_summary, risks=risks).text
    details = []
    for s in score.technical_signals:
        if s.indicator.value == bad_indicator:
            details.append({"indicator": s.indicator.value, "detail": "이동평균선은 부정적입니다."})  # 신호 왜곡
        else:
            details.append({"indicator": s.indicator.value,
                            "detail": interp.fallback_detail(s.indicator, s.signal, s.metrics).detail})
    return json.dumps({"interpretation_text": text, "details": details}, ensure_ascii=False)


def test_sup16_partial_detail_fallback():
    bad = _partial_bad_response(DAILY, WEEKLY, MONTHLY)
    out = _run([NORM_OK, FOCUS_OK, bad, bad])  # 1차·재생성 모두 같은 부분 실패
    assert out.interpretation.source == GenerationSource.LLM_REGENERATED  # interpretation은 유지
    by_ind = {ts.indicator.value: ts for ts in out.technical_signals}
    assert by_ind["moving_average"].detail_source == GenerationSource.TEMPLATE_FALLBACK  # 실패분만 폴백
    others = [ts for k, ts in by_ind.items() if k != "moving_average"]
    assert others and all(ts.detail_source == GenerationSource.LLM_REGENERATED for ts in others)
    assert out.verification.outcome == out.verification.outcome.TEMPLATE_FALLBACK


# ── SUP-17: L2 — value=None이 조립 경로에서 보존됨 ──────────────────────────
def test_sup17_to_technical_signals_preserves_none():
    from src.agents.technical.nodes.interpret_report import DetailResult
    from src.agents.technical.schemas.enums import IndicatorType, Signal
    from src.agents.technical.synthesis.signal_score import IndicatorSignalResult
    isr = IndicatorSignalResult(IndicatorType.VOLUME, Signal.NEUTRAL, None, [], 0.20)
    detail = DetailResult("volume", "거래량은 중립 신호로 확인됩니다.", GenerationSource.LLM)
    out = steps._to_technical_signals([isr], [detail])
    assert out[0].value is None  # None 보존(0.0 날조 없음)


# ── SUP-18: M2 — 비-LLM 예외는 전파(broad catch 아님) ───────────────────────
def test_sup18_non_llm_error_propagates():
    # query="" → run_normalize_question이 ValueError(호출 전 입력 오류) → supervisor가 삼키지 않음
    with pytest.raises(ValueError):
        _run([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD],
             agent_input=TechnicalAgentInput(ticker=TICKER, query="", request_id="r", as_of=AS_OF))


# ── SUP-19: H1 — analysis_focus가 interpret payload에 힌트로 들어감 ─────────
def test_sup19_focus_hint_in_interpret_payload():
    focus_json = json.dumps(
        {"analysis_focus": ["momentum", "volume"], "focus_summary": "모멘텀과 거래량을 봅니다."},
        ensure_ascii=False)
    client = ScriptedLlm([NORM_OK, focus_json, INTERP_BAD, INTERP_BAD])
    sup.run(_input(), llm_client=client,
            fetcher=lambda t, *, end_date=None: {"D": DAILY, "W": WEEKLY, "M": MONTHLY}, trace_id="t")
    interpret_prompt = client.prompts[2]
    assert "analysis_focus" in interpret_prompt
    assert "momentum" in interpret_prompt


# ── DATE-08: as_of가 fetcher end_date로 스레딩되고 output.as_of와 일치 ───────
def test_sup_as_of_threaded_to_fetcher_end_date():
    seen = {}

    def rec_fetcher(ticker, *, end_date=None):
        seen["end_date"] = end_date
        return {"D": DAILY, "W": WEEKLY, "M": MONTHLY}
    out = sup.run(_input(), llm_client=ScriptedLlm([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD]),
                  fetcher=rec_fetcher, trace_id="t")
    assert seen["end_date"] == date(2026, 6, 30)      # AS_OF 날짜가 fetcher로 전달
    assert out.as_of.date() == seen["end_date"]        # output.as_of와 fetcher end_date 일치


def test_sup_as_of_change_changes_end_date():
    seen = []

    def rec_fetcher(ticker, *, end_date=None):
        seen.append(end_date)
        return {"D": DAILY, "W": WEEKLY, "M": MONTHLY}
    for as_of in ("2026-06-30T14:30:00+09:00", "2025-01-15T09:00:00+09:00"):
        sup.run(TechnicalAgentInput(ticker=TICKER, query="q", request_id="r", as_of=as_of),
                llm_client=ScriptedLlm([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD]),
                fetcher=rec_fetcher, trace_id="t")
    assert seen == [date(2026, 6, 30), date(2025, 1, 15)]  # as_of 바뀌면 end_date도 바뀜


# ── M1: REGEN_MAX_COUNT만큼만 재생성(하드코딩 아님) ─────────────────────────
def test_regen_count_matches_config():
    from src.agents.technical.config import REGEN_MAX_COUNT
    client = ScriptedLlm([NORM_OK, FOCUS_OK] + [INTERP_BAD] * (REGEN_MAX_COUNT + 1))
    sup.run(_input(), llm_client=client,
            fetcher=lambda t, *, end_date=None: {"D": DAILY, "W": WEEKLY, "M": MONTHLY}, trace_id="t")
    # normalize + focus + (1차 interpret + REGEN_MAX_COUNT 재생성)
    assert len(client.prompts) == 2 + (1 + REGEN_MAX_COUNT)


def _fetcher(t, *, end_date=None):
    return {"D": DAILY, "W": WEEKLY, "M": MONTHLY}


# ── 미세 갭 1: REGEN_MAX_COUNT=0이면 regenerate 호출이 없어야 한다 ───────────
def test_regen_max_count_zero_skips_regenerate(monkeypatch):
    monkeypatch.setattr(steps, "REGEN_MAX_COUNT", 0)
    # 1차 interpret 검증 실패(INTERP_BAD). 응답을 3개만 준다 — regenerate가 호출되면 pop 실패로 드러남.
    client = ScriptedLlm([NORM_OK, FOCUS_OK, INTERP_BAD])
    out = sup.run(_input(), llm_client=client, fetcher=_fetcher, trace_id="t")
    assert len(client.prompts) == 3  # normalize + focus + interpret 1회 (regenerate 없음)
    assert out.interpretation.source == GenerationSource.TEMPLATE_FALLBACK
    assert out.verification.outcome == out.verification.outcome.TEMPLATE_FALLBACK
    assert out.verification.regen_count == 0


def test_regen_max_count_one_regenerates_once(monkeypatch):
    monkeypatch.setattr(steps, "REGEN_MAX_COUNT", 1)
    client = ScriptedLlm([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD])
    out = sup.run(_input(), llm_client=client, fetcher=_fetcher, trace_id="t")
    assert len(client.prompts) == 4  # normalize + focus + interpret + regenerate 1회
    assert out.verification.regen_count == 1


# ── 미세 갭 2: analysis_focus가 바뀌어도 코드 확정값은 불변 ──────────────────
def test_focus_change_does_not_alter_confirmed_values():
    focus_a = json.dumps({"analysis_focus": ["trend"], "focus_summary": "추세를 봅니다."},
                         ensure_ascii=False)
    focus_b = json.dumps({"analysis_focus": ["momentum", "volume"], "focus_summary": "모멘텀과 거래량을 봅니다."},
                         ensure_ascii=False)

    def _run_with_focus(focus_json):
        client = ScriptedLlm([NORM_OK, focus_json, INTERP_BAD, INTERP_BAD])
        out = sup.run(_input(), llm_client=client, fetcher=_fetcher, trace_id="t")
        return out, client.prompts[2]  # prompts[2] = interpret payload

    out_a, interp_prompt_a = _run_with_focus(focus_a)
    out_b, interp_prompt_b = _run_with_focus(focus_b)

    # focus hint는 interpret payload에 반영되고 서로 다르다
    assert "trend" in interp_prompt_a and "momentum" in interp_prompt_b
    assert interp_prompt_a != interp_prompt_b

    # 하지만 코드 확정값(regime·signal·technical_signals value/metrics/weight·risk·chart)은 불변
    assert out_a.regime == out_b.regime
    assert out_a.signal == out_b.signal
    assert out_a.risk == out_b.risk
    assert out_a.charts == out_b.charts
    a_by = {ts.indicator: ts for ts in out_a.technical_signals}
    b_by = {ts.indicator: ts for ts in out_b.technical_signals}
    assert a_by.keys() == b_by.keys()
    for ind, ts_a in a_by.items():
        ts_b = b_by[ind]
        assert (ts_a.signal, ts_a.value, ts_a.metrics, ts_a.weight) == \
               (ts_b.signal, ts_b.value, ts_b.metrics, ts_b.weight)


# ── SUP intraday: 선택적 1D 조립(입력 있을 때만) ────────────────────────────
_INTRA = [NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD]


def test_intraday_absent_charts_dwm_only():
    out = _run(_INTRA)
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y"}
    assert out.intraday_context is None


def test_intraday_present_adds_1d_chart():
    out = _run(_INTRA, intraday_candles=INTRADAY_CANDLES)
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y", "1d"}
    one_d = next(p for p in out.charts if p.period.value == "1d")
    assert isinstance(one_d.chart_data, IntradayChartData)
    assert one_d.chart_data.candle_unit == "1min"
    out.model_dump_json()  # 직렬화 가능(판별 유니온)


def test_intraday_context_set_with_hint_and_alignment():
    out = _run(_INTRA, intraday_candles=INTRADAY_CANDLES)
    assert out.intraday_context is not None
    assert out.intraday_context.intraday_regime_hint is not None
    assert out.intraday_context.regime_alignment is not None


def test_final_regime_unchanged_by_intraday():
    without = _run(_INTRA)
    with_intraday = _run(_INTRA, intraday_candles=INTRADAY_CANDLES)
    assert with_intraday.regime == without.regime  # RegimeResult 전체 동일(final_regime 포함)


def test_confidence_signal_unchanged_by_intraday():
    without = _run(_INTRA)
    with_intraday = _run(_INTRA, intraday_candles=INTRADAY_CANDLES)
    assert with_intraday.signal == without.signal  # signal_score·confidence 동일
    assert with_intraday.intraday_context.confidence_adjustment == 0.0
    assert with_intraday.intraday_context.signal_score_adjustment == 0.0


def test_intraday_failure_does_not_break_dwm(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("intraday build failed")
    monkeypatch.setattr(steps, "build_intraday_chart_payload", boom)
    out = _run(_INTRA, intraday_candles=INTRADAY_CANDLES)
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y"}  # D/W/M 유지
    assert out.intraday_context is None  # 조립 실패 → 붙이지 않음


# ── SUP intraday: KIS fetcher 연결(커밋 14) ──────────────────────────────────
def test_intraday_fetcher_success_adds_1d_and_context():
    out = _run(_INTRA, intraday_fetcher=_minute_fetcher())
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y", "1d"}
    assert out.intraday_context is not None


def test_intraday_fetcher_previous_close_used():
    # fetcher previous_close=200 → return_pct는 200 기준(일봉 fallback 아님)
    out = _run(_INTRA, intraday_fetcher=_minute_fetcher(previous_close=200.0))
    ctx = out.intraday_context
    assert ctx.previous_close == 200.0  # INTRADAY_CANDLES last close=100.9
    assert ctx.intraday_return_pct == pytest.approx((100.9 - 200.0) / 200.0 * 100)


def test_intraday_fetcher_previous_close_none_falls_back_to_daily():
    out = _run(_INTRA, intraday_fetcher=_minute_fetcher(previous_close=None))
    # DAILY[-1].close (i=119 홀수 → 102.0) 로 fallback
    assert out.intraday_context.previous_close == 102.0


def test_intraday_fetcher_empty_candles_dwm_only():
    out = _run(_INTRA, intraday_fetcher=_minute_fetcher(candles=[]))
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y"}
    assert out.intraday_context is None


def test_intraday_fetcher_exception_does_not_break_dwm():
    def boom(ticker, *, as_of=None, **kw):
        raise RuntimeError("kis intraday down")
    out = _run(_INTRA, intraday_fetcher=boom)
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y"}  # D/W/M 정상
    assert out.intraday_context is None


def test_direct_candles_take_precedence_over_fetcher():
    called = {"n": 0}

    def counting(ticker, *, as_of=None, **kw):
        called["n"] += 1
        return IntradayFetchResult([], None, None, None, None)

    out = _run(_INTRA, intraday_candles=INTRADAY_CANDLES, intraday_fetcher=counting)
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y", "1d"}  # 직접 주입이 1d 생성
    assert called["n"] == 0  # fetcher 호출 안 함(직접 주입 우선)


def test_final_regime_and_signal_unchanged_by_fetcher():
    without = _run(_INTRA)
    with_fetch = _run(_INTRA, intraday_fetcher=_minute_fetcher())
    assert with_fetch.regime == without.regime      # final_regime 등 불변
    assert with_fetch.signal == without.signal       # top-level confidence/signal_score 불변
    # 보정값은 context 내부에만
    assert with_fetch.intraday_context.signal_score_adjustment == 0.0


# ── SUP intraday: INTRADAY_FETCH_ENABLED flag gate (C안) ─────────────────────
def _default_minute_stub(called: dict, *, candles=None, previous_close=101.0):
    """steps.fetch_minute_ohlcv 대체용 — 호출 카운트를 기록한다."""
    def stub(ticker, *, as_of=None, **kw):
        called["n"] += 1
        return IntradayFetchResult(
            candles=list(INTRADAY_CANDLES if candles is None else candles),
            previous_close=previous_close, latest_price=None,
            cumulative_volume=None, cumulative_trading_value=None,
        )
    return stub


def test_flag_off_default_no_intraday(monkeypatch):
    # flag 기본 False → 명시 fetcher/candles 없으면 기본 minute fetcher를 쓰지 않는다.
    called = {"n": 0}
    monkeypatch.setattr(steps, "fetch_minute_ohlcv", _default_minute_stub(called))
    out = _run(_INTRA)
    assert called["n"] == 0
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y"}
    assert out.intraday_context is None


def test_flag_on_uses_default_minute_fetcher(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(steps, "INTRADAY_FETCH_ENABLED", True)
    monkeypatch.setattr(steps, "fetch_minute_ohlcv", _default_minute_stub(called))
    out = _run(_INTRA)  # fetcher·candles 미주입
    assert called["n"] == 1  # flag ON → 기본 fetcher 호출
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y", "1d"}
    assert out.intraday_context is not None


def test_flag_on_direct_candles_skip_default_fetcher(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(steps, "INTRADAY_FETCH_ENABLED", True)
    monkeypatch.setattr(steps, "fetch_minute_ohlcv", _default_minute_stub(called))
    out = _run(_INTRA, intraday_candles=INTRADAY_CANDLES)
    assert called["n"] == 0  # 직접 주입 우선 → 기본 fetcher 미호출
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y", "1d"}


def test_flag_on_explicit_fetcher_takes_precedence(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(steps, "INTRADAY_FETCH_ENABLED", True)
    monkeypatch.setattr(steps, "fetch_minute_ohlcv", _default_minute_stub(called))
    out = _run(_INTRA, intraday_fetcher=_minute_fetcher(previous_close=200.0))
    assert called["n"] == 0  # 명시 fetcher 우선 → 기본 미호출
    assert out.intraday_context.previous_close == 200.0


def test_flag_on_default_fetcher_exception_isolated(monkeypatch):
    def boom(ticker, *, as_of=None, **kw):
        raise RuntimeError("kis intraday down")
    monkeypatch.setattr(steps, "INTRADAY_FETCH_ENABLED", True)
    monkeypatch.setattr(steps, "fetch_minute_ohlcv", boom)
    out = _run(_INTRA)
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y"}  # D/W/M 정상
    assert out.intraday_context is None


def test_flag_on_default_empty_candles_dwm_only(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(steps, "INTRADAY_FETCH_ENABLED", True)
    monkeypatch.setattr(steps, "fetch_minute_ohlcv", _default_minute_stub(called, candles=[]))
    out = _run(_INTRA)
    assert called["n"] == 1
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y"}
    assert out.intraday_context is None


def test_flag_on_final_regime_and_signal_unchanged(monkeypatch):
    without = _run(_INTRA)
    monkeypatch.setattr(steps, "INTRADAY_FETCH_ENABLED", True)
    monkeypatch.setattr(steps, "fetch_minute_ohlcv", _default_minute_stub({"n": 0}))
    with_flag = _run(_INTRA)
    assert with_flag.regime == without.regime      # final_regime 등 불변
    assert with_flag.signal == without.signal       # top-level confidence/signal_score 불변
    assert with_flag.intraday_context.signal_score_adjustment == 0.0


# ── SUP intraday: as_of 날짜 정합성 가드 ─────────────────────────────────────
# AS_OF = 2026-06-30. INTRADAY_CANDLES 는 2026-06-30(일치), 아래는 다른 날짜(2026-07-06, 불일치).
_INTRADAY_OTHER_DATE = [
    IntradayCandle(
        timestamp=f"2026-07-06T09:{i:02d}:00",
        open=100.0 + i * 0.1, high=100.0 + i * 0.1 + 0.3,
        low=100.0 + i * 0.1 - 0.3, close=100.0 + i * 0.1,
        volume=120, interval="1min",
    )
    for i in range(10)
]


def test_intraday_matches_as_of_helper():
    d = date(2026, 6, 30)
    assert steps._intraday_matches_as_of(INTRADAY_CANDLES, d) is True         # 같은 날짜
    assert steps._intraday_matches_as_of(_INTRADAY_OTHER_DATE, d) is False    # 다른 날짜
    assert steps._intraday_matches_as_of(_INTRADAY_OTHER_DATE, None) is True  # as_of None → 기존 동작
    assert steps._intraday_matches_as_of([], d) is True                       # empty → True(상위 처리)
    assert steps._intraday_matches_as_of(INTRADAY_CANDLES + _INTRADAY_OTHER_DATE, d) is False  # 일부만 다름


def test_intraday_matches_as_of_uses_kst_date_for_tzaware():
    """tz-aware as_of(UTC)는 KST 날짜로 비교한다. candle 은 KST 장 시각(2026-06-30 09:xx).

    회귀: UTC 날짜로 비교하면 06-30 00:00~09:00 KST(=06-29 UTC) 구간에서 정상 당일 분봉이
    전날로 어긋나 폐기됐다."""
    from datetime import datetime, timezone
    # 2026-06-30 00:30 KST == 2026-06-29 15:30 UTC → UTC.date()면 06-29(불일치), KST면 06-30(일치)
    as_of_utc = datetime(2026, 6, 29, 15, 30, tzinfo=timezone.utc)
    assert steps._intraday_matches_as_of(INTRADAY_CANDLES, as_of_utc) is True


def test_intraday_date_match_included():
    out = _run(_INTRA, intraday_candles=INTRADAY_CANDLES)  # 2026-06-30 == as_of.date()
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y", "1d"}
    assert out.intraday_context is not None


def test_intraday_date_mismatch_omitted_direct():
    out = _run(_INTRA, intraday_candles=_INTRADAY_OTHER_DATE)  # 2026-07-06 != as_of 2026-06-30
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y"}
    assert out.intraday_context is None


def test_intraday_date_mismatch_omitted_fetcher():
    out = _run(_INTRA, intraday_fetcher=_minute_fetcher(candles=_INTRADAY_OTHER_DATE))
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y"}
    assert out.intraday_context is None


def test_intraday_date_mismatch_keeps_dwm_and_regime():
    base = _run(_INTRA)
    mm = _run(_INTRA, intraday_candles=_INTRADAY_OTHER_DATE)
    assert {p.period.value for p in mm.charts} == {"3m", "1y", "5y"}
    assert mm.regime == base.regime      # final_regime 등 불변
    assert mm.signal == base.signal       # top-level confidence/signal_score 불변


# ── SUP intraday: output1 metadata 보존 (fetcher path) ───────────────────────
def test_intraday_fetcher_metadata_flows_to_context():
    out = _run(_INTRA, intraday_fetcher=_minute_fetcher(
        latest_price=99999.0, cumulative_volume=555, cumulative_trading_value=777))
    ctx = out.intraday_context
    assert ctx.latest_price == 99999.0            # output1 정본 우선(마지막 candle close 아님)
    assert ctx.cumulative_volume == 555            # output1.acml_vol 우선(sum 아님)
    assert ctx.cumulative_trading_value == 777      # output1.acml_tr_pbmn 보존


def test_intraday_direct_candles_use_candle_fallback():
    out = _run(_INTRA, intraday_candles=INTRADAY_CANDLES)  # 직접 주입 → metadata 없음
    ctx = out.intraday_context
    assert ctx.latest_price == pytest.approx(100.0 + 9 * 0.1)  # 마지막 candle close
    assert ctx.cumulative_volume == 120 * 9 + 600              # sum(candle volume)
    assert ctx.cumulative_trading_value is None                 # metadata 없음 → None


# ── SUP intraday: best-effort 실패 로깅 (원인 기록, D/W/M 정상) ──────────────
def _intraday_warnings(caplog):
    return [r for r in caplog.records
            if r.levelno == logging.WARNING and r.getMessage().startswith("intraday_")]


def test_intraday_fetch_failure_logs_warning(caplog):
    def boom(ticker, *, as_of=None, **kw):
        raise RuntimeError("kis intraday down")
    with caplog.at_level(logging.WARNING, logger="src.agents.technical.supervisor.technical_supervisor"):
        out = _run(_INTRA, intraday_fetcher=boom)
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y"}  # D/W/M 정상
    assert out.intraday_context is None
    recs = _intraday_warnings(caplog)
    assert any(r.getMessage() == "intraday_fetch_failed" for r in recs)  # 원인 기록됨
    rec = next(r for r in recs if r.getMessage() == "intraday_fetch_failed")
    assert rec.exc_info is not None                      # exc_info 포함
    assert rec.stage == "resolve_intraday" and rec.ticker == TICKER
    # secret/token/account 미포함(로그 extra에 그런 필드 자체가 없어야 함)
    for attr in ("appkey", "appsecret", "api_key", "api_secret", "token", "account_no"):
        assert not hasattr(rec, attr)


def test_intraday_assemble_failure_logs_warning(monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("assemble boom")
    monkeypatch.setattr(steps, "build_intraday_chart_payload", boom)
    with caplog.at_level(logging.WARNING, logger="src.agents.technical.supervisor.technical_supervisor"):
        out = _run(_INTRA, intraday_candles=INTRADAY_CANDLES)
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y"}  # D/W/M 정상
    assert out.intraday_context is None
    recs = _intraday_warnings(caplog)
    assert any(r.getMessage() == "intraday_assemble_failed" for r in recs)
    rec = next(r for r in recs if r.getMessage() == "intraday_assemble_failed")
    assert rec.exc_info is not None and rec.stage == "assemble_intraday"


# ── RES: cache-aware D/W/M 수집 (feat/technical-cache-service) ──────────────────
from src.agents.technical.config import REGEN_MAX_COUNT  # noqa: E402
from src.agents.technical.schemas.enums import DataStatus as _DataStatus  # noqa: E402
from src.agents.technical.services.cache_service import CacheLookup  # noqa: E402
from src.agents.technical.services.kis_client import KisApiError  # noqa: E402


class _FakeCache:
    """supervisor 배선용 fake 캐시. entries={tf: ("fresh"|"stale", candles)}. now 무시(결정론)."""

    def __init__(self, entries=None):
        self._entries = dict(entries or {})
        self.sets = []

    def get(self, ticker, tf, as_of_id, *, now):
        e = self._entries.get(tf)
        return CacheLookup(e[0], e[1]) if e is not None else CacheLookup("miss")

    def set(self, ticker, tf, as_of_id, candles, *, now):
        self.sets.append(tf)
        self._entries[tf] = ("fresh", list(candles))


_DWM_FRESH = {"D": ("fresh", DAILY), "W": ("fresh", WEEKLY), "M": ("fresh", MONTHLY)}
_DWM_STALE = {"D": ("stale", DAILY), "W": ("stale", WEEKLY), "M": ("stale", MONTHLY)}


def _run_cache(cache, *, fetcher):
    responses = [NORM_OK, FOCUS_OK] + [INTERP_BAD] * (REGEN_MAX_COUNT + 1)
    return sup.run(_input(), llm_client=ScriptedLlm(responses), fetcher=fetcher, cache=cache, trace_id="t")


def _recording_fetcher():
    calls = {"n": 0}

    def fetch(t, *, end_date=None):
        calls["n"] += 1
        return {"D": DAILY, "W": WEEKLY, "M": MONTHLY}
    return fetch, calls


def _kis_fail_fetcher(t, *, end_date=None):
    raise KisApiError("KIS 최대 재시도 초과")     # 복구 가능한 KIS 통신 실패


def _envelope_bad_fetcher(t, *, end_date=None):
    return {"D": DAILY}                            # W/M 누락 → run_data_collect envelope ValueError


def _type_error_fetcher(t, *, end_date=None):
    raise TypeError("programming error")


# ── 기본: fresh hit / miss→write / 하위호환 ────────────────────────────────────
def test_res_cache_hit_skips_fetcher():
    fetch, calls = _recording_fetcher()
    out = _run_cache(_FakeCache(_DWM_FRESH), fetcher=fetch)
    assert calls["n"] == 0                       # fresh 캐시 → KIS 미호출
    assert out.source == "KIS"
    assert out.data_status != _DataStatus.STALE_CACHE


def test_res_cache_miss_fetches_and_writes():
    fetch, calls = _recording_fetcher()
    cache = _FakeCache()
    out = _run_cache(cache, fetcher=fetch)
    assert calls["n"] == 1                        # miss → KIS 1회
    assert cache.sets == ["D", "W", "M"]          # 3종 write
    assert out.source == "KIS"


def test_res_no_cache_is_backward_compatible():
    fetch, calls = _recording_fetcher()
    out = sup.run(_input(), llm_client=ScriptedLlm([NORM_OK, FOCUS_OK] + [INTERP_BAD] * (REGEN_MAX_COUNT + 1)),
                  fetcher=fetch, trace_id="t")
    assert calls["n"] == 1 and out.source == "KIS"


# ── stale 폴백은 KisApiError만 허용, 나머지는 전파(fail-fast) ──────────────────
def test_res_kis_apierror_uses_stale_cache():
    out = _run_cache(_FakeCache(_DWM_STALE), fetcher=_kis_fail_fetcher)
    assert out.source == "KIS (stale)"
    assert out.data_status == _DataStatus.STALE_CACHE
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y"}


def test_res_envelope_error_propagates_even_with_stale():
    with pytest.raises(ValueError):              # envelope 오류는 stale로 덮지 않음
        _run_cache(_FakeCache(_DWM_STALE), fetcher=_envelope_bad_fetcher)


def test_res_type_error_propagates_even_with_stale():
    with pytest.raises(TypeError):              # 프로그래밍 오류 전파
        _run_cache(_FakeCache(_DWM_STALE), fetcher=_type_error_fetcher)


def test_res_bad_as_of_rejected_at_input():
    # 미래 as_of는 이제 입력 계약(TechnicalAgentInput validator)에서 fail-fast로 거절된다
    # (KIS/OpenAI/cache 이전). endpoint에서는 422 VALIDATION_ERROR로 매핑된다.
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        TechnicalAgentInput(ticker=TICKER, query="q", request_id="r",
                            as_of="2099-01-01T00:00:00+09:00")


# ── per-timeframe stale 재구성 (D 필수 · W/M optional) ────────────────────────
def test_res_kis_fail_d_stale_only_continues():
    # KIS 실패 + D stale만 있음(W/M 없음) → 실패하지 않고 제한 분석 진행
    out = _run_cache(_FakeCache({"D": ("stale", DAILY)}), fetcher=_kis_fail_fetcher)
    assert out.source == "KIS (stale)"
    assert out.data_status == _DataStatus.STALE_CACHE
    assert {"3m", "1y", "5y"} <= {p.period.value for p in out.charts}  # 산출됨(W/M 빈 데이터 허용)


def test_res_kis_fail_no_d_stale_propagates():
    # KIS 실패 + D stale 없음(W/M만 있음) → 재구성 불가 → KIS 예외 전파
    with pytest.raises(KisApiError):
        _run_cache(_FakeCache({"W": ("stale", WEEKLY), "M": ("stale", MONTHLY)}), fetcher=_kis_fail_fetcher)


def test_res_mixed_fresh_and_stale_marks_stale():
    # D fresh + W/M stale인데 전체 fresh가 아니라 KIS 시도 → 실패 → per-tf 재구성(D fresh·W/M stale)
    entries = {"D": ("fresh", DAILY), "W": ("stale", WEEKLY), "M": ("stale", MONTHLY)}
    out = _run_cache(_FakeCache(entries), fetcher=_kis_fail_fetcher)
    assert out.source == "KIS (stale)"             # 하나라도 stale이면 stale 표기
    assert out.data_status == _DataStatus.STALE_CACHE


def test_res_redis_down_kis_ok_uses_live():
    # Redis get 장애는 cache_service가 miss로 흡수 → miss 캐시로 모사. KIS 성공 → live.
    fetch, calls = _recording_fetcher()
    out = _run_cache(_FakeCache(), fetcher=fetch)
    assert calls["n"] == 1 and out.source == "KIS"


def test_res_redis_down_kis_fail_no_stale_propagates():
    with pytest.raises(KisApiError):
        _run_cache(_FakeCache(), fetcher=_kis_fail_fetcher)   # stale 없음 → KIS 실패 전파


# ── TRACE: trace_sink 주입 관측 (feat/technical-trace-logger) ──────────────────
from src.agents.technical.nodes._llm_utils import LlmCallError  # noqa: E402
from src.agents.technical.observability.trace_logger import InMemoryTraceSink  # noqa: E402


def _types(events):
    return [(e["node"], e["event_type"], e["status"]) for e in events]


def _run_trace(responses, *, fetcher=None, cache=None, agent_input=None):
    sink = InMemoryTraceSink()
    out = sup.run(
        agent_input or _input(), llm_client=ScriptedLlm(responses),
        fetcher=fetcher or (lambda t, *, end_date=None: {"D": DAILY, "W": WEEKLY, "M": MONTHLY}),
        cache=cache, trace_id="t", trace_sink=sink,
    )
    return out, sink.events


def test_trace_run_started_and_succeeded():
    out, events = _run_trace([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD])
    assert events[0]["event_type"] == "trace_start"
    assert events[-1]["event_type"] == "trace_end" and events[-1]["status"] == "success"
    assert events[-1]["output_summary"]["status"] == "completed"
    assert events[-1]["output_summary"]["data_status"] == out.data_status.value
    # 모든 event가 같은 trace_id, event_id 순번 부여
    assert {e["trace_id"] for e in events} == {"t"}
    assert all(e["event_id"] for e in events)


def test_trace_query_hash_excludes_plaintext():
    _out, events = _run_trace([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD],
                              agent_input=_input(query="LG엔솔 지금 사도 돼?"))
    dumped = json.dumps(events, ensure_ascii=False)
    assert "지금 사도" not in dumped                      # 원문 평문 미기록
    assert events[0]["input_summary"]["original_query_hash"].startswith("sha256:")


def test_trace_major_node_events_present():
    _out, events = _run_trace([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD])
    seen = {(n, t) for n, t, _ in _types(events)}
    for node in ("normalize_question", "focus_analysis", "data_collect", "regime_classify",
                 "indicator_calculate", "signal_aggregate", "confidence_calculate",
                 "risk_detect", "chart_generate", "interpret_report"):
        assert (node, "node_start") in seen and (node, "node_end") in seen
    # node_end에 duration_ms가 기록됨
    ends = [e for e in events if e["event_type"] == "node_end" and e["status"] == "success"]
    assert ends and all(isinstance(e["duration_ms"], int) for e in ends)


def test_trace_run_failed_reraises_and_records():
    sink = InMemoryTraceSink()
    with pytest.raises(TypeError):
        sup.run(_input(), llm_client=ScriptedLlm([NORM_OK, FOCUS_OK]),
                fetcher=_type_error_fetcher, trace_id="t", trace_sink=sink)
    end = sink.events[-1]
    assert end["event_type"] == "trace_end" and end["status"] == "failed"
    assert end["error"]["error_type"] == "TypeError"       # safe_error 요약


def test_trace_cache_hit_summary():
    _out, events = _run_trace([NORM_OK, FOCUS_OK] + [INTERP_BAD] * (REGEN_MAX_COUNT + 1),
                              cache=_FakeCache(_DWM_FRESH))
    dc_end = next(e for e in events if e["node"] == "data_collect" and e["event_type"] == "node_end")
    assert dc_end["output_summary"]["source"] == "cache"
    assert dc_end["output_summary"]["cache_hit_by_period"] == {"D": True, "W": True, "M": True}


def test_trace_stale_fallback_event():
    _out, events = _run_trace([NORM_OK, FOCUS_OK] + [INTERP_BAD] * (REGEN_MAX_COUNT + 1),
                              cache=_FakeCache(_DWM_STALE), fetcher=_kis_fail_fetcher)
    fb = [e for e in events if e["event_type"] == "fallback" and e["node"] == "data_collect"]
    assert fb and fb[0]["output_summary"]["fallback_type"] == "stale_cache"


def test_trace_regime_unavailable_skips_code_nodes():
    short_daily = _series(40, day_stride=1, start="2023-01-02")
    _out, events = _run_trace(
        [NORM_OK, FOCUS_OK],
        fetcher=lambda t, *, end_date=None: {"D": short_daily, "W": WEEKLY, "M": MONTHLY})
    skipped = {e["node"] for e in events if e["status"] == "skipped"}
    # 국면분류(gate)가 지표계산보다 먼저라 unavailable이면 indicator도 스킵(trace_schema §9.1)
    assert skipped == {"indicator_calculate", "signal_aggregate", "confidence_calculate", "risk_detect"}
    # chart_generate는 skip되지 않고 실행됨(unavailable 경로에서도 차트 제공)
    assert any(e["node"] == "chart_generate" and e["event_type"] == "node_end"
               and e["status"] == "success" for e in events)


def test_trace_interpret_template_fallback_event():
    # INTERP_BAD를 재생성까지 반복 → regen 소진 → template fallback 이벤트
    _out, events = _run_trace([NORM_OK, FOCUS_OK] + [INTERP_BAD] * (REGEN_MAX_COUNT + 1))
    retries = [e for e in events if e["event_type"] == "retry" and e["node"] == "interpret_report"]
    fb = [e for e in events if e["event_type"] == "fallback" and e["node"] == "interpret_report"]
    assert len(retries) == REGEN_MAX_COUNT               # 재생성 시도마다 retry
    assert fb and fb[0]["output_summary"]["fallback_type"] == "template_fallback"


def test_trace_llm_call_failure_preprocess_fallback():
    _out, events = _run_trace([LlmCallError("boom"), FOCUS_OK, INTERP_BAD, INTERP_BAD])
    fb = [e for e in events if e["event_type"] == "fallback" and e["node"] == "normalize_question"]
    assert fb and fb[0]["output_summary"]["fallback_type"] == "template_fallback"


def test_trace_validation_event_per_attempt():
    # INTERP_BAD 반복 → attempt마다 validation 이벤트(검증③ 결과)가 기록됨
    _out, events = _run_trace([NORM_OK, FOCUS_OK] + [INTERP_BAD] * (REGEN_MAX_COUNT + 1))
    vals = [e for e in events if e["event_type"] == "validation" and e["node"] == "interpret_report"]
    assert len(vals) == REGEN_MAX_COUNT + 1               # 1차 + 재생성 각각 검증
    v0 = vals[0]["output_summary"]
    assert v0["attempt"] == 0 and v0["validation_result"] == "failed"
    assert "label_matched" in v0 and "failed_indicators" in v0
    assert vals[0]["status"] == "failed"


def test_trace_validation_pass_on_good_interpretation():
    good = _good_interp_response(DAILY, WEEKLY, MONTHLY)
    _out, events = _run_trace([NORM_OK, FOCUS_OK, good])
    vals = [e for e in events if e["event_type"] == "validation"]
    assert len(vals) == 1 and vals[0]["status"] == "success"
    assert vals[0]["output_summary"]["validation_result"] == "passed"
    # interpret_report node_end에 최종 source·regen·fallback 요약이 실린다
    end = next(e for e in events if e["node"] == "interpret_report" and e["event_type"] == "node_end")
    s = end["output_summary"]
    assert "interpretation_source" in s and "detail_source_count" in s
    assert s["template_fallback_used"] is False


def test_trace_validation_has_no_raw_llm_response():
    # INTERP_BAD의 raw 응답 문구가 validation/trace 어디에도 남지 않는다
    _out, events = _run_trace([NORM_OK, FOCUS_OK] + [INTERP_BAD] * (REGEN_MAX_COUNT + 1))
    dumped = json.dumps(events, ensure_ascii=False)
    assert "흥미롭습니다" not in dumped                    # raw interpretation_text 미기록


def test_trace_sink_failure_does_not_break_run():
    class BoomSink:
        def emit(self, event):
            raise ConnectionError("sink down")
    out = sup.run(_input(), llm_client=ScriptedLlm([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD]),
                  fetcher=lambda t, *, end_date=None: {"D": DAILY, "W": WEEKLY, "M": MONTHLY},
                  trace_id="t", trace_sink=BoomSink())
    assert out.data_status == DataStatus.NORMAL          # sink 예외에도 정상 완주


# ── ALLOWLIST + DEADLINE (feat/technical-ai-endpoint hardening) ────────────────
import time as _time  # noqa: E402

from src.agents.technical.runtime.deadline import Deadline, DeadlineExceeded  # noqa: E402
def _dwm_fetcher(t, *, end_date=None):
    return {"D": DAILY, "W": WEEKLY, "M": MONTHLY}


def test_expanded_ticker_enters_llm_and_fetcher():
    # 전체 종목 확장: 구 allowlist 밖 ticker(999999)도 정책상 지원 → OpenAI/KIS로 진입해 정상 output.
    llm = ScriptedLlm([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD])
    calls = {"n": 0}

    def fetch(t, *, end_date=None):
        calls["n"] += 1
        return {"D": DAILY, "W": WEEKLY, "M": MONTHLY}
    expanded = TechnicalAgentInput(ticker="999999", query="q", request_id="r", as_of=AS_OF)
    out = sup.run(expanded, llm_client=llm, fetcher=fetch, trace_id="t")
    assert out.ticker == "999999" and calls["n"] > 0      # gate 미차단 → KIS 진입


def test_expired_deadline_raises_before_preprocess():
    llm = ScriptedLlm([])
    expired = Deadline(expires_at=_time.monotonic() - 1)  # 이미 만료
    with pytest.raises(DeadlineExceeded):
        sup.run(_input(), llm_client=llm, fetcher=_dwm_fetcher, deadline=expired, trace_id="t")
    assert llm.prompts == []                              # 예산 초과 → LLM 미호출


def test_deadline_checks_placed_at_stages(monkeypatch):
    # check_deadline이 주요 stage(전처리·데이터·재생성 포함)에 배치돼 있는지 — 호출 stage 기록
    seen: list[str] = []
    monkeypatch.setattr(steps, "check_deadline", lambda dl, stage: seen.append(stage))
    _run([NORM_OK, FOCUS_OK, INTERP_BAD, INTERP_BAD])     # regen 발생
    for stage in ("preprocess", "focus_analysis", "data_collect",
                  "regime_classify", "interpret_report", "interpret_regeneration"):
        assert stage in seen
