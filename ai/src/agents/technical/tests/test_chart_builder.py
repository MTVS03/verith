"""chart_builder 단위테스트 (CHART-*, test_plan.md §6). 외부 호출 없음.

chart_data 구조·source 매핑·slice·annotation 생성을 직접 만든 OHLCV fixture로 검증한다.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from src.agents.technical.charts.chart_builder import build_chart_payloads
from src.agents.technical.schemas.contracts import ChartPayload
from src.agents.technical.schemas.enums import ChartPeriod
from src.agents.technical.schemas.ohlcv import OHLCV

CHARTS_DIR = Path(__file__).resolve().parent.parent / "charts"
CANDLE_FIELDS = {"date", "open", "high", "low", "close", "volume", "trading_value"}
CHART_DATA_KEYS = {"candle_unit", "candles", "overlays", "subcharts", "annotations"}


def series(closes, *, highs=None, lows=None, volumes=None, trading_values=None,
           start=date(2025, 1, 1), step_days=1) -> list[OHLCV]:
    bars = []
    for i, c in enumerate(closes):
        hi = highs[i] if highs else max(c, c)
        lo = lows[i] if lows else min(c, c)
        bars.append(OHLCV(
            date=(start + timedelta(days=step_days * i)).isoformat(),
            open=c, high=max(hi, c), low=min(lo, c), close=c,
            volume=volumes[i] if volumes else 100_000,
            trading_value=trading_values[i] if trading_values else 2_000_000_000,
        ))
    return bars


def payload_of(payloads, period: ChartPeriod) -> ChartPayload:
    return next(p for p in payloads if p.period == period)


def cdata(payload: ChartPayload) -> dict:
    """chart_data(ChartData) → 최종 JSON dict. 테스트는 최종 계약 JSON을 검증한다."""
    return payload.chart_data.model_dump(mode="json", by_alias=True)


def kinds_of(payload: ChartPayload) -> set[str]:
    return {a["kind"] for a in cdata(payload)["annotations"]}


def rich_daily(n=80) -> list[OHLCV]:
    return series([100 + i for i in range(n)])


# ── payload / source / candle_unit ────────────────────────────────────────────
def test_three_payloads_for_each_period():
    payloads = build_chart_payloads(rich_daily(), rich_daily(), rich_daily())
    # D/W/M 3종만 생성(1d 장중 분봉은 별도 경로라 여기서 미생성). ChartPeriod 전량과 같지 않다.
    assert {p.period for p in payloads} == {
        ChartPeriod.THREE_MONTHS, ChartPeriod.ONE_YEAR, ChartPeriod.FIVE_YEARS,
    }


def test_source_and_candle_unit_mapping():
    daily = series([100.0] * 120)
    weekly = series([777.0] * 120, step_days=7, start=date(2020, 1, 1))
    monthly = series([555.0] * 60, step_days=30, start=date(2020, 1, 1))
    payloads = build_chart_payloads(daily, weekly, monthly)

    p3m = payload_of(payloads, ChartPeriod.THREE_MONTHS)
    p1y = payload_of(payloads, ChartPeriod.ONE_YEAR)
    p5y = payload_of(payloads, ChartPeriod.FIVE_YEARS)

    assert cdata(p3m)["candle_unit"] == "D"
    assert cdata(p1y)["candle_unit"] == "D"
    assert cdata(p5y)["candle_unit"] == "W"
    # 3m·1y는 daily(100), 5y는 weekly(777) — monthly(555)는 어디에도 없음
    assert all(c["close"] == 100.0 for c in cdata(p3m)["candles"])
    assert all(c["close"] == 777.0 for c in cdata(p5y)["candles"])
    assert all(c["close"] != 555.0 for c in cdata(p1y)["candles"])
    assert cdata(p5y)["candles"], "5y가 weekly source로 채워져야 함"


def test_no_resample_function():
    for path in CHARTS_DIR.glob("*.py"):
        assert "resample" not in path.read_text(encoding="utf-8").lower()


# ── slice / 데이터 부족 ───────────────────────────────────────────────────────
def test_candles_sliced_by_period_days():
    daily = series([100.0 + i for i in range(200)])  # 200일
    p3m = payload_of(build_chart_payloads(daily, [], []), ChartPeriod.THREE_MONTHS)
    dates = [date.fromisoformat(c["date"]) for c in cdata(p3m)["candles"]]
    assert dates, "candles 존재"
    assert (dates[-1] - dates[0]).days <= 90        # 90일 창
    assert len(dates) < 200                          # 전체보다 적게 slice


def test_insufficient_data_uses_available_no_exception():
    payloads = build_chart_payloads(series([100.0, 101.0, 102.0]), [], [])
    p3m = payload_of(payloads, ChartPeriod.THREE_MONTHS)
    assert len(cdata(p3m)["candles"]) == 3       # 확보분만


def test_empty_source_has_empty_candles():
    p5y = payload_of(build_chart_payloads(rich_daily(), [], []), ChartPeriod.FIVE_YEARS)
    assert cdata(p5y)["candles"] == []


# ── chart_data 구조 ───────────────────────────────────────────────────────────
def test_chart_data_has_required_keys():
    p1y = payload_of(build_chart_payloads(rich_daily(), [], []), ChartPeriod.ONE_YEAR)
    assert set(cdata(p1y).keys()) == CHART_DATA_KEYS


def test_candle_row_fields_match_contract():
    p1y = payload_of(build_chart_payloads(rich_daily(), [], []), ChartPeriod.ONE_YEAR)
    assert set(cdata(p1y)["candles"][0].keys()) == CANDLE_FIELDS


def test_moving_average_overlay_generated():
    overlays = cdata(payload_of(build_chart_payloads(rich_daily(), [], []), ChartPeriod.ONE_YEAR))["overlays"]
    windows = {o["window"] for o in overlays["moving_average"]}
    assert {5, 20, 60} <= windows


def test_rsi_subchart_generated():
    sub = cdata(payload_of(build_chart_payloads(rich_daily(), [], []), ChartPeriod.ONE_YEAR))["subcharts"]
    assert sub["rsi"]["period"] == 14 and sub["rsi"]["points"]


def test_volume_subchart_generated():
    sub = cdata(payload_of(build_chart_payloads(rich_daily(), [], []), ChartPeriod.ONE_YEAR))["subcharts"]
    assert sub["volume"]["avg_window"] == 20 and sub["volume"]["bars"]


def test_support_resistance_overlay_generated():
    overlays = cdata(payload_of(build_chart_payloads(rich_daily(), [], []), ChartPeriod.ONE_YEAR))["overlays"]
    types = {o["type"] for o in overlays["support_resistance"]}
    assert types == {"support", "resistance"}


# ── annotation kind ───────────────────────────────────────────────────────────
def _kinds_from_daily(daily) -> set[str]:
    payloads = build_chart_payloads(daily, [], [])
    return kinds_of(payload_of(payloads, ChartPeriod.ONE_YEAR))


def test_golden_cross_annotation():
    daily = series([100 - i for i in range(20)] + [80 + 3 * i for i in range(20)])
    assert "golden_cross" in _kinds_from_daily(daily)


def test_dead_cross_annotation():
    daily = series([80 + i for i in range(20)] + [98 - 3 * i for i in range(20)])
    assert "dead_cross" in _kinds_from_daily(daily)


def test_volume_spike_annotation():
    vols = [1000] * 24 + [5000]
    daily = series([100.0] * 25, volumes=vols)
    assert "volume_spike" in _kinds_from_daily(daily)


def test_support_touch_annotation():
    closes = [105.0] * 24 + [100.5]
    daily = series(closes, highs=[110.0] * 25, lows=[100.0] * 25)
    assert "support_touch" in _kinds_from_daily(daily)


def test_resistance_touch_annotation():
    closes = [105.0] * 24 + [109.5]
    daily = series(closes, highs=[110.0] * 25, lows=[100.0] * 25)
    assert "resistance_touch" in _kinds_from_daily(daily)


def test_rsi_overbought_annotation():
    daily = series([100 + i for i in range(30)])  # 지속 상승 → RSI 과열 진입
    assert "rsi_overbought" in _kinds_from_daily(daily)


def test_rsi_oversold_annotation():
    daily = series([200 - i for i in range(30)])  # 지속 하락 → RSI 과매도 진입
    assert "rsi_oversold" in _kinds_from_daily(daily)


def test_box_range_candidate_annotation():
    closes, highs, lows = [], [], []
    for i in range(45):
        top = i % 2 == 0
        closes.append(107.0 if top else 101.0)
        highs.append(108.0 if top else 102.0)
        lows.append(106.0 if top else 100.0)
    daily = series(closes, highs=highs, lows=lows)
    assert "box_range_candidate" in _kinds_from_daily(daily)


def test_deferred_kinds_not_generated():
    # 여러 시나리오에서도 후속 kind는 절대 생성되지 않음
    for daily in (rich_daily(), series([100 - i for i in range(20)] + [80 + 3 * i for i in range(20)])):
        assert not ({"box_breakout_candidate", "cup_handle_candidate"} & _kinds_from_daily(daily))


# ── annotation 공통 정책 ──────────────────────────────────────────────────────
def _all_annotations(daily):
    p1y = payload_of(build_chart_payloads(daily, [], []), ChartPeriod.ONE_YEAR)
    return cdata(p1y)["annotations"]


def test_annotation_source_always_code():
    anns = _all_annotations(series([100 + i for i in range(30)]))
    assert anns and all(a["source"] == "code" for a in anns)


def test_annotation_ids_deterministic():
    anns = _all_annotations(series([100 + i for i in range(30)]))
    assert [a["id"] for a in anns] == [f"ann_{i:03d}" for i in range(1, len(anns) + 1)]


def test_annotation_labels_no_buy_sell():
    # 과매수/과매도(oversold/overbought)는 정상 기술 용어이므로 제외하고 검사
    forbidden = ["매수", "매도", "사라", "팔아", "손절", "목표가"]
    daily = series([200 - i for i in range(30)])  # rsi_oversold 등 포함
    for a in _all_annotations(daily):
        cleaned = a["label"].replace("과매수", "").replace("과매도", "")
        assert not [w for w in forbidden if w in cleaned], f"금지 표현: {a['label']}"


def test_chart_data_excludes_regime_synthesis():
    p1y = payload_of(build_chart_payloads(rich_daily(), [], []), ChartPeriod.ONE_YEAR)
    banned = {"regime", "synthesis", "risk", "technical_signals", "confidence",
              "final_regime", "alignment_flag", "consensus", "signal_score"}
    assert not (banned & set(cdata(p1y).keys()))


def test_no_external_dependency_imports():
    banned = ["httpx", "redis", "requests", "openai", "psycopg", "sqlalchemy", "langchain"]
    for path in CHARTS_DIR.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith(("import ", "from ")):
                assert not any(pkg in s for pkg in banned), f"{path.name}: {s}"


# ── Phase A hardening: S/R touch count 게이트 ─────────────────────────────────
def test_support_touch_requires_min_touch_count():
    # 현재가는 지지에 근접하지만 그 저점이 1회뿐 → support_touch 생성 안 함
    single = series([110.0] * 19 + [100.0], highs=[200.0] * 20, lows=[110.0] * 19 + [100.0])
    assert "support_touch" not in _kinds_from_daily(single)
    # 같은 저점이 여러 번(>=2) 터치 → 생성
    multi = series([100.0] * 20, highs=[200.0] * 20, lows=[100.0] * 20)
    assert "support_touch" in _kinds_from_daily(multi)


def test_sr_overlay_kept_even_when_touch_annotation_gated():
    single = series([110.0] * 19 + [100.0], highs=[200.0] * 20, lows=[110.0] * 19 + [100.0])
    p1y = payload_of(build_chart_payloads(single, [], []), ChartPeriod.ONE_YEAR)
    types = {o["type"] for o in cdata(p1y)["overlays"]["support_resistance"]}
    assert types == {"support", "resistance"}  # overlay는 유지


# ── Phase A hardening: dedup은 봉 index 거리 기준 ─────────────────────────────
from src.agents.technical.charts.chart_builder import _finalize_annotations  # noqa: E402


def _mk(kind, when):
    return {"kind": kind, "date": when, "price": None, "label": "x",
            "importance": "low", "source": "code", "meta": {}}


def test_dedup_by_bar_index_not_calendar():
    # 달력상 두 달 떨어졌지만 봉 index로는 3봉 → dedup_bars=5면 중복 제거
    anns = [_mk("volume_spike", "2025-01-02"), _mk("volume_spike", "2025-03-10")]
    date_to_index = {"2025-01-02": 100, "2025-03-10": 103}
    result = _finalize_annotations(anns, 5, date_to_index)
    assert len(result) == 1


def test_dedup_keeps_when_index_gap_large():
    anns = [_mk("volume_spike", "2025-01-02"), _mk("volume_spike", "2025-01-09")]
    date_to_index = {"2025-01-02": 100, "2025-01-09": 106}  # 6봉 간격 >= 5
    assert len(_finalize_annotations(anns, 5, date_to_index)) == 2


def test_dedup_same_date_same_kind_merged():
    anns = [_mk("golden_cross", "2025-01-02"), _mk("golden_cross", "2025-01-02")]
    date_to_index = {"2025-01-02": 100}
    assert len(_finalize_annotations(anns, 5, date_to_index)) == 1


# ── rolling support/resistance (feat/technical-chart-patterns) ──────────────────
def _d(i: int) -> str:
    """series 기본 시작일(2025-01-01, step 1일) 기준 index i의 날짜."""
    return (date(2025, 1, 1) + timedelta(days=i)).isoformat()


def _sr_dates(daily, kind: str) -> list[str]:
    payloads = build_chart_payloads(daily, [], [])
    anns = cdata(payload_of(payloads, ChartPeriod.ONE_YEAR))["annotations"]
    return [a["date"] for a in anns if a["kind"] == kind]


def test_rolling_support_touch_on_past_bar():
    # bar 25에서만 support(100) 근접 close, 이후 봉은 멀어짐 → 최신 봉이 아닌 과거 봉에 생성
    closes = [105.0] * 25 + [100.5] + [105.0] * 20
    daily = series(closes, highs=[110.0] * 46, lows=[100.0] * 46)
    dates = _sr_dates(daily, "support_touch")
    assert _d(25) in dates       # 과거 봉(25)에 support_touch
    assert _d(45) not in dates   # 최신 봉(45)은 touch 아님


def test_rolling_resistance_touch_on_past_bar():
    closes = [105.0] * 25 + [109.5] + [105.0] * 20
    daily = series(closes, highs=[110.0] * 46, lows=[100.0] * 46)
    dates = _sr_dates(daily, "resistance_touch")
    assert _d(25) in dates
    assert _d(45) not in dates


def test_rolling_support_touch_no_lookahead():
    # bar 20 저점(100) 단독 → touch_count 1 < 2 이라 생성 안 됨(미래 반복을 미리 보지 않음).
    # bar 25에서 저점이 반복돼 창 안에 2회가 되면 그때 생성 → annotation은 bar 25에만.
    lows = [105.0] * 46
    closes = [108.0] * 46
    lows[20], closes[20] = 100.0, 100.5   # 1차 저점(단독)
    lows[25], closes[25] = 100.0, 100.5   # 2차 저점(반복)
    dates = _sr_dates(series(closes, highs=[112.0] * 46, lows=lows), "support_touch")
    assert _d(20) not in dates   # 단독 저점 시점엔 생성 안 됨(look-ahead 없음)
    assert _d(25) in dates       # 반복이 창에 들어온 시점에 생성


def test_rolling_support_touch_skips_initial_lookback():
    # 전 봉 flat=support. 창(20봉) 못 채우는 초기 구간(index<19)엔 생성 안 됨.
    daily = series([100.0] * 30, highs=[100.0] * 30, lows=[100.0] * 30)
    dates = _sr_dates(daily, "support_touch")
    assert dates                             # 생성은 됨
    assert all(d >= _d(19) for d in dates)   # 모두 index>=19
    assert _d(0) not in dates and _d(18) not in dates


def test_rolling_latest_bar_touch_preserved():
    # 기존 최신-only 동작 보존: 최신 봉이 support를 touch하면 여전히 생성
    closes = [105.0] * 24 + [100.5]
    daily = series(closes, highs=[110.0] * 25, lows=[100.0] * 25)
    assert _d(24) in _sr_dates(daily, "support_touch")   # 최신 봉(24)


def test_rolling_support_touch_dedup_bounds_count():
    # 60봉 flat=support → 매 봉 touch 후보지만 dedup(1y=10봉)으로 과도하지 않게 정리
    daily = series([100.0] * 60, highs=[100.0] * 60, lows=[100.0] * 60)
    anns = cdata(payload_of(build_chart_payloads(daily, [], []), ChartPeriod.ONE_YEAR))["annotations"]
    sup = [a for a in anns if a["kind"] == "support_touch"]
    assert 1 <= len(sup) <= 8    # 41개 후보(19..59)가 dedup 10봉으로 ~5개 수준


def test_rolling_sr_schema_and_importance_unchanged():
    daily = series([100.0] * 60, highs=[100.0] * 60, lows=[100.0] * 60)
    anns = cdata(payload_of(build_chart_payloads(daily, [], []), ChartPeriod.ONE_YEAR))["annotations"]
    sr = [a for a in anns if a["kind"] in ("support_touch", "resistance_touch")]
    assert sr
    for a in sr:
        assert set(a) >= {"id", "kind", "date", "price", "label", "importance", "source", "meta"}
        assert a["importance"] == "medium"   # importance 미변경(retier는 별도 커밋)
        assert a["source"] == "code"


# ── rolling box_range_candidate (feat/technical-chart-patterns) ─────────────────
from src.agents.technical.charts.chart_builder import _box_range_at  # noqa: E402


def _box_series(n: int) -> list[OHLCV]:
    """n봉 박스권(상단 108 부근 / 하단 100 부근, range 8% ≤ 12%)."""
    closes, highs, lows = [], [], []
    for i in range(n):
        top = i % 2 == 0
        closes.append(107.0 if top else 101.0)
        highs.append(108.0 if top else 102.0)
        lows.append(106.0 if top else 100.0)
    return series(closes, highs=highs, lows=lows)


def _box_dates(daily) -> list[str]:
    anns = cdata(payload_of(build_chart_payloads(daily, [], []), ChartPeriod.ONE_YEAR))["annotations"]
    return [a["date"] for a in anns if a["kind"] == "box_range_candidate"]


def test_rolling_box_on_past_window():
    # 앞 41봉 박스 → 이후 급등(플래토 130)해서 최신 창은 박스 아님 → 과거 봉에 box_range 생성
    box = _box_series(41)
    trend = series([130.0] * 10, highs=[130.0] * 10, lows=[130.0] * 10,
                   start=date(2025, 1, 1) + timedelta(days=41))
    daily = box + trend
    dates = _box_dates(daily)
    assert dates                       # 박스 후보 생성됨
    assert _d(50) not in dates         # 최신 봉(급등 구간)은 박스 아님
    assert all(d <= _d(40) for d in dates)  # 박스 후보는 과거 flat 구간에만


def test_rolling_box_latest_judgment_preserved():
    # i=len-1 판정이 기존 최신-only와 동일: 최신 40봉이 박스면 그 끝봉에서 box 판정
    daily = _box_series(45)
    ann = _box_range_at(daily, len(daily) - 1)
    assert ann is not None
    assert ann["kind"] == "box_range_candidate"
    assert ann["date"] == daily[-1].date


def test_rolling_box_no_lookahead():
    # 박스 구간(bars 20~59) 앞에 강한 상승(bars 0~19) → 창에 상승이 섞인 i에선 박스 아님.
    # 미래(박스 완성)를 미리 보지 않으므로 i=40에선 None, 창이 박스로 가득 찬 i=59에서만 박스.
    rise = series([60.0 + 2.0 * i for i in range(20)],
                  highs=[60.0 + 2.0 * i for i in range(20)],
                  lows=[60.0 + 2.0 * i for i in range(20)])
    box = _box_series(40)
    box = series([float(b.close) for b in box],
                 highs=[float(b.high) for b in box], lows=[float(b.low) for b in box],
                 start=date(2025, 1, 1) + timedelta(days=20))
    daily = rise + box
    assert _box_range_at(daily, 40) is None       # 창에 상승 섞임 → 박스 아님(미래 안 봄)
    assert _box_range_at(daily, 59) is not None    # 창이 박스로 가득 → 박스


def test_rolling_box_skips_initial_window():
    # 창(40봉) 못 채우는 초기 구간(index < 39)엔 생성 안 됨
    daily = _box_series(45)
    assert _box_range_at(daily, 38) is None    # window 부족
    assert _box_range_at(daily, 39) is not None
    dates = _box_dates(daily)
    assert dates and all(d >= _d(39) for d in dates)


def test_rolling_box_dedup_bounds_count():
    # 60봉 박스 → 매 창이 박스 후보지만 dedup(1y=10봉)으로 과도하지 않게 정리
    daily = _box_series(60)
    box = [a for a in cdata(payload_of(build_chart_payloads(daily, [], []),
                                       ChartPeriod.ONE_YEAR))["annotations"]
           if a["kind"] == "box_range_candidate"]
    assert 1 <= len(box) <= 5    # 21개 후보(39..59)가 dedup 10봉으로 ~3개 수준


def test_rolling_box_not_generated_in_trend():
    # 명확한 상승 추세 → 어떤 창도 박스 아님
    daily = series([100.0 + 2.0 * i for i in range(60)])
    assert "box_range_candidate" not in _kinds_from_daily(daily)


def test_rolling_box_schema_and_metadata():
    daily = _box_series(45)
    anns = cdata(payload_of(build_chart_payloads(daily, [], []), ChartPeriod.ONE_YEAR))["annotations"]
    box = [a for a in anns if a["kind"] == "box_range_candidate"]
    assert box
    for a in box:
        assert a["importance"] == "low"   # importance 미변경
        assert a["source"] == "code"
        # 상단/하단 + breakout 대비 metadata(자유 dict, schema 변경 없음)
        assert {"top", "bottom", "range_pct", "top_touch", "bottom_touch", "window_bars"} <= set(a["meta"])
        assert a["meta"]["window_bars"] == 40


# ── box_breakout_candidate (feat/technical-chart-patterns) ──────────────────────
def _breakout_anns(daily) -> list[dict]:
    anns = cdata(payload_of(build_chart_payloads(daily, [], []), ChartPeriod.ONE_YEAR))["annotations"]
    return [a for a in anns if a["kind"] == "box_breakout_candidate"]


def _breakout_dates(daily) -> list[str]:
    return [a["date"] for a in _breakout_anns(daily)]


def test_box_breakout_upside():
    # 41봉 박스(상단 108) + 다음 봉 close 115 → 상방 이탈 후보
    box = _box_series(41)
    up = series([115.0], highs=[116.0], lows=[114.0], start=date(2025, 1, 1) + timedelta(days=41))
    anns = _breakout_anns(box + up)
    assert len(anns) == 1
    assert anns[0]["date"] == _d(41)
    assert anns[0]["meta"]["direction"] == "up"
    assert anns[0]["meta"]["box_top"] == 108.0


def test_box_breakout_downside():
    # 41봉 박스(하단 100) + 다음 봉 close 95 → 하방 이탈 후보
    box = _box_series(41)
    down = series([95.0], highs=[96.0], lows=[94.0], start=date(2025, 1, 1) + timedelta(days=41))
    anns = _breakout_anns(box + down)
    assert len(anns) == 1
    assert anns[0]["date"] == _d(41)
    assert anns[0]["meta"]["direction"] == "down"
    assert anns[0]["meta"]["box_bottom"] == 100.0


def test_box_breakout_none_when_not_box():
    # 추세라 직전 window가 박스가 아니면, close가 높아도 breakout 없음
    daily = series([100.0 + 2.0 * i for i in range(45)])
    assert _breakout_anns(daily) == []


def test_box_breakout_none_when_inside_box():
    # 박스 안에 머물면 breakout 없음(box_range는 있어도 breakout은 없음)
    daily = _box_series(45)
    assert _breakout_anns(daily) == []


def test_box_breakout_no_lookahead_future_independent():
    # bar 41 breakout 판정은 과거 박스만 사용 → 미래 봉을 더 붙여도 그대로 유지
    box = _box_series(41)
    up = series([115.0], highs=[116.0], lows=[114.0], start=date(2025, 1, 1) + timedelta(days=41))
    base = box + up
    extended = base + series([200.0] * 5, highs=[201.0] * 5, lows=[199.0] * 5,
                             start=date(2025, 1, 1) + timedelta(days=42))
    assert _d(41) in _breakout_dates(base)
    assert _d(41) in _breakout_dates(extended)   # 미래 봉 추가와 무관


def test_box_breakout_volume_meta():
    box = _box_series(41)
    # 거래량 급증 동반 이탈 → volume_confirmed true
    up_hi = series([115.0], highs=[116.0], lows=[114.0], volumes=[500_000],
                   start=date(2025, 1, 1) + timedelta(days=41))
    a_hi = _breakout_anns(box + up_hi)[0]
    assert a_hi["meta"]["volume_confirmed"] is True
    assert a_hi["meta"]["volume_ratio"] is not None and a_hi["meta"]["volume_ratio"] >= 2.0
    # 거래량 평범(기본 100k) → volume_confirmed false, 그래도 후보는 생성(가격 이탈만으로)
    up_lo = series([115.0], highs=[116.0], lows=[114.0],
                   start=date(2025, 1, 1) + timedelta(days=41))
    a_lo = _breakout_anns(box + up_lo)[0]
    assert a_lo["meta"]["volume_confirmed"] is False


def test_box_breakout_not_repeated_after_box_gone():
    # 박스 이탈 후 상단 위에서 지속되면, 박스가 사라져 연속 후보가 남발되지 않음
    box = _box_series(41)
    sustained = series([115.0 + i for i in range(6)],
                       highs=[117.0 + i for i in range(6)], lows=[113.0 + i for i in range(6)],
                       start=date(2025, 1, 1) + timedelta(days=41))
    assert len(_breakout_anns(box + sustained)) <= 2   # dedup/구조상 과도하지 않음


def test_box_breakout_schema_and_importance():
    box = _box_series(41)
    up = series([115.0], highs=[116.0], lows=[114.0], start=date(2025, 1, 1) + timedelta(days=41))
    a = _breakout_anns(box + up)[0]
    assert a["kind"] == "box_breakout_candidate"
    assert a["importance"] == "medium"   # box_range(low)보다 행동 이벤트 → medium
    assert a["source"] == "code"
    assert a["label"] == "박스권 이탈 관찰"
    assert {"direction", "box_top", "box_bottom", "box_range_pct", "box_window_bars",
            "breakout_close", "breakout_pct", "volume_confirmed", "volume_ratio"} <= set(a["meta"])
