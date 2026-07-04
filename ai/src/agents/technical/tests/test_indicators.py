"""indicators 순수 단위테스트 (외부 호출 없음).

검증 ①(계산 정확성)의 지표 계산 축(test_plan.md §3). fixture는 직접 만들고,
KIS/Redis/DB/LLM을 호출하지 않는다. 기대값은 손계산으로 명시한다.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import pytest

from src.agents.technical.config import MA_WINDOWS
from src.agents.technical.indicators.moving_average import (
    calculate_bollinger_bands,
    calculate_moving_averages,
    calculate_sma,
)
from src.agents.technical.indicators.pattern import calculate_candle_features
from src.agents.technical.indicators.rsi import calculate_rsi
from src.agents.technical.indicators.support_resistance import calculate_support_resistance
from src.agents.technical.indicators.volume import (
    calculate_trading_value_average,
    calculate_volume_average,
    calculate_volume_ratio,
)
from src.agents.technical.schemas.ohlcv import OHLCV

INDICATORS_DIR = Path(__file__).resolve().parent.parent / "indicators"


# ── fixture 빌더 ──────────────────────────────────────────────────────────────
def make_bar(
    close: float = 100,
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    volume: int = 1,
    trading_value: int = 1,
    date: str = "2026-01-01",
) -> OHLCV:
    open_ = close if open_ is None else open_
    high = max(open_, close) if high is None else high
    low = min(open_, close) if low is None else low
    return OHLCV(
        date=date, open=open_, high=high, low=low, close=close,
        volume=volume, trading_value=trading_value,
    )


def bars_from_closes(closes: list[float]) -> list[OHLCV]:
    return [make_bar(close=c) for c in closes]


def bars_from_volumes(volumes: list[int]) -> list[OHLCV]:
    return [make_bar(volume=v) for v in volumes]


def bars_from_trading_values(values: list[int]) -> list[OHLCV]:
    return [make_bar(trading_value=v) for v in values]


def bars_from_low_high(lows: list[float], highs: list[float]) -> list[OHLCV]:
    return [make_bar(close=lo, low=lo, high=hi) for lo, hi in zip(lows, highs)]


# ── SMA / 이동평균 ────────────────────────────────────────────────────────────
def test_sma_length_matches_input():
    assert len(calculate_sma([1, 2, 3, 4, 5], 3)) == 5


def test_sma_leading_none_and_values():
    # window=3: 앞 2칸 None, 이후 3봉 평균
    assert calculate_sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_moving_averages_use_ma_windows():
    closes = [1, 2, 3, 4, 5, 6]
    result = calculate_moving_averages(bars_from_closes(closes))
    assert set(result.keys()) == set(MA_WINDOWS)  # 5·20·60
    # window=5 SMA 손계산: index4=(1..5)/5=3, index5=(2..6)/5=4
    assert result[5] == [None, None, None, None, 3.0, 4.0]


def test_bollinger_returns_middle_upper_lower_constant():
    # 상수 종가 20개 → 표준편차 0 → 세 값 모두 동일
    bars = bars_from_closes([100.0] * 20)
    bands = calculate_bollinger_bands(bars)
    assert bands[18] == {"middle": None, "upper": None, "lower": None}
    assert bands[19] == {"middle": 100.0, "upper": 100.0, "lower": 100.0}


def test_bollinger_uses_population_std():
    closes = [float(x) for x in range(1, 21)]  # 1..20, 창=20
    bands = calculate_bollinger_bands(bars_from_closes(closes))
    pop_std = statistics.pstdev(closes)  # ddof=0 (표본표준편차 아님)
    assert bands[19]["middle"] == pytest.approx(statistics.fmean(closes))
    assert bands[19]["upper"] == pytest.approx(statistics.fmean(closes) + 2.0 * pop_std)
    assert bands[19]["lower"] == pytest.approx(statistics.fmean(closes) - 2.0 * pop_std)


# ── RSI ───────────────────────────────────────────────────────────────────────
def test_rsi_length_and_leading_none():
    closes = list(range(1, 21))  # 20개
    rsi = calculate_rsi(bars_from_closes(closes))  # period=14
    assert len(rsi) == 20
    assert rsi[:14] == [None] * 14  # 앞 14칸 None
    assert all(v is not None for v in rsi[14:])


def test_rsi_within_0_100():
    closes = [10, 11, 10, 12, 11, 13, 12, 14, 13, 15, 14, 16, 15, 17, 16, 18]
    rsi = calculate_rsi(bars_from_closes(closes))
    for v in rsi:
        if v is not None:
            assert 0.0 <= v <= 100.0


def test_rsi_flat_prices_is_50():
    rsi = calculate_rsi(bars_from_closes([100.0] * 20))
    assert rsi[-1] == 50.0  # 무변동 → 50 정책


def test_rsi_all_gains_is_100_all_losses_is_0():
    up = calculate_rsi(bars_from_closes(list(range(1, 21))))
    down = calculate_rsi(bars_from_closes(list(range(20, 0, -1))))
    assert up[-1] == 100.0
    assert down[-1] == 0.0


# ── 거래량 / 거래대금 ────────────────────────────────────────────────────────
def test_volume_average_matches():
    bars = bars_from_volumes([10, 20, 30, 40])
    assert calculate_volume_average(bars, window=2) == [None, 15.0, 25.0, 35.0]


def test_trading_value_average_matches():
    bars = bars_from_trading_values([100, 200, 300, 400])
    assert calculate_trading_value_average(bars, window=2) == [None, 150.0, 250.0, 350.0]


def test_volume_ratio_is_current_over_average():
    bars = bars_from_volumes([10, 20, 30, 40])
    ratio = calculate_volume_ratio(bars, window=2)
    assert ratio[0] is None
    assert ratio[1] == pytest.approx(20 / 15)
    assert ratio[2] == pytest.approx(30 / 25)
    assert ratio[3] == pytest.approx(40 / 35)


def test_volume_ratio_none_when_average_zero():
    bars = bars_from_volumes([0, 0, 0])
    assert calculate_volume_ratio(bars, window=2) == [None, None, None]


# ── 지지 / 저항 ───────────────────────────────────────────────────────────────
def test_support_resistance_uses_recent_lookback():
    bars = bars_from_low_high(lows=[5, 3, 4, 2, 6], highs=[10, 12, 9, 15, 11])
    rows = calculate_support_resistance(bars, lookback=3)
    assert rows[0] == {"support": None, "resistance": None}
    assert rows[1] == {"support": None, "resistance": None}
    assert rows[2] == {"support": 3.0, "resistance": 12.0}   # min(5,3,4), max(10,12,9)
    assert rows[3] == {"support": 2.0, "resistance": 15.0}   # min(3,4,2), max(12,9,15)
    assert rows[4] == {"support": 2.0, "resistance": 15.0}   # min(4,2,6), max(9,15,11)


# ── 캔들 특징 ─────────────────────────────────────────────────────────────────
def test_candle_features_bullish():
    row = calculate_candle_features([make_bar(open_=100, close=110, high=115, low=95)])[0]
    assert row == {
        "body": 10.0, "upper_wick": 5.0, "lower_wick": 5.0,
        "is_bullish": True, "is_bearish": False,
    }


def test_candle_features_bearish():
    row = calculate_candle_features([make_bar(open_=110, close=100, high=112, low=98)])[0]
    assert row["body"] == 10.0 and row["upper_wick"] == 2.0 and row["lower_wick"] == 2.0
    assert row["is_bullish"] is False and row["is_bearish"] is True


def test_candle_features_doji():
    row = calculate_candle_features([make_bar(open_=100, close=100, high=105, low=95)])[0]
    assert row["body"] == 0.0
    assert row["is_bullish"] is False and row["is_bearish"] is False


# ── 빈 입력 / 데이터 부족 정책 ────────────────────────────────────────────────
def test_empty_input_policy():
    assert calculate_sma([], 3) == []
    assert calculate_moving_averages([]) == {w: [] for w in MA_WINDOWS}
    assert calculate_bollinger_bands([]) == []
    assert calculate_rsi([]) == []
    assert calculate_volume_average([]) == []
    assert calculate_trading_value_average([]) == []
    assert calculate_volume_ratio([]) == []
    assert calculate_support_resistance([]) == []
    assert calculate_candle_features([]) == []


def test_insufficient_data_returns_none_padded_same_length():
    bars = bars_from_closes([1, 2, 3])  # RSI period 14보다 짧음
    rsi = calculate_rsi(bars)
    assert rsi == [None, None, None]
    bands = calculate_bollinger_bands(bars)
    assert len(bands) == 3 and all(b == {"middle": None, "upper": None, "lower": None} for b in bands)


# ── 경계 규약: 코드에 매수/매도 표현 없음 ────────────────────────────────────
def test_no_buy_sell_expressions_in_source():
    # indicators는 원천 수치만 내고 매수/매도 등 투자 권유 문자열을 코드에 두지 않는다.
    forbidden = ["매수", "매도", "사라", "팔아", "손절", "목표가"]
    for path in INDICATORS_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        hits = [w for w in forbidden if w in text]
        assert not hits, f"{path.name}에 매수/매도 표현: {hits}"


# ── 경계 규약: indicators가 KIS/Redis/DB/LLM을 import(호출)하지 않음 ───────────
def test_no_external_dependency_imports():
    # docstring이 아니라 실제 import 라인만 검사한다(문구 오탐 방지).
    banned = ["httpx", "redis", "requests", "openai", "psycopg", "sqlalchemy", "langchain"]
    for path in INDICATORS_DIR.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert not any(pkg in stripped for pkg in banned), (
                    f"{path.name} import 위반: {stripped}"
                )
