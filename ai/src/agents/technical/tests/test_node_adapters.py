"""노드 어댑터(3~9번) 단위테스트. 외부 호출 없음 — fake fetcher + OHLCV fixture만 사용.

검사 축(요청 §8):
  - 노드 반환이 기존 모듈 직접 호출 결과와 일치(중복 계산·변조 없음).
  - data_collect는 주입 fetcher 결과를 그대로 통과, D/W/M 키 유지.
  - IndicatorBundle이 confidence/risk에 필요한 필드를 가진다.
  - 입력 부족 시 조용한 빈 결과가 아니라 명시적 예외.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import src.agents.technical.charts.chart_builder as cb_mod
import src.agents.technical.indicators.moving_average as ma_mod
import src.agents.technical.nodes.indicator_calculate as ic_mod
import src.agents.technical.regime.rules as rules_mod
import src.agents.technical.synthesis.signal_score as ss_mod
from src.agents.technical.charts.chart_builder import build_chart_payloads
from src.agents.technical.config import MA_LONG_WINDOW, MA_MID_WINDOW, MA_SHORT_WINDOW
from src.agents.technical.nodes.chart_generate import run_chart_generate
from src.agents.technical.nodes.confidence_calculate import run_confidence_calculate
from src.agents.technical.nodes.data_collect import run_data_collect
from src.agents.technical.nodes.indicator_calculate import IndicatorBundle, run_indicator_calculate
from src.agents.technical.nodes.regime_classify import run_regime_classify
from src.agents.technical.nodes.risk_detect import run_risk_detect
from src.agents.technical.nodes.signal_aggregate import run_signal_aggregate
from src.agents.technical.regime.multiframe import analyze_multiframe
from src.agents.technical.regime.rules import classify_daily_regime
from src.agents.technical.schemas.ohlcv import OHLCV
from src.agents.technical.synthesis.confidence import compute_confidence
from src.agents.technical.synthesis.risk import detect_risks
from src.agents.technical.synthesis.signal_score import compute_signal_score


# ── fixture ──────────────────────────────────────────────────────────────────
def _series(n: int, *, start_close: float = 100.0, step: float = 0.5,
            day_stride: int = 1, start: str = "2023-01-02") -> list[OHLCV]:
    """distinct ISO date를 갖는 완만한 우상향 OHLCV n개(과거→최신)."""
    d0 = date.fromisoformat(start)
    bars: list[OHLCV] = []
    for i in range(n):
        close = start_close + step * i
        high = close + 1.0
        low = close - 1.0
        bars.append(OHLCV(
            date=(d0 + timedelta(days=i * day_stride)).isoformat(),
            open=close, high=high, low=low, close=close,
            volume=1000 + i, trading_value=2_000_000_000 + i,
        ))
    return bars


DAILY = _series(120, day_stride=1, start="2023-01-02")
WEEKLY = _series(80, day_stride=7, start="2021-01-04")
MONTHLY = _series(36, day_stride=28, start="2020-01-06")


# ── data_collect (3) ─────────────────────────────────────────────────────────
def test_data_collect_passes_through_fetcher():
    canned = {"D": DAILY, "W": WEEKLY, "M": MONTHLY}
    result = run_data_collect("373220", fetcher=lambda ticker: canned)
    assert result is canned  # 그대로 통과(재가공 없음)


def test_data_collect_has_dwm_keys():
    result = run_data_collect("373220", fetcher=lambda t: {"D": DAILY, "W": WEEKLY, "M": MONTHLY})
    assert set(result) == {"D", "W", "M"}


def test_data_collect_empty_ticker_raises():
    with pytest.raises(ValueError):
        run_data_collect("", fetcher=lambda t: {})


def test_data_collect_propagates_fetcher_error():
    def boom(_ticker):
        raise RuntimeError("KIS down")
    with pytest.raises(RuntimeError):
        run_data_collect("373220", fetcher=boom)


# ── data_collect envelope 검증 (F3) ──────────────────────────────────────────
def test_data_collect_rejects_missing_period():
    # {"D": []} — W/M 누락
    with pytest.raises(ValueError):
        run_data_collect("373220", fetcher=lambda t: {"D": DAILY})


def test_data_collect_rejects_extra_key():
    with pytest.raises(ValueError):
        run_data_collect("373220", fetcher=lambda t: {"D": DAILY, "W": WEEKLY, "M": MONTHLY, "X": []})


def test_data_collect_rejects_string_value():
    with pytest.raises(ValueError):
        run_data_collect("373220", fetcher=lambda t: {"D": "not-bars", "W": WEEKLY, "M": MONTHLY})


def test_data_collect_rejects_wrong_value_type():
    # dict은 Sequence가 아니므로 거부
    with pytest.raises(ValueError):
        run_data_collect("373220", fetcher=lambda t: {"D": {}, "W": WEEKLY, "M": MONTHLY})


def test_data_collect_rejects_non_ohlcv_item():
    with pytest.raises(ValueError):
        run_data_collect("373220", fetcher=lambda t: {"D": [123], "W": WEEKLY, "M": MONTHLY})


def test_data_collect_rejects_non_dict_result():
    with pytest.raises(ValueError):
        run_data_collect("373220", fetcher=lambda t: ["not", "a", "dict"])


def test_data_collect_allows_empty_sequences():
    # 빈 리스트는 구조상 유효(경계 검증은 비어있음을 막지 않음 — 하류 노드가 예외 처리)
    result = run_data_collect("373220", fetcher=lambda t: {"D": [], "W": [], "M": []})
    assert set(result) == {"D", "W", "M"}


# ── indicator_calculate (4) ──────────────────────────────────────────────────
def test_indicator_bundle_type_and_fields():
    bundle = run_indicator_calculate(DAILY)
    assert isinstance(bundle, IndicatorBundle)
    # confidence/risk가 소비하는 최소 필드 존재
    for field in ("close", "prev_close", "ma_short", "ma_mid", "ma_long", "rsi", "volume_ratio",
                  "support", "resistance", "avg_volume", "avg_trading_value", "latest_candle"):
        assert hasattr(bundle, field)


def test_indicator_bundle_matches_direct_module_calls():
    """IndicatorBundle 12개 필드 전부가 indicators/* 모듈 직접 호출 결과와 동일한지 검증(F4)."""
    from src.agents.technical.indicators.moving_average import calculate_moving_averages
    from src.agents.technical.indicators.pattern import calculate_candle_features
    from src.agents.technical.indicators.rsi import calculate_rsi
    from src.agents.technical.indicators.support_resistance import calculate_support_resistance
    from src.agents.technical.indicators.volume import (
        calculate_trading_value_average,
        calculate_volume_average,
        calculate_volume_ratio,
    )
    bundle = run_indicator_calculate(DAILY)
    mas = calculate_moving_averages(DAILY)
    sr = calculate_support_resistance(DAILY)[-1]
    assert bundle.close == float(DAILY[-1].close)
    assert bundle.prev_close == float(DAILY[-2].close)
    assert bundle.ma_short == mas[MA_SHORT_WINDOW][-1]
    assert bundle.ma_mid == mas[MA_MID_WINDOW][-1]
    assert bundle.ma_long == mas[MA_LONG_WINDOW][-1]
    assert bundle.rsi == calculate_rsi(DAILY)[-1]
    assert bundle.volume_ratio == calculate_volume_ratio(DAILY)[-1]
    assert bundle.support == sr["support"]
    assert bundle.resistance == sr["resistance"]
    assert bundle.avg_volume == calculate_volume_average(DAILY)[-1]
    assert bundle.avg_trading_value == calculate_trading_value_average(DAILY)[-1]
    assert bundle.latest_candle == calculate_candle_features(DAILY)[-1]


def test_indicator_calculate_empty_raises():
    with pytest.raises(ValueError):
        run_indicator_calculate([])


# ── regime_classify (5) ──────────────────────────────────────────────────────
def test_regime_classify_matches_direct():
    node_result = run_regime_classify(DAILY, WEEKLY, MONTHLY)
    direct = analyze_multiframe(classify_daily_regime(DAILY), WEEKLY, MONTHLY)
    assert node_result == direct


def test_regime_classify_empty_daily_raises():
    with pytest.raises(ValueError):
        run_regime_classify([], WEEKLY, MONTHLY)


# ── signal_aggregate (6) ─────────────────────────────────────────────────────
def test_signal_aggregate_matches_direct():
    assert run_signal_aggregate(DAILY) == compute_signal_score(DAILY)


def test_signal_aggregate_empty_raises():
    # 모듈은 빈 입력에 (neutral,0.0)을 조용히 내지만, 노드는 명시적 예외로 막는다.
    with pytest.raises(ValueError):
        run_signal_aggregate([])


# ── confidence_calculate (7) ─────────────────────────────────────────────────
def test_confidence_matches_direct():
    signal_result = compute_signal_score(DAILY)
    bundle = run_indicator_calculate(DAILY)
    regime_result = run_regime_classify(DAILY, WEEKLY, MONTHLY)
    node_result = run_confidence_calculate(signal_result, bundle, regime_result)
    direct = compute_confidence(
        signal_result,
        volume_ratio=bundle.volume_ratio,
        final_regime=regime_result.final_regime,
        alignment_flag=regime_result.alignment_flag,
    )
    assert node_result == direct


def test_confidence_missing_input_raises():
    with pytest.raises(ValueError):
        run_confidence_calculate(None, None, None)


# ── risk_detect (8) ──────────────────────────────────────────────────────────
def test_risk_detect_matches_direct():
    signal_result = compute_signal_score(DAILY)
    bundle = run_indicator_calculate(DAILY)
    regime_result = run_regime_classify(DAILY, WEEKLY, MONTHLY)
    node_result = run_risk_detect(signal_result, bundle, regime_result)
    direct = detect_risks(
        signal_result,
        close=bundle.close, support=bundle.support, resistance=bundle.resistance,
        rsi=bundle.rsi, final_regime=regime_result.final_regime,
        alignment_flag=regime_result.alignment_flag, volume_ratio=bundle.volume_ratio,
        avg_volume=bundle.avg_volume, avg_trading_value=bundle.avg_trading_value,
    )
    assert node_result == direct


def test_risk_detect_missing_input_raises():
    with pytest.raises(ValueError):
        run_risk_detect(None, None, None)


# ── chart_generate (9) ───────────────────────────────────────────────────────
def test_chart_generate_matches_direct():
    node_result = run_chart_generate(DAILY, WEEKLY, MONTHLY)
    direct = build_chart_payloads(DAILY, WEEKLY, MONTHLY)
    assert node_result == direct
    assert [p.period.value for p in node_result] == ["3m", "1y", "5y"]


def test_chart_generate_empty_daily_raises():
    with pytest.raises(ValueError):
        run_chart_generate([], WEEKLY, MONTHLY)


# ── MA window 상수화 회귀 가드 (CALC-06, test_plan §3) ────────────────────────
# from-import 구조상 config 단일 patch는 이미 import된 모듈에 전파되지 않으므로,
# 소비 모듈별 window 바인딩을 각각 patch한다(모두 같은 상수원 파생 → 키 일관, KeyError 없음).
def _patch_windows(monkeypatch, short: int, mid: int, long: int) -> None:
    windows = [short, mid, long]
    monkeypatch.setattr(ma_mod, "MA_WINDOWS", windows)
    for mod in (ss_mod, ic_mod):
        monkeypatch.setattr(mod, "MA_SHORT_WINDOW", short)
        monkeypatch.setattr(mod, "MA_MID_WINDOW", mid)
        monkeypatch.setattr(mod, "MA_LONG_WINDOW", long)
    monkeypatch.setattr(rules_mod, "_SHORT_MA", short)
    monkeypatch.setattr(rules_mod, "_MID_MA", mid)
    monkeypatch.setattr(rules_mod, "_LONG_MA", long)
    monkeypatch.setattr(cb_mod, "MA_WINDOWS", windows)
    monkeypatch.setattr(cb_mod, "_CROSS_PAIRS", ((short, mid, "medium"), (mid, long, "high")))


def test_indicator_calculate_custom_windows_no_keyerror(monkeypatch):
    _patch_windows(monkeypatch, 10, 30, 90)
    mas = ma_mod.calculate_moving_averages(DAILY)
    assert set(mas) == {10, 30, 90}  # 생산 키가 새 window를 반영
    bundle = run_indicator_calculate(DAILY)  # mas[5] KeyError 없이 동작
    assert bundle.ma_short == mas[10][-1]
    assert bundle.ma_mid == mas[30][-1]
    assert bundle.ma_long == mas[90][-1]


def test_signal_aggregate_custom_windows_no_keyerror(monkeypatch):
    _patch_windows(monkeypatch, 10, 30, 90)
    result = run_signal_aggregate(DAILY)  # mas[5] KeyError 없이 동작
    assert result.consensus is not None


def test_regime_classify_custom_windows_no_keyerror(monkeypatch):
    _patch_windows(monkeypatch, 10, 30, 90)
    result = run_regime_classify(DAILY, WEEKLY, MONTHLY)  # mas[_SHORT_MA] 새 window로 접근
    assert result.final_regime is not None


def test_chart_generate_custom_windows_no_keyerror(monkeypatch):
    _patch_windows(monkeypatch, 10, 30, 90)
    charts = run_chart_generate(DAILY, WEEKLY, MONTHLY)  # overlay·cross가 새 window로 동작
    assert len(charts) == 3
    windows = {
        ov["window"]
        for p in charts
        for ov in p.chart_data.model_dump(mode="json")["overlays"]["moving_average"]
    }
    assert windows and windows <= {10, 30, 90}  # overlay window가 변경된 MA window를 반영
