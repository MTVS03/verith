"""chart annotation 진단 — read-only 계측 도구 (기능 구현 아님).

목적: "전략(annotation)이 잘 안 보인다"의 원인을 숫자로 가른다.
  - 생성 자체가 안 됨(조건 불충족) vs
  - 생성되지만 dedup에서 줄어듦 vs
  - 생성되지만 importance가 낮아 프론트 필터에 걸림(특히 5y) vs
  - 봉 수 부족으로 계산 불가 vs
  - 생성기 미구현(현재 전 10종 구현 완료 — 미구현 목록은 비어 있다)

방식(프로덕션 무변경): `charts/chart_builder.py`의 public `build_chart_payloads`(post-dedup 정본)와
내부 annotation 생성기(`_cross_annotations` 등)를 **읽기 전용**으로 호출해 pre/post-dedup을 비교한다.
chart_builder·indicators·config·schemas의 로직/계약은 전혀 바꾸지 않는다.

실행:
  cd ai
  uv run python src/agents/technical/scripts/diagnose_chart_annotations.py --fixture
  uv run python src/agents/technical/scripts/diagnose_chart_annotations.py --ticker 373220 --as-of 2026-07-06

기본은 fixture mode(KIS 호출 없음). real KIS mode는 --ticker로만 켜지며 env 없으면 graceful skip한다.
pytest/CI에는 fixture mode만 안전하게 포함한다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import get_args

# 스탠드얼론 스크립트라 ai/ 를 sys.path에 올려 `src...` import가 되게 한다.
# 이 파일 위치: ai/src/agents/technical/scripts/ → parents[4] = ai/
_AI_ROOT = Path(__file__).resolve().parents[4]
if str(_AI_ROOT) not in sys.path:
    sys.path.insert(0, str(_AI_ROOT))

from src.agents.technical.charts import chart_builder as cb  # noqa: E402
from src.agents.technical.config import (  # noqa: E402
    BOX_LOOKBACK_DAYS,
    CHART_PERIOD_DAYS,
    CUP_HANDLE_DAILY_LOOKBACK_BARS,
    CUP_HANDLE_WEEKLY_LOOKBACK_BARS,
    MA_LONG_WINDOW,
    RSI_PERIOD,
    SUPPORT_LOOKBACK_DAYS,
    VOLUME_AVG_WINDOW,
)
from src.agents.technical.indicators.moving_average import calculate_moving_averages  # noqa: E402
from src.agents.technical.indicators.rsi import calculate_rsi  # noqa: E402
from src.agents.technical.indicators.volume import (  # noqa: E402
    calculate_trading_value_average,
    calculate_volume_average,
)
from src.agents.technical.schemas.chart import AnnotationKind  # noqa: E402
from src.agents.technical.schemas.enums import ChartPeriod  # noqa: E402
from src.agents.technical.schemas.ohlcv import OHLCV  # noqa: E402

_DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "chart_annotation_diagnostics_output"

# annotation kind 정본을 스키마에서 **자동 유도**(schemas/chart.py AnnotationKind = chart_annotation_spec §7).
# 수동 목록 복제 대신 계약을 단일 소스로 삼는다 — kind가 추가/제거되면 진단기가 자동 반영한다.
ALL_KINDS = list(get_args(AnnotationKind))
# 계약엔 있지만 chart_builder 생성기가 없는 kind. 전 kind 구현 완료 → 비어 있음
# (남으면 "contract exists but generator missing"으로 표시).
UNIMPLEMENTED_KINDS: list[str] = []
_IMPORTANCE_LEVELS = ["high", "medium", "low"]

# period → 기본 candle_unit (build_chart_payloads 매핑과 동일: 3m·1y=D, 5y=W)
_PERIOD_UNIT = {
    ChartPeriod.THREE_MONTHS: "D",
    ChartPeriod.ONE_YEAR: "D",
    ChartPeriod.FIVE_YEARS: "W",
}

# capacity 기준(봉 수). 각 detector가 "최신 시점에서 계산 가능"하려면 source에 필요한 최소 봉 수.
_REQUIRED_BARS = {
    "ma_cross_required_bars": MA_LONG_WINDOW + 1,          # 두 MA + 직전봉 비교
    "rsi_required_bars": RSI_PERIOD + 1,                   # 와일더: period+1
    "volume_required_bars": VOLUME_AVG_WINDOW,
    "support_resistance_required_bars": SUPPORT_LOOKBACK_DAYS,
    "box_required_bars": BOX_LOOKBACK_DAYS,
    "cup_handle_daily_required_bars": CUP_HANDLE_DAILY_LOOKBACK_BARS,
    "cup_handle_weekly_required_bars": CUP_HANDLE_WEEKLY_LOOKBACK_BARS,
}


# ─────────────────────────────────────────────────────────────────────────────
# pre-dedup annotation 재현 (chart_builder._build_chart_data와 동일 입력 — read-only)
# ─────────────────────────────────────────────────────────────────────────────
def _pre_dedup_annotations(period: ChartPeriod, source: list[OHLCV]) -> list[dict]:
    """dedup 전 raw annotation. chart_builder 내부 생성기를 그대로 호출한다(로직 변경 없음)."""
    if not source:
        return []
    start = cb._slice_start_index(source, CHART_PERIOD_DAYS[period.value])
    mas = calculate_moving_averages(source)
    rsis = calculate_rsi(source)
    vol_avg = calculate_volume_average(source)
    tv_avg = calculate_trading_value_average(source)
    unit = _PERIOD_UNIT[period]
    cup = (cb._cup_handle_annotations(source, start, candle_unit=unit, vol_avg=vol_avg)
           if period in (ChartPeriod.ONE_YEAR, ChartPeriod.FIVE_YEARS) else [])
    return (
        cb._cross_annotations(source, mas, start)
        + cb._volume_spike_annotations(source, vol_avg, tv_avg, start)
        + cb._sr_touch_annotations(source, start)
        + cb._rsi_annotations(source, rsis, start)
        + cb._box_range_annotations(source, start)
        + cb._box_breakout_annotations(source, start, vol_avg)
        + cup
    )


def _count_by(items: list, key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        k = it[key] if isinstance(it, dict) else getattr(it, key)
        out[k] = out.get(k, 0) + 1
    return out


def _zero_filled(counts: dict[str, int], keys: list[str]) -> dict[str, int]:
    """모든 후보 key를 0으로 채운 뒤 counts를 덮어써 항상 같은 shape을 유지한다."""
    base = {k: 0 for k in keys}
    for k, v in counts.items():
        base[k] = v
    return base


def _capacity_check(source_count: int, period: ChartPeriod) -> dict:
    unit = _PERIOD_UNIT[period]
    cup_required = (_REQUIRED_BARS["cup_handle_daily_required_bars"] if unit == "D"
                    else _REQUIRED_BARS["cup_handle_weekly_required_bars"])
    # cup_handle은 구현 완료. capacity_check는 "봉 수가 충분한지"만 말한다(생성 여부 아님).
    # 3m은 period 정책상 제외라 enough=true여도 생성하지 않는다.
    if period is ChartPeriod.THREE_MONTHS:
        cup_note = ("cup_handle_candidate는 period 정책상 3m에서 제외된다 — "
                    "enough_for_cup_handle은 봉 수 충분 여부만 의미(생성하지 않음).")
    else:
        tf = "1y(D) 일봉" if unit == "D" else "5y(W) 주봉"
        cup_note = (f"capacity only — {tf} cup_handle은 {cup_required}봉 필요. "
                    "annotation-only로 탐지된다(enough은 봉 수 충분 여부만).")
    return {
        **_REQUIRED_BARS,
        "enough_for_ma_cross": source_count >= _REQUIRED_BARS["ma_cross_required_bars"],
        "enough_for_rsi": source_count >= _REQUIRED_BARS["rsi_required_bars"],
        "enough_for_volume": source_count >= _REQUIRED_BARS["volume_required_bars"],
        "enough_for_support_resistance": source_count >= _REQUIRED_BARS["support_resistance_required_bars"],
        "enough_for_box": source_count >= _REQUIRED_BARS["box_required_bars"],
        "enough_for_cup_handle": source_count >= cup_required,
        "cup_handle_note": cup_note,
    }


def _diagnose_period(period: ChartPeriod, source: list[OHLCV], post_annotations: list) -> dict:
    unit = _PERIOD_UNIT[period]
    source_count = len(source)
    start = cb._slice_start_index(source, CHART_PERIOD_DAYS[period.value]) if source else 0
    visible_count = source_count - start

    pre = _pre_dedup_annotations(period, source)
    pre_by_kind = _zero_filled(_count_by(pre, "kind"), ALL_KINDS)
    post_by_kind = _zero_filled(_count_by(post_annotations, "kind"), ALL_KINDS)
    post_by_importance = _zero_filled(_count_by(post_annotations, "importance"), _IMPORTANCE_LEVELS)

    dedup_before = len(pre)
    dedup_after = len(post_annotations)
    return {
        "period": period.value,
        "candle_unit": unit,
        "source_candle_count": source_count,
        "visible_candle_count": visible_count,
        "lookback_buffer_count": start,  # visible 앞쪽 buffer 봉 수(지표 계산용)
        "annotation_total_count": dedup_after,
        "annotation_count_by_kind": post_by_kind,
        "annotation_count_by_importance": post_by_importance,
        "dedup_before_count": dedup_before,
        "dedup_after_count": dedup_after,
        "dedup_removed_count": dedup_before - dedup_after,
        "dedup_removed_by_kind": {
            k: pre_by_kind[k] - post_by_kind[k] for k in ALL_KINDS if pre_by_kind[k] != post_by_kind[k]
        },
        # 생성기가 visible 구간에서만 annotation을 만들므로 최종 개수는 전부 visible 안에 있다.
        "visible_annotation_count": dedup_after,
        "missing_or_unimplemented_kinds": [
            {"kind": k, "reason": "contract exists but generator missing"} for k in UNIMPLEMENTED_KINDS
        ],
        "capacity_check": _capacity_check(source_count, period),
        "notes": (
            "annotation은 visible 구간 기준으로 생성됨(=visible_annotation_count=total). "
            "support/resistance·box_range·box_breakout·cup_handle은 rolling 또는 historical 후보로 생성될 수 있음. "
            "box/cup이 0이면 우선 조건 불충족 여부를 확인하고, 5y에서는 importance/display 정책(chart_annotation_spec §4.2)도 함께 확인한다."
        ),
    }


def diagnose(daily: list[OHLCV], weekly: list[OHLCV], monthly: list[OHLCV], *, mode: str) -> dict:
    """3m/1y/5y 진단 결과 dict. build_chart_payloads(post-dedup 정본)를 그대로 읽는다."""
    payloads = cb.build_chart_payloads(daily, weekly, monthly)
    post_by_period = {p.period.value: list(p.chart_data.annotations) for p in payloads}
    source_by_period = {
        ChartPeriod.THREE_MONTHS: list(daily),
        ChartPeriod.ONE_YEAR: list(daily),
        ChartPeriod.FIVE_YEARS: list(weekly),
    }
    periods = [
        _diagnose_period(period, source_by_period[period], post_by_period.get(period.value, []))
        for period in (ChartPeriod.THREE_MONTHS, ChartPeriod.ONE_YEAR, ChartPeriod.FIVE_YEARS)
    ]
    return {
        "mode": mode,
        "daily_source_count": len(daily),
        "weekly_source_count": len(weekly),
        "monthly_source_count": len(monthly),
        "unimplemented_kinds": UNIMPLEMENTED_KINDS,
        "periods": periods,
    }


# ─────────────────────────────────────────────────────────────────────────────
# fixture (결정론 합성 OHLCV — KIS 호출 없음)
# ─────────────────────────────────────────────────────────────────────────────
def _bar(d: str, close: float, volume: int) -> OHLCV:
    open_ = close * 0.995
    high = max(open_, close) * 1.01
    low = min(open_, close) * 0.99
    return OHLCV(
        date=d, open=round(open_, 1), high=round(high, 1), low=round(low, 1),
        close=round(close, 1), volume=volume, trading_value=int(close * volume),
    )


def _dates(n: int, *, start: date, step_days: int, weekdays_only: bool) -> list[str]:
    out: list[str] = []
    d = start
    while len(out) < n:
        if not weekdays_only or d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=step_days)
    return out


def _synthetic_series(n: int, *, start: date, step_days: int, weekdays_only: bool) -> list[OHLCV]:
    """추세+진동으로 MA 크로스·RSI 스윙·주기적 거래량 급증이 나오는 결정론 시계열."""
    dates = _dates(n, start=start, step_days=step_days, weekdays_only=weekdays_only)
    bars: list[OHLCV] = []
    for i, d in enumerate(dates):
        close = 80000 + 40 * i + 8000 * math.sin(i / 9.0)  # 크로스 유발 진동
        volume = 200_000 + (500_000 if i % 30 == 0 else int(60_000 * abs(math.sin(i / 5.0))))
        bars.append(_bar(d, close, volume))
    return bars


def build_fixture() -> tuple[list[OHLCV], list[OHLCV], list[OHLCV]]:
    """(daily, weekly, monthly). monthly는 chart_builder 미사용이라 빈 리스트."""
    # Date.now() 없이 고정 기준일(결정론). 실제 값이 아니라 진단 shape 검증용.
    daily = _synthetic_series(330, start=date(2025, 1, 1), step_days=1, weekdays_only=True)
    weekly = _synthetic_series(330, start=date(2020, 1, 6), step_days=7, weekdays_only=False)
    return daily, weekly, []


# ─────────────────────────────────────────────────────────────────────────────
# real KIS mode (옵션 — 기본 아님, env 없으면 graceful skip)
# ─────────────────────────────────────────────────────────────────────────────
def _load_real(ticker: str, as_of: str | None) -> tuple[list[OHLCV], list[OHLCV], list[OHLCV]] | None:
    from src.agents.technical.services import kis_client as kc
    try:
        kc.load_kis_settings()  # env 검증(.env 로드). 없으면 RuntimeError.
    except RuntimeError as exc:
        print(f"[diagnose] real KIS env 없음 → skip: {exc}", file=sys.stderr)
        return None
    end = datetime.fromisoformat(as_of) if as_of else None
    try:
        by_period = kc.fetch_multi_timeframe_ohlcv(ticker, end_date=end)
    except kc.OutOfScopeTickerError as exc:
        print(f"[diagnose] 지원 정책 밖(형식 오류) 종목 → skip: {exc}", file=sys.stderr)
        return None
    return list(by_period["D"]), list(by_period["W"]), list(by_period["M"])


# ─────────────────────────────────────────────────────────────────────────────
# 출력
# ─────────────────────────────────────────────────────────────────────────────
def _print_table(result: dict) -> None:
    print("\nperiod | source | visible | total | high | medium | low | pre→post(dedup) | missing")
    print("-" * 92)
    for p in result["periods"]:
        imp = p["annotation_count_by_importance"]
        missing = ",".join(m["kind"].replace("_candidate", "") for m in p["missing_or_unimplemented_kinds"])
        print(f"{p['period']:6} | {p['source_candle_count']:6} | {p['visible_candle_count']:7} | "
              f"{p['annotation_total_count']:5} | {imp['high']:4} | {imp['medium']:6} | {imp['low']:3} | "
              f"{p['dedup_before_count']:3}→{p['dedup_after_count']:<3}       | {missing}")


def _save(out_dir: Path, result: dict, stamp: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"annotation_diagnostics_{result['mode']}_{stamp}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="chart annotation 진단(read-only 계측)")
    p.add_argument("--fixture", action="store_true", help="합성 OHLCV로 진단(기본·KIS 호출 없음)")
    p.add_argument("--ticker", default=None, help="real KIS mode 종목코드(옵션). 지정 시 KIS 호출")
    p.add_argument("--as-of", dest="as_of", default=None, help="real KIS 기준일(ISO). 생략 시 현재")
    p.add_argument("--output-dir", dest="out_dir", default=str(_DEFAULT_OUT_DIR))
    p.add_argument("--no-save", action="store_true", help="JSON 저장 생략(콘솔만)")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    if args.ticker:  # real KIS mode (명시적으로만)
        loaded = _load_real(args.ticker, args.as_of)
        if loaded is None:
            return 1
        daily, weekly, monthly = loaded
        mode = f"real_{args.ticker}"
    else:  # fixture mode (기본)
        daily, weekly, monthly = build_fixture()
        mode = "fixture"

    result = diagnose(daily, weekly, monthly, mode=mode)
    _print_table(result)
    if not args.no_save:
        # Date.now() 사용은 스크립트 실행 시각 스탬프용(결정론 대상 아님).
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = _save(Path(args.out_dir), result, stamp)
        print(f"\n[diagnose] saved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
