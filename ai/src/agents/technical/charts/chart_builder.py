"""chart_builder — 프론트 렌더용 chart_data JSON 생성.

정본: `chart_annotation_spec.md`(구조·annotation 규칙), `contracts.md`(charts[].chart_data),
`config.md §10`(차트 상수). LLM·KIS·DB·Redis 미사용. 이미지/HTML/SVG를 만들지 않는다.

경계:
  - 입력은 OHLCV(D/W/M) + config 뿐이다. regime/synthesis/risk 결과는 입력이 아니며
    chart_data에도 넣지 않는다(순수 chart JSON). support_touch·rsi_overbought 등은
    risk를 읽지 않고 OHLCV 기준으로 독립 계산한다.
  - annotation은 전부 코드가 생성한다(source="code"). label은 코드 템플릿(투자 권유 표현 없음).
  - D→W/M 리샘플을 하지 않는다. 5y는 주봉 candle을 그대로 쓴다.

MVP 구현 annotation: golden_cross·dead_cross·volume_spike·support_touch·resistance_touch·
rsi_overbought·rsi_oversold·box_range_candidate. box_breakout·cup_handle은 후속(제외).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from ..config import (
    ANNOTATION_DEDUP_BARS,
    BOX_LOOKBACK_DAYS,
    BOX_MIN_TOUCH_COUNT,
    BOX_RANGE_THRESHOLD_PCT,
    CHART_PERIOD_DAYS,
    KIS_PERIOD_DAILY,
    KIS_PERIOD_WEEKLY,
    MA_WINDOWS,
    NEAR_RESISTANCE_THRESHOLD_PCT,
    NEAR_SUPPORT_THRESHOLD_PCT,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    RSI_PERIOD,
    SUPPORT_LOOKBACK_DAYS,
    TRADING_VALUE_SPIKE_MULTIPLIER,
    VOLUME_AVG_WINDOW,
    VOLUME_SPIKE_MULTIPLIER,
)
from ..indicators.moving_average import calculate_moving_averages
from ..indicators.rsi import calculate_rsi
from ..indicators.volume import calculate_trading_value_average, calculate_volume_average
from ..schemas.contracts import ChartPayload
from ..schemas.enums import ChartPeriod
from ..schemas.ohlcv import OHLCV

# annotation 표시 라벨 (코드 템플릿, chart_annotation_spec §7). 투자 권유 표현 없음.
_LABELS = {
    "golden_cross": "골든크로스",
    "dead_cross": "데드크로스",
    "volume_spike": "거래량 급증",
    "support_touch": "지지선 근접",
    "resistance_touch": "저항선 근접",
    "rsi_overbought": "RSI 과열",
    "rsi_oversold": "RSI 과매도",
    "box_range_candidate": "박스권 후보",
}

# 골든/데드 크로스 판정 MA 조합 (config.md MA_WINDOWS 기반, chart_annotation_spec §8.2).
# 단기/중기 = medium, 중기/장기 = high.
_CROSS_PAIRS = (
    (MA_WINDOWS[0], MA_WINDOWS[1], "medium"),
    (MA_WINDOWS[1], MA_WINDOWS[2], "high"),
)


def build_chart_payloads(
    daily_ohlcv: Sequence[OHLCV],
    weekly_ohlcv: Sequence[OHLCV],
    monthly_ohlcv: Sequence[OHLCV],
) -> list[ChartPayload]:
    """3m/1y/5y ChartPayload를 생성한다.

    3m·1y는 일봉(D), 5y는 주봉(W)을 기본 candle로 쓴다. monthly_ohlcv는 MVP chart_data에
    넣지 않지만(보조 봉 = Future Work) 시그니처에 받아 상위 조율과의 계약을 유지한다.
    """
    _ = monthly_ohlcv  # MVP 미사용 (auxiliary_series = Future Work)
    plan = [
        (ChartPeriod.THREE_MONTHS, KIS_PERIOD_DAILY, daily_ohlcv),
        (ChartPeriod.ONE_YEAR, KIS_PERIOD_DAILY, daily_ohlcv),
        (ChartPeriod.FIVE_YEARS, KIS_PERIOD_WEEKLY, weekly_ohlcv),
    ]
    return [
        ChartPayload(period=period, chart_data=_build_chart_data(period, unit, source))
        for period, unit, source in plan
    ]


# ─────────────────────────────────────────────────────────────────────────────
# slice
# ─────────────────────────────────────────────────────────────────────────────
def _slice_start_index(source: Sequence[OHLCV], days: int) -> int:
    """마지막 candle date 기준 최근 days일 안에 드는 첫 index. 부족하면 확보분만."""
    if not source:
        return 0
    last_date = date.fromisoformat(source[-1].date)
    cutoff = last_date - timedelta(days=days)
    for i, bar in enumerate(source):
        if date.fromisoformat(bar.date) >= cutoff:
            return i
    return len(source)


# ─────────────────────────────────────────────────────────────────────────────
# chart_data 조립
# ─────────────────────────────────────────────────────────────────────────────
def _build_chart_data(period: ChartPeriod, candle_unit: str, source: Sequence[OHLCV]) -> dict:
    start = _slice_start_index(source, CHART_PERIOD_DAYS[period.value])
    visible = list(source[start:])
    candles = [
        {"date": b.date, "open": b.open, "high": b.high, "low": b.low,
         "close": b.close, "volume": b.volume, "trading_value": b.trading_value}
        for b in visible
    ]

    if not source:
        return {"candle_unit": candle_unit, "candles": [],
                "overlays": {"moving_average": [], "support_resistance": []},
                "subcharts": {"rsi": _empty_rsi(), "volume": {"avg_window": VOLUME_AVG_WINDOW, "bars": []}},
                "annotations": []}

    mas = calculate_moving_averages(source)
    rsis = calculate_rsi(source)
    vol_avg = calculate_volume_average(source)
    tv_avg = calculate_trading_value_average(source)

    overlays = {
        "moving_average": _ma_overlays(source, mas, start),
        "support_resistance": _sr_overlays(source),
    }
    subcharts = {
        "rsi": _rsi_subchart(source, rsis, start),
        "volume": _volume_subchart(source, vol_avg, start),
    }

    annotations = (
        _cross_annotations(source, mas, start)
        + _volume_spike_annotations(source, vol_avg, tv_avg, start)
        + _sr_touch_annotations(source)
        + _rsi_annotations(source, rsis, start)
        + _box_range_annotation(source)
    )
    date_to_index = {bar.date: i for i, bar in enumerate(source)}
    annotations = _finalize_annotations(annotations, ANNOTATION_DEDUP_BARS[period.value], date_to_index)

    return {"candle_unit": candle_unit, "candles": candles,
            "overlays": overlays, "subcharts": subcharts, "annotations": annotations}


# ── overlays / subcharts ──────────────────────────────────────────────────────
def _ma_overlays(source: Sequence[OHLCV], mas: dict, start: int) -> list[dict]:
    overlays = []
    for window in MA_WINDOWS:
        points = [
            {"date": source[i].date, "value": mas[window][i]}
            for i in range(start, len(source))
            if mas[window][i] is not None
        ]
        if points:  # 계산 봉 부족으로 값이 없으면 제외(chart_annotation_spec §17)
            overlays.append({"window": window, "points": points})
    return overlays


def _sr_levels(source: Sequence[OHLCV]) -> dict | None:
    """최근 SUPPORT_LOOKBACK_DAYS 창의 지지/저항 레벨과 터치 횟수. overlay·touch annotation 공용."""
    window = list(source[-SUPPORT_LOOKBACK_DAYS:])
    if not window:
        return None
    lows = [float(b.low) for b in window]
    highs = [float(b.high) for b in window]
    support, resistance = min(lows), max(highs)
    return {
        "support": support,
        "resistance": resistance,
        "support_touch": sum(1 for lo in lows if support and abs(lo - support) / support <= NEAR_SUPPORT_THRESHOLD_PCT),
        "resistance_touch": sum(1 for hi in highs if resistance and abs(hi - resistance) / resistance <= NEAR_RESISTANCE_THRESHOLD_PCT),
        "from": window[0].date,
        "to": window[-1].date,
    }


def _sr_overlays(source: Sequence[OHLCV]) -> list[dict]:
    levels = _sr_levels(source)
    if levels is None:
        return []
    return [
        {"type": "support", "price": levels["support"], "from": levels["from"],
         "to": levels["to"], "touch_count": levels["support_touch"]},
        {"type": "resistance", "price": levels["resistance"], "from": levels["from"],
         "to": levels["to"], "touch_count": levels["resistance_touch"]},
    ]


def _empty_rsi() -> dict:
    return {"period": RSI_PERIOD, "overbought": RSI_OVERBOUGHT, "oversold": RSI_OVERSOLD, "points": []}


def _rsi_subchart(source: Sequence[OHLCV], rsis: list, start: int) -> dict:
    points = [
        {"date": source[i].date, "value": rsis[i]}
        for i in range(start, len(source))
        if rsis[i] is not None
    ]
    return {"period": RSI_PERIOD, "overbought": RSI_OVERBOUGHT, "oversold": RSI_OVERSOLD, "points": points}


def _volume_subchart(source: Sequence[OHLCV], vol_avg: list, start: int) -> dict:
    bars = []
    for i in range(start, len(source)):
        avg = vol_avg[i]
        vol = float(source[i].volume)
        bars.append({
            "date": source[i].date, "volume": source[i].volume, "avg_volume": avg,
            "is_spike": bool(avg is not None and avg > 0 and vol >= avg * VOLUME_SPIKE_MULTIPLIER),
        })
    return {"avg_window": VOLUME_AVG_WINDOW, "bars": bars}


# ── annotations ───────────────────────────────────────────────────────────────
def _ann(kind: str, when: str, price: float | None, importance: str, meta: dict | None = None) -> dict:
    return {"kind": kind, "date": when, "price": price, "label": _LABELS[kind],
            "importance": importance, "source": "code", "meta": meta or {}}


def _cross_annotations(source: Sequence[OHLCV], mas: dict, start: int) -> list[dict]:
    anns: list[dict] = []
    for short, long, importance in _CROSS_PAIRS:
        s, ln = mas[short], mas[long]
        for i in range(max(1, start), len(source)):
            if None in (s[i], s[i - 1], ln[i], ln[i - 1]):
                continue
            meta = {"pair": f"{short}/{long}"}
            if s[i - 1] <= ln[i - 1] and s[i] > ln[i]:
                anns.append(_ann("golden_cross", source[i].date, float(source[i].close), importance, meta))
            elif s[i - 1] >= ln[i - 1] and s[i] < ln[i]:
                anns.append(_ann("dead_cross", source[i].date, float(source[i].close), importance, meta))
    return anns


def _volume_spike_annotations(source: Sequence[OHLCV], vol_avg: list, tv_avg: list, start: int) -> list[dict]:
    anns: list[dict] = []
    for i in range(start, len(source)):
        va, ta = vol_avg[i], tv_avg[i]
        vol, tv = float(source[i].volume), float(source[i].trading_value)
        triggered = []
        if va and vol >= va * VOLUME_SPIKE_MULTIPLIER:
            triggered.append("volume")
        if ta and tv >= ta * TRADING_VALUE_SPIKE_MULTIPLIER:
            triggered.append("trading_value")
        if triggered:
            anns.append(_ann("volume_spike", source[i].date, float(source[i].close), "medium", {
                "volume_ratio": round(vol / va, 2) if va else None,
                "trading_value_ratio": round(tv / ta, 2) if ta else None,
                "triggered_by": triggered,
            }))
    return anns


def _sr_touch_annotations(source: Sequence[OHLCV]) -> list[dict]:
    """현재가가 지지/저항 레벨에 근접(±pct) **AND** 그 레벨 터치가 BOX_MIN_TOUCH_COUNT회 이상일 때만
    생성한다(chart_annotation_spec §10.2·§10.3: 유사 가격대 2회 이상)."""
    levels = _sr_levels(source)
    if levels is None:
        return []
    support, resistance = levels["support"], levels["resistance"]
    close = float(source[-1].close)
    last_date = source[-1].date
    anns: list[dict] = []
    if (support and abs(close - support) / support <= NEAR_SUPPORT_THRESHOLD_PCT
            and levels["support_touch"] >= BOX_MIN_TOUCH_COUNT):
        anns.append(_ann("support_touch", last_date, support, "medium",
                         {"touch_count": levels["support_touch"]}))
    if (resistance and abs(close - resistance) / resistance <= NEAR_RESISTANCE_THRESHOLD_PCT
            and levels["resistance_touch"] >= BOX_MIN_TOUCH_COUNT):
        anns.append(_ann("resistance_touch", last_date, resistance, "medium",
                         {"touch_count": levels["resistance_touch"]}))
    return anns


def _rsi_annotations(source: Sequence[OHLCV], rsis: list, start: int) -> list[dict]:
    """RSI가 과열/과매도 구간에 진입하는 봉에만 annotation을 만든다(진입 이벤트)."""
    anns: list[dict] = []
    for i in range(start, len(source)):
        cur = rsis[i]
        if cur is None:
            continue
        prev = rsis[i - 1] if i > 0 else None
        if cur >= RSI_OVERBOUGHT and (prev is None or prev < RSI_OVERBOUGHT):
            anns.append(_ann("rsi_overbought", source[i].date, None, "medium", {"rsi": round(cur, 1)}))
        elif cur <= RSI_OVERSOLD and (prev is None or prev > RSI_OVERSOLD):
            anns.append(_ann("rsi_oversold", source[i].date, None, "medium", {"rsi": round(cur, 1)}))
    return anns


def _box_range_annotation(source: Sequence[OHLCV]) -> list[dict]:
    window = list(source[-BOX_LOOKBACK_DAYS:])
    if len(window) < BOX_LOOKBACK_DAYS:
        return []
    highs = [float(b.high) for b in window]
    lows = [float(b.low) for b in window]
    top, bottom = max(highs), min(lows)
    if bottom <= 0 or (top - bottom) / bottom > BOX_RANGE_THRESHOLD_PCT:
        return []
    top_touch = sum(1 for h in highs if abs(h - top) / top <= NEAR_RESISTANCE_THRESHOLD_PCT)
    bottom_touch = sum(1 for lo in lows if abs(lo - bottom) / bottom <= NEAR_SUPPORT_THRESHOLD_PCT)
    if top_touch < BOX_MIN_TOUCH_COUNT or bottom_touch < BOX_MIN_TOUCH_COUNT:
        return []
    return [_ann("box_range_candidate", window[-1].date, None, "low",
                 {"top": top, "bottom": bottom, "range_pct": round((top - bottom) / bottom, 3)})]


def _finalize_annotations(annotations: list[dict], dedup_bars: int, date_to_index: dict[str, int]) -> list[dict]:
    """동일 kind 근접 중복 제거 → 정렬 → 결정론 id(ann_001..) 부여.

    중복 제거는 달력일이 아니라 **candle(봉) index 거리**로 판정한다(주말·휴장 왜곡 방지,
    chart_annotation_spec §8.4). 같은 kind가 dedup_bars 봉 이내면 앞선 것만 남긴다.
    """
    kept: list[dict] = []
    last_index_by_kind: dict[str, int] = {}
    for ann in sorted(annotations, key=lambda a: (a["kind"], date_to_index.get(a["date"], -1))):
        idx = date_to_index.get(ann["date"], -1)
        prev = last_index_by_kind.get(ann["kind"])
        if prev is not None and idx - prev < dedup_bars:
            continue
        kept.append(ann)
        last_index_by_kind[ann["kind"]] = idx

    ordered = sorted(kept, key=lambda a: (date_to_index.get(a["date"], -1), a["kind"]))
    for i, ann in enumerate(ordered, start=1):
        ann["id"] = f"ann_{i:03d}"
    return ordered
