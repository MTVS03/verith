"""chart_builder — 프론트 렌더용 chart_data JSON 생성.

정본: `chart_annotation_spec.md`(구조·annotation 규칙), `contracts.md`(charts[].chart_data),
`config.md §10`(차트 상수). LLM·KIS·DB·Redis 미사용. 이미지/HTML/SVG를 만들지 않는다.

경계:
  - 입력은 OHLCV(D/W/M) + config 뿐이다. regime/synthesis/risk 결과는 입력이 아니며
    chart_data에도 넣지 않는다(순수 chart JSON). support_touch·rsi_overbought 등은
    risk를 읽지 않고 OHLCV 기준으로 독립 계산한다.
  - annotation은 전부 코드가 생성한다(source="code"). label은 코드 템플릿(투자 권유 표현 없음).
  - D→W/M 리샘플을 하지 않는다. 5y는 주봉 candle을 그대로 쓴다.

구현 annotation(10종): golden_cross·dead_cross·volume_spike·support_touch·resistance_touch·
rsi_overbought·rsi_oversold·box_range_candidate·box_breakout_candidate·cup_handle_candidate.
support/resistance·box_range·box_breakout·cup_handle은 visible range 전체를 rolling으로 판정한다
(look-ahead 없음). cup_handle은 1y(일봉)·5y(주봉)만(3m 제외). 패턴 후보는 annotation-only(signal 미반영).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from ..config import (
    ANNOTATION_DEDUP_BARS,
    BOX_LOOKBACK_DAYS,
    BOX_MIN_ALTERNATIONS,
    BOX_MIN_TOUCH_COUNT,
    BOX_RANGE_THRESHOLD_PCT,
    CHART_PERIOD_DAYS,
    CUP_HANDLE_BOTTOM_TOLERANCE_PCT,
    CUP_HANDLE_DAILY_LOOKBACK_BARS,
    CUP_HANDLE_MAX_DEPTH_PCT,
    CUP_HANDLE_MAX_HANDLE_BARS,
    CUP_HANDLE_MAX_HANDLE_PULLBACK_PCT,
    CUP_HANDLE_MIN_BOTTOM_BARS,
    CUP_HANDLE_MIN_DEPTH_PCT,
    CUP_HANDLE_MIN_HANDLE_BARS,
    CUP_HANDLE_MIN_HANDLE_PULLBACK_PCT,
    CUP_HANDLE_RIM_TOLERANCE_PCT,
    CUP_HANDLE_WEEKLY_LOOKBACK_BARS,
    KIS_PERIOD_DAILY,
    KIS_PERIOD_WEEKLY,
    MA_LONG_WINDOW,
    MA_MID_WINDOW,
    MA_SHORT_WINDOW,
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
    "box_breakout_candidate": "박스권 이탈 관찰",
    "cup_handle_candidate": "컵앤핸들 후보",
}

# 골든/데드 크로스 판정 MA 조합 (config 역할 상수, chart_annotation_spec §8.2).
# short/mid = medium, mid/long = high. overlays는 아래에서 MA_WINDOWS 전체를 순회한다.
_CROSS_PAIRS = (
    (MA_SHORT_WINDOW, MA_MID_WINDOW, "medium"),
    (MA_MID_WINDOW, MA_LONG_WINDOW, "high"),
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

    # 컵앤핸들은 1y(일봉)·5y(주봉)만 — 3m은 창이 너무 짧아 제외(chart_annotation_spec §13).
    cup = (_cup_handle_annotations(source, start, candle_unit=candle_unit, vol_avg=vol_avg)
           if period in (ChartPeriod.ONE_YEAR, ChartPeriod.FIVE_YEARS) else [])
    annotations = (
        _cross_annotations(source, mas, start)
        + _volume_spike_annotations(source, vol_avg, tv_avg, start)
        + _sr_touch_annotations(source, start)
        + _rsi_annotations(source, rsis, start)
        + _box_range_annotations(source, start)
        + _box_breakout_annotations(source, start, vol_avg)
        + cup
    )
    date_to_index = {bar.date: i for i, bar in enumerate(source)}
    annotations = _finalize_annotations(annotations, ANNOTATION_DEDUP_BARS[period.value], date_to_index)
    annotations = _apply_period_importance_policy(annotations, period=period)

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


def _sr_levels_at(source: Sequence[OHLCV], end_i: int) -> dict | None:
    """`source[end_i]` 기준 **직전 SUPPORT_LOOKBACK_DAYS 창**(현재봉 포함, look-ahead 없음)의
    지지/저항 레벨과 터치 횟수. 미래 봉(end_i 이후)은 절대 보지 않는다."""
    lo_i = max(0, end_i - SUPPORT_LOOKBACK_DAYS + 1)
    window = list(source[lo_i:end_i + 1])
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


def _sr_levels(source: Sequence[OHLCV]) -> dict | None:
    """최신 봉 기준 지지/저항 레벨(overlay 공용). `_sr_levels_at(source, len-1)`와 동일."""
    if not source:
        return None
    return _sr_levels_at(source, len(source) - 1)


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


def _sr_touch_annotations(source: Sequence[OHLCV], start: int) -> list[dict]:
    """visible range의 **각 봉을 기준으로 rolling** 지지/저항 근접을 생성한다.

    봉 i에서: 직전 SUPPORT_LOOKBACK_DAYS 창(현재봉 포함, `_sr_levels_at` — look-ahead 없음)의
    지지/저항 레벨을 구하고, close[i]가 그 레벨에 근접(±pct) **AND** 창 내 터치가
    BOX_MIN_TOUCH_COUNT회 이상이면 해당 봉 날짜에 annotation을 만든다
    (chart_annotation_spec §10.2·§10.3: 유사 가격대 2회 이상). 최신 봉 하나만 보던 기존 동작을
    visible 전 구간으로 확장한 것으로, 최신 봉에 대한 판정 결과는 그대로 유지된다.
    창을 채우지 못하는 초기 구간(i < SUPPORT_LOOKBACK_DAYS-1)은 skip한다. 중복은 dedup이 정리한다.
    """
    anns: list[dict] = []
    first = max(start, SUPPORT_LOOKBACK_DAYS - 1)  # 초기 lookback 부족 구간 skip
    for i in range(first, len(source)):
        levels = _sr_levels_at(source, i)
        if levels is None:
            continue
        support, resistance = levels["support"], levels["resistance"]
        close = float(source[i].close)
        bar_date = source[i].date
        if (support and abs(close - support) / support <= NEAR_SUPPORT_THRESHOLD_PCT
                and levels["support_touch"] >= BOX_MIN_TOUCH_COUNT):
            anns.append(_ann("support_touch", bar_date, support, "medium",
                             {"touch_count": levels["support_touch"]}))
        if (resistance and abs(close - resistance) / resistance <= NEAR_RESISTANCE_THRESHOLD_PCT
                and levels["resistance_touch"] >= BOX_MIN_TOUCH_COUNT):
            anns.append(_ann("resistance_touch", bar_date, resistance, "medium",
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


def _box_range_at(source: Sequence[OHLCV], end_i: int) -> dict | None:
    """`source[end_i]`를 끝으로 하는 **직전 BOX_LOOKBACK_DAYS 창**(현재봉 포함, look-ahead 없음)이
    박스권이면 box_range_candidate annotation dict, 아니면 None. 창이 부족한 초기 구간은 None.

    조건(기존 최신-only와 동일): range width ≤ BOX_RANGE_THRESHOLD_PCT AND 상/하단 각각 터치
    BOX_MIN_TOUCH_COUNT회 이상. 미래 봉(end_i 이후)은 절대 보지 않는다.
    meta에 top/bottom/range_pct + top_touch/bottom_touch/window_bars(box_breakout 대비)를 남긴다.
    """
    lo_i = end_i - BOX_LOOKBACK_DAYS + 1
    if lo_i < 0:  # 창(40봉)을 못 채우는 초기 구간 skip
        return None
    window = list(source[lo_i:end_i + 1])
    highs = [float(b.high) for b in window]
    lows = [float(b.low) for b in window]
    top, bottom = max(highs), min(lows)
    if bottom <= 0 or (top - bottom) / bottom > BOX_RANGE_THRESHOLD_PCT:
        return None
    top_touch = sum(1 for h in highs if abs(h - top) / top <= NEAR_RESISTANCE_THRESHOLD_PCT)
    bottom_touch = sum(1 for lo in lows if abs(lo - bottom) / bottom <= NEAR_SUPPORT_THRESHOLD_PCT)
    if top_touch < BOX_MIN_TOUCH_COUNT or bottom_touch < BOX_MIN_TOUCH_COUNT:
        return None
    # 왕복 검사: 각 봉을 상단/하단 zone으로 분류(middle 무시) → 연속 압축 → 전환 수가
    # BOX_MIN_ALTERNATIONS 이상이어야 박스. 단방향 추세(top들 뒤 bottom들)는 전환 1회라 배제된다.
    alternations = _zone_alternations(highs, lows, top, bottom)
    if alternations < BOX_MIN_ALTERNATIONS:
        return None
    return _ann("box_range_candidate", source[end_i].date, None, "low", {
        "top": top, "bottom": bottom, "range_pct": round((top - bottom) / bottom, 3),
        "top_touch": top_touch, "bottom_touch": bottom_touch, "window_bars": len(window),
        "alternations": alternations,
    })


def _zone_alternations(highs: list, lows: list, top: float, bottom: float) -> int:
    """봉들을 상단('T')/하단('B') zone으로 분류(둘 다/middle은 무시)해 연속 중복을 압축한 뒤
    zone 전환 횟수를 센다(top↔bottom 왕복 횟수). 예: T,T,B,B,T → T,B,T → 전환 2."""
    seq: list[str] = []
    for h, lo in zip(highs, lows):
        near_top = top and abs(h - top) / top <= NEAR_RESISTANCE_THRESHOLD_PCT
        near_bottom = bottom and abs(lo - bottom) / bottom <= NEAR_SUPPORT_THRESHOLD_PCT
        if near_top == near_bottom:
            continue  # middle(둘 다 아님) 또는 애매(둘 다) → 왕복 판정에서 제외
        zone = "T" if near_top else "B"
        if not seq or seq[-1] != zone:
            seq.append(zone)
    return max(0, len(seq) - 1)


def _box_range_annotations(source: Sequence[OHLCV], start: int) -> list[dict]:
    """visible range의 각 봉을 창 끝점으로 **rolling** 박스권 후보를 생성한다(look-ahead 없음).

    최신 봉(i=len-1)에 대한 판정은 기존 최신-only `_box_range_at(source, len-1)`와 동일하다.
    창 부족 초기 구간은 skip하며, 연속 박스로 여러 개가 생겨도 dedup이 정리한다.
    """
    anns: list[dict] = []
    first = max(start, BOX_LOOKBACK_DAYS - 1)  # 초기 lookback 부족 구간 skip
    for i in range(first, len(source)):
        ann = _box_range_at(source, i)
        if ann is not None:
            anns.append(ann)
    return anns


def _box_breakout_annotations(source: Sequence[OHLCV], start: int, vol_avg: list) -> list[dict]:
    """박스권 상단/하단을 이탈한 **후보**를 생성한다(chart_annotation_spec §12.2).

    "박스가 먼저 있었고 그다음 봉에서 이탈"한 구조로 판단한다 — 봉 i에서 **현재봉을 제외한**
    직전 박스(`_box_range_at(source, i-1)`, bars ≤ i-1)를 구하고, close[i]가 그 박스 상단 위/하단
    아래로 마감하면 생성한다. 창(bars ≤ i-1) + 판단봉(i)만 쓰므로 **look-ahead 없음**.

    v1은 **가격 이탈만으로** 후보를 만든다(거래량은 gate가 아니라 meta로만 기록 — §12.2). 확정적
    돌파/매수·매도 신호가 아니라 **관찰 후보**이며 label·표현은 중립을 유지한다. importance=medium.
    """
    anns: list[dict] = []
    first = max(start, BOX_LOOKBACK_DAYS)  # 직전 박스(창 40봉) + 현재봉 → i >= BOX_LOOKBACK_DAYS
    for i in range(first, len(source)):
        box = _box_range_at(source, i - 1)  # 현재봉을 제외한 직전 박스
        if box is None:
            continue
        box_top = box["meta"]["top"]
        box_bottom = box["meta"]["bottom"]
        close = float(source[i].close)
        if close > box_top:
            direction, ref = "up", box_top
        elif close < box_bottom:
            direction, ref = "down", box_bottom
        else:
            continue  # 박스 안에 머묾 → 이탈 아님
        vol_ratio = None
        avg = vol_avg[i] if i < len(vol_avg) else None
        if avg:
            vol_ratio = round(float(source[i].volume) / avg, 2)
        anns.append(_ann("box_breakout_candidate", source[i].date, ref, "medium", {
            "direction": direction,
            "box_top": box_top,
            "box_bottom": box_bottom,
            "box_range_pct": box["meta"]["range_pct"],
            "box_window_bars": box["meta"]["window_bars"],
            "breakout_close": close,
            "breakout_pct": round((close - ref) / ref, 4) if ref else None,
            # 거래량은 생성 조건이 아니라 confirmation 정보(§12.2). 기존 VOLUME_SPIKE_MULTIPLIER 재사용.
            "volume_confirmed": bool(vol_ratio is not None and vol_ratio >= VOLUME_SPIKE_MULTIPLIER),
            "volume_ratio": vol_ratio,
        }))
    return anns


def _cup_handle_at(source: Sequence[OHLCV], end_i: int, *, lookback: int, vol_avg: list) -> dict | None:
    """`source[end_i]`를 끝으로 하는 직전 `lookback`봉 창(현재봉 포함, look-ahead 없음)이 컵앤핸들
    **후보** 형태면 annotation dict, 아니면 None(chart_annotation_spec §13). 미래 봉은 보지 않는다.

    보수적 결정론 판정: ① left_rim=앞 30% 최고 high ② bottom=전체 최저 low(중앙부·left_rim 이후,
    **bottom 근처 ≥MIN_BOTTOM_BARS봉** = 단봉 V자 배제) ③ right_rim=bottom 이후 최고 high(핸들 최소
    여지) → rim 차 ≤tol · depth∈[min,max] · handle 길이∈[min,max] · **handle 되돌림∈[MIN,MAX]이고
    handle 저점 < right_rim(실제 조정 존재)** · handle 저점이 컵 깊이 절반 위 · 최신 close가 handle~rim 근처.
    **돌파(neckline breakout)는 요구하지 않는다**(관찰 후보). 완전 곡률 판정은 Phase 2. 거래량은 meta로만.
    """
    lo_i = end_i - lookback + 1
    if lo_i < 0:  # 창(lookback봉)을 못 채우는 초기 구간 skip
        return None
    highs = [float(source[k].high) for k in range(lo_i, end_i + 1)]
    lows = [float(source[k].low) for k in range(lo_i, end_i + 1)]
    last_close = float(source[end_i].close)
    n = len(highs)  # == lookback

    left_end = max(1, n * 3 // 10)
    left_rim_idx = max(range(left_end), key=lambda k: highs[k])
    left_rim = highs[left_rim_idx]
    bottom_idx = min(range(n), key=lambda k: lows[k])
    bottom = lows[bottom_idx]
    if bottom_idx <= left_rim_idx or not (0.3 <= bottom_idx / (n - 1) <= 0.7):
        return None  # 저점이 좌측 rim 이후·중앙부여야 컵 모양
    # 둥근 저점 근사: bottom 근처(±tol)에 최소 봉 수가 있어야 한다(단봉 V자 spike 배제). 완전 곡률은 Phase 2.
    if bottom > 0:
        bottom_zone_bars = sum(1 for lo in lows if lo <= bottom * (1 + CUP_HANDLE_BOTTOM_TOLERANCE_PCT))
        if bottom_zone_bars < CUP_HANDLE_MIN_BOTTOM_BARS:
            return None

    right_end = n - CUP_HANDLE_MIN_HANDLE_BARS  # 우측 rim 뒤 핸들 최소 확보
    if right_end <= bottom_idx + 1:
        return None
    right_rim_idx = max(range(bottom_idx + 1, right_end), key=lambda k: highs[k])
    right_rim = highs[right_rim_idx]
    handle_bars = (n - 1) - right_rim_idx
    if not (CUP_HANDLE_MIN_HANDLE_BARS <= handle_bars <= CUP_HANDLE_MAX_HANDLE_BARS):
        return None
    if left_rim <= 0 or abs(left_rim - right_rim) / left_rim > CUP_HANDLE_RIM_TOLERANCE_PCT:
        return None  # 좌/우 rim 회복(가격 차 tolerance)

    rim = min(left_rim, right_rim)
    if rim <= 0:
        return None
    depth = (rim - bottom) / rim
    if not (CUP_HANDLE_MIN_DEPTH_PCT <= depth <= CUP_HANDLE_MAX_DEPTH_PCT):
        return None

    handle_low = min(lows[right_rim_idx + 1:])
    handle_pullback = (right_rim - handle_low) / right_rim
    # 핸들은 **실제 조정(dip)** 이 있어야 한다: 최소 되돌림 이상·최대 이하, handle 저점 < right_rim.
    # (상한만 있으면 right_rim 이후 계속 상승/무조정도 handle_forming으로 오탐된다.)
    if handle_low >= right_rim or not (
        CUP_HANDLE_MIN_HANDLE_PULLBACK_PCT <= handle_pullback <= CUP_HANDLE_MAX_HANDLE_PULLBACK_PCT
    ):
        return None
    if handle_low <= bottom + (rim - bottom) * 0.5:
        return None  # 핸들 저점이 컵 저점보다 충분히 위(핸들이 컵만큼 깊으면 무효)
    if not (handle_low <= last_close <= right_rim * (1 + CUP_HANDLE_RIM_TOLERANCE_PCT)):
        return None  # 최신 close가 handle 안쪽~rim 근처(돌파 미요구)

    vol_ratio = None
    avg = vol_avg[end_i] if end_i < len(vol_avg) else None
    if avg:
        vol_ratio = round(float(source[end_i].volume) / avg, 2)
    return _ann("cup_handle_candidate", source[end_i].date, right_rim, "medium", {
        "lookback_bars": lookback,
        "left_rim_price": left_rim,
        "right_rim_price": right_rim,
        "bottom_price": bottom,
        "cup_depth_pct": round(depth, 4),
        "rim_tolerance_pct": round(abs(left_rim - right_rim) / left_rim, 4),
        "handle_pullback_pct": round(handle_pullback, 4),
        "handle_bars": handle_bars,
        "candidate_stage": "handle_forming",
        # 거래량은 생성 조건이 아니라 confirmation 정보. 기존 VOLUME_SPIKE_MULTIPLIER 재사용.
        "volume_confirmed": bool(vol_ratio is not None and vol_ratio >= VOLUME_SPIKE_MULTIPLIER),
        "volume_ratio": vol_ratio,
    })


def _cup_handle_annotations(
    source: Sequence[OHLCV], start: int, *, candle_unit: str, vol_avg: list,
) -> list[dict]:
    """visible range의 각 봉을 창 끝점으로 **rolling** 컵앤핸들 후보를 생성한다(look-ahead 없음).

    lookback은 timeframe별 BARS: 일봉=`CUP_HANDLE_DAILY_LOOKBACK_BARS`, 주봉=`..._WEEKLY_...`.
    호출은 1y(일봉)·5y(주봉)에서만 한다(3m 제외 — 창이 너무 짧음). 창 부족 초기 구간은 skip,
    연속 유사 후보는 dedup이 정리한다. annotation-only(signal 미반영).
    """
    lookback = CUP_HANDLE_WEEKLY_LOOKBACK_BARS if candle_unit == "W" else CUP_HANDLE_DAILY_LOOKBACK_BARS
    anns: list[dict] = []
    first = max(start, lookback - 1)  # 초기 lookback 부족 구간 skip
    for i in range(first, len(source)):
        ann = _cup_handle_at(source, i, lookback=lookback, vol_avg=vol_avg)
        if ann is not None:
            anns.append(ann)
    return anns


# 5y period-aware importance 승격 정책 (chart_annotation_spec §4.1·§14).
# 5y는 프론트 기본 표시가 high 중심이라 medium이 대부분이면 대부분 숨겨진다(실측: 5개 종목 공통).
# frontend를 바꾸지 않는 대신 backend에서 **장기·구조적 패턴 후보만** high로 선별 승격한다.
# tactical/보조 이벤트(S/R touch·volume·RSI·cross)는 medium 유지(과밀 방지) — 전체 승격 금지.
_FIVE_YEAR_IMPORTANCE_PROMOTION = {
    "cup_handle_candidate": "high",       # 장기 패턴 후보(사용자 핵심 기대) — annotation-only 유지
    "box_breakout_candidate": "high",     # 박스권 이탈은 장기 차트에서 중요 이벤트(매수/확정 아님)
    "box_range_candidate": "medium",      # setup 성격 — breakout보다 낮게(low→medium)
}


def _apply_period_importance_policy(annotations: list[dict], *, period: ChartPeriod) -> list[dict]:
    """period별 importance 승격. **5y에서만** 장기 패턴 후보를 선별 승격하고 3m/1y는 그대로 둔다.

    dedup 이후 최종 리스트에 적용한다(생성 로직·dedup 무영향, importance는 dedup 기준이 아님).
    annotation kind/label/meta/date/price는 절대 바꾸지 않고 importance만 조정한다. signal_score·
    final_regime·top-level 값과 무관하다(chart annotation 표시 정책 전용).
    """
    if period is not ChartPeriod.FIVE_YEARS:
        return annotations
    for ann in annotations:
        promoted = _FIVE_YEAR_IMPORTANCE_PROMOTION.get(ann["kind"])
        if promoted is not None:
            ann["importance"] = promoted
    return annotations


_IMPORTANCE_RANK = {"low": 1, "medium": 2, "high": 3}


def _finalize_annotations(annotations: list[dict], dedup_bars: int, date_to_index: dict[str, int]) -> list[dict]:
    """동일 kind 근접 중복 제거 → 정렬 → 결정론 id(ann_001..) 부여.

    중복 제거는 달력일이 아니라 **candle(봉) index 거리**로 판정한다(주말·휴장 왜곡 방지,
    chart_annotation_spec §8.4). 같은 kind가 dedup_bars 봉 이내면 **importance가 높은 것, 같으면 더
    최신(index 큰) 것을 남긴다**(§15.1) — rolling detector에서 초기 미성숙 후보가 아니라 완성된
    최신 후보가 표시되도록. 선호도 순으로 greedy 채택하며, 이미 채택된 동일 kind와 dedup_bars 이내면 버린다.
    """
    kept: list[dict] = []
    kept_index_by_kind: dict[str, list[int]] = {}
    # 선호도: importance 높은 것 → 같으면 최신(index 큰) 것 먼저. 결정론(date 안정 정렬).
    ordered_pref = sorted(
        annotations,
        key=lambda a: (_IMPORTANCE_RANK.get(a["importance"], 0), date_to_index.get(a["date"], -1)),
        reverse=True,
    )
    for ann in ordered_pref:
        idx = date_to_index.get(ann["date"], -1)
        near = any(abs(idx - kidx) < dedup_bars for kidx in kept_index_by_kind.get(ann["kind"], ()))
        if near:
            continue
        kept.append(ann)
        kept_index_by_kind.setdefault(ann["kind"], []).append(idx)

    ordered = sorted(kept, key=lambda a: (date_to_index.get(a["date"], -1), a["kind"]))
    for i, ann in enumerate(ordered, start=1):
        ann["id"] = f"ann_{i:03d}"
    return ordered
