"""daily regime 규칙 단위테스트 (검증 ②, test_plan.md §4.1).

regime 규칙 자체를 검증하기 위해 indicators를 monkeypatch해 최신 봉의 지표 조건을 직접 통제한다.
KIS/Redis/DB/LLM을 호출하지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from src.agents.technical.config import MIN_DAILY_BARS
from src.agents.technical.regime import rules
from src.agents.technical.schemas.enums import Regime
from src.agents.technical.schemas.ohlcv import OHLCV

REGIME_DIR = Path(__file__).resolve().parent.parent / "regime"


def daily_bars(n: int = 60, last_close: float = 100.0) -> list[OHLCV]:
    """indicators를 patch하므로 내용은 무의미하지만, 길이와 최신 종가만 의미가 있다."""
    bars = [OHLCV(date="2026-01-01", open=100, high=100, low=100, close=100,
                  volume=1, trading_value=1) for _ in range(n - 1)]
    bars.append(OHLCV(date="2026-01-02", open=last_close, high=last_close,
                      low=last_close, close=last_close, volume=1, trading_value=1))
    return bars


def candle(is_bullish=True, body=1.0, lower_wick=0.0, upper_wick=0.0):
    return {"body": body, "upper_wick": upper_wick, "lower_wick": lower_wick,
            "is_bullish": is_bullish, "is_bearish": not is_bullish and body > 0}


def patch_indicators(monkeypatch, *, ma5, ma20, ma60, upper, rsi, support, cndl):
    monkeypatch.setattr(rules, "calculate_moving_averages",
                        lambda o: {5: [ma5], 20: list(ma20), 60: list(ma60)})
    monkeypatch.setattr(rules, "calculate_bollinger_bands",
                        lambda o: [{"middle": None, "upper": upper, "lower": None}])
    monkeypatch.setattr(rules, "calculate_rsi", lambda o: [rsi])
    monkeypatch.setattr(rules, "calculate_support_resistance",
                        lambda o: [{"support": support, "resistance": None}])
    monkeypatch.setattr(rules, "calculate_candle_features", lambda o: [cndl])


# 1. 데이터 부족 → UNAVAILABLE
def test_insufficient_bars_unavailable():
    assert rules.classify_daily_regime(daily_bars(MIN_DAILY_BARS - 1)) == Regime.UNAVAILABLE


# 2. 과매도 반등 관찰
def test_oversold_rebound_watch(monkeypatch):
    patch_indicators(monkeypatch, ma5=10, ma20=[10] * 8, ma60=[10] * 8, upper=200,
                     rsi=30, support=100, cndl=candle(is_bullish=True))
    assert rules.classify_daily_regime(daily_bars(last_close=100)) == Regime.OVERSOLD_REBOUND_WATCH


# 3. 과열
def test_overheated(monkeypatch):
    patch_indicators(monkeypatch, ma5=10, ma20=[10] * 8, ma60=[10] * 8, upper=100,
                     rsi=75, support=None, cndl=candle())
    assert rules.classify_daily_regime(daily_bars(last_close=100)) == Regime.OVERHEATED


# 4. 극단 우선: 정배열 + RSI 72 → OVERHEATED (uptrend 아님)
def test_overheated_priority_over_uptrend(monkeypatch):
    patch_indicators(monkeypatch, ma5=13, ma20=[1, 2, 3, 4, 5, 6, 7, 8], ma60=[0, 1, 2, 3, 4, 5, 6, 7],
                     upper=100, rsi=72, support=None, cndl=candle())
    assert rules.classify_daily_regime(daily_bars(last_close=100)) == Regime.OVERHEATED


# 5. 상승 전환 관찰 (20MA 기울기 음→양 전환)
def test_bullish_reversal_watch(monkeypatch):
    # ma20: 현재 slope(8-3=... ) 양, 직전 slope 0 이하 → 전환
    patch_indicators(monkeypatch, ma5=13, ma20=[10, 10, 10, 10, 10, 10, 10, 12],
                     ma60=[11] * 8, upper=200, rsi=50, support=None, cndl=candle())
    assert rules.classify_daily_regime(daily_bars(last_close=13)) == Regime.BULLISH_REVERSAL_WATCH


# 6. 상승 추세 유지 (정배열 완성 + 20·60MA 우상향, 전환 아님)
def test_uptrend_intact(monkeypatch):
    patch_indicators(monkeypatch, ma5=9, ma20=[1, 2, 3, 4, 5, 6, 7, 8], ma60=[0, 1, 2, 3, 4, 5, 6, 7],
                     upper=200, rsi=50, support=None, cndl=candle())
    assert rules.classify_daily_regime(daily_bars(last_close=9)) == Regime.UPTREND_INTACT


# 7. 하락 추세
def test_downtrend(monkeypatch):
    patch_indicators(monkeypatch, ma5=0, ma20=[8, 7, 6, 5, 4, 3, 2, 1], ma60=[9, 8, 7, 6, 5, 4, 3, 2],
                     upper=200, rsi=50, support=None, cndl=candle())
    assert rules.classify_daily_regime(daily_bars(last_close=0.5)) == Regime.DOWNTREND


# 8. 기본값 SIDEWAYS
def test_sideways_default(monkeypatch):
    patch_indicators(monkeypatch, ma5=10, ma20=[10] * 8, ma60=[10] * 8,
                     upper=200, rsi=50, support=None, cndl=candle())
    assert rules.classify_daily_regime(daily_bars(last_close=10)) == Regime.SIDEWAYS


# 9. slope 계산 불가(60MA 5일 기울기 None) → 전체 unavailable 아님, fallback
def test_partial_slope_none_falls_back_not_unavailable(monkeypatch):
    patch_indicators(monkeypatch, ma5=9, ma20=[1, 2, 3, 4, 5, 6, 7, 8],
                     ma60=[1, 1, None, 4, 5, 6, 7, 8], upper=200, rsi=50, support=None, cndl=candle())
    result = rules.classify_daily_regime(daily_bars(last_close=9))
    assert result != Regime.UNAVAILABLE
    assert result == Regime.SIDEWAYS  # 60MA slope None → uptrend 조건 False → 착지


# 10. support None/0 → 지지 근처 False
def test_near_support_false_when_support_none_or_zero():
    assert rules._is_near_support(100.0, None) is False
    assert rules._is_near_support(100.0, 0) is False
    assert rules._is_near_support(100.0, 100.0) is True


def test_oversold_blocked_when_support_none(monkeypatch):
    patch_indicators(monkeypatch, ma5=10, ma20=[10] * 8, ma60=[10] * 8, upper=200,
                     rsi=30, support=None, cndl=candle(is_bullish=True))
    assert rules.classify_daily_regime(daily_bars(last_close=100)) != Regime.OVERSOLD_REBOUND_WATCH


# 11. upper None → 볼밴 상단 근처 False
def test_near_upper_band_false_when_upper_none():
    assert rules._is_near_upper_band(100.0, None) is False
    assert rules._is_near_upper_band(100.0, 100.0) is True


def test_overheated_blocked_when_upper_none(monkeypatch):
    patch_indicators(monkeypatch, ma5=10, ma20=[10] * 8, ma60=[10] * 8, upper=None,
                     rsi=75, support=None, cndl=candle())
    assert rules.classify_daily_regime(daily_bars(last_close=100)) != Regime.OVERHEATED


# 12. 경계값 포함 규칙
def test_boundary_rsi_oversold_inclusive(monkeypatch):
    patch_indicators(monkeypatch, ma5=10, ma20=[10] * 8, ma60=[10] * 8, upper=200,
                     rsi=35, support=100, cndl=candle(is_bullish=True))  # RSI == 35 포함
    assert rules.classify_daily_regime(daily_bars(last_close=100)) == Regime.OVERSOLD_REBOUND_WATCH


def test_boundary_rsi_overbought_inclusive(monkeypatch):
    patch_indicators(monkeypatch, ma5=10, ma20=[10] * 8, ma60=[10] * 8, upper=100,
                     rsi=70, support=None, cndl=candle())  # RSI == 70 포함
    assert rules.classify_daily_regime(daily_bars(last_close=100)) == Regime.OVERHEATED


def test_boundary_near_band_inclusive(monkeypatch):
    # close == upper * 0.98 정확히 → 포함
    patch_indicators(monkeypatch, ma5=10, ma20=[10] * 8, ma60=[10] * 8, upper=100,
                     rsi=70, support=None, cndl=candle())
    assert rules._is_near_upper_band(98.0, 100.0) is True
    assert rules.classify_daily_regime(daily_bars(last_close=98)) == Regime.OVERHEATED


# 13. 매수/매도 표현 없음
def test_no_buy_sell_expressions_in_source():
    forbidden = ["매수", "매도", "사라", "팔아", "손절", "목표가"]
    for path in REGIME_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not [w for w in forbidden if w in text], f"{path.name} 매수/매도 표현"


# 14. 외부 의존 import 없음
def test_no_external_dependency_imports():
    banned = ["httpx", "redis", "requests", "openai", "psycopg", "sqlalchemy", "langchain"]
    for path in REGIME_DIR.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith(("import ", "from ")):
                assert not any(pkg in s for pkg in banned), f"{path.name}: {s}"
