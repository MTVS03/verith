"""Technical Supervisor end-to-end 테스트 (test_plan §5.10 SUP-*). fake만 — 실 KIS/LLM 없음."""

from __future__ import annotations

import json
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
    regime = sup._to_regime_result(regime_result)
    signal_summary = sup._to_signal_summary(score, conf)
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


def _minute_fetcher(candles=None, *, previous_close=101.0):
    """테스트용 fake intraday fetcher — IntradayFetchResult를 돌려준다(KIS 없음)."""
    result = IntradayFetchResult(
        candles=list(INTRADAY_CANDLES if candles is None else candles),
        previous_close=previous_close, latest_price=None,
        cumulative_volume=None, cumulative_trading_value=None,
    )
    return lambda ticker, *, as_of=None, **kw: result


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
    regime = sup._to_regime_result(regime_result)
    signal_summary = sup._to_signal_summary(score, conf)
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
    out = sup._to_technical_signals([isr], [detail])
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
    monkeypatch.setattr(sup, "REGEN_MAX_COUNT", 0)
    # 1차 interpret 검증 실패(INTERP_BAD). 응답을 3개만 준다 — regenerate가 호출되면 pop 실패로 드러남.
    client = ScriptedLlm([NORM_OK, FOCUS_OK, INTERP_BAD])
    out = sup.run(_input(), llm_client=client, fetcher=_fetcher, trace_id="t")
    assert len(client.prompts) == 3  # normalize + focus + interpret 1회 (regenerate 없음)
    assert out.interpretation.source == GenerationSource.TEMPLATE_FALLBACK
    assert out.verification.outcome == out.verification.outcome.TEMPLATE_FALLBACK
    assert out.verification.regen_count == 0


def test_regen_max_count_one_regenerates_once(monkeypatch):
    monkeypatch.setattr(sup, "REGEN_MAX_COUNT", 1)
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
    monkeypatch.setattr(sup, "build_intraday_chart_payload", boom)
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
    """sup.fetch_minute_ohlcv 대체용 — 호출 카운트를 기록한다."""
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
    monkeypatch.setattr(sup, "fetch_minute_ohlcv", _default_minute_stub(called))
    out = _run(_INTRA)
    assert called["n"] == 0
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y"}
    assert out.intraday_context is None


def test_flag_on_uses_default_minute_fetcher(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(sup, "INTRADAY_FETCH_ENABLED", True)
    monkeypatch.setattr(sup, "fetch_minute_ohlcv", _default_minute_stub(called))
    out = _run(_INTRA)  # fetcher·candles 미주입
    assert called["n"] == 1  # flag ON → 기본 fetcher 호출
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y", "1d"}
    assert out.intraday_context is not None


def test_flag_on_direct_candles_skip_default_fetcher(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(sup, "INTRADAY_FETCH_ENABLED", True)
    monkeypatch.setattr(sup, "fetch_minute_ohlcv", _default_minute_stub(called))
    out = _run(_INTRA, intraday_candles=INTRADAY_CANDLES)
    assert called["n"] == 0  # 직접 주입 우선 → 기본 fetcher 미호출
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y", "1d"}


def test_flag_on_explicit_fetcher_takes_precedence(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(sup, "INTRADAY_FETCH_ENABLED", True)
    monkeypatch.setattr(sup, "fetch_minute_ohlcv", _default_minute_stub(called))
    out = _run(_INTRA, intraday_fetcher=_minute_fetcher(previous_close=200.0))
    assert called["n"] == 0  # 명시 fetcher 우선 → 기본 미호출
    assert out.intraday_context.previous_close == 200.0


def test_flag_on_default_fetcher_exception_isolated(monkeypatch):
    def boom(ticker, *, as_of=None, **kw):
        raise RuntimeError("kis intraday down")
    monkeypatch.setattr(sup, "INTRADAY_FETCH_ENABLED", True)
    monkeypatch.setattr(sup, "fetch_minute_ohlcv", boom)
    out = _run(_INTRA)
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y"}  # D/W/M 정상
    assert out.intraday_context is None


def test_flag_on_default_empty_candles_dwm_only(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(sup, "INTRADAY_FETCH_ENABLED", True)
    monkeypatch.setattr(sup, "fetch_minute_ohlcv", _default_minute_stub(called, candles=[]))
    out = _run(_INTRA)
    assert called["n"] == 1
    assert {p.period.value for p in out.charts} == {"3m", "1y", "5y"}
    assert out.intraday_context is None


def test_flag_on_final_regime_and_signal_unchanged(monkeypatch):
    without = _run(_INTRA)
    monkeypatch.setattr(sup, "INTRADAY_FETCH_ENABLED", True)
    monkeypatch.setattr(sup, "fetch_minute_ohlcv", _default_minute_stub({"n": 0}))
    with_flag = _run(_INTRA)
    assert with_flag.regime == without.regime      # final_regime 등 불변
    assert with_flag.signal == without.signal       # top-level confidence/signal_score 불변
    assert with_flag.intraday_context.signal_score_adjustment == 0.0
