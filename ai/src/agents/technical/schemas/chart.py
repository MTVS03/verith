"""chart_data 계약 모델.

`chart_annotation_spec.md §5~§7` 정본 구조를 Pydantic으로 고정한다. `ChartPayload.chart_data`가
이 `ChartData`로 검증되어(자유 dict 아님) 문서와 다른 구조는 거부된다. chart_builder는 이 구조의
dict를 생성하고, contracts가 이 모델로 파싱·검증한다(생성 로직은 chart_builder 그대로).

원칙(technical_coding_guidelines):
  - 문서에 없는 key 차단: 전 하위 모델 extra="forbid" (단 annotation.meta는 계산 근거용 자유 dict).
  - 필드 타입은 chart_builder 실제 출력 타입에 맞춰(int/float) JSON 표현을 보존한다.
  - candles는 내부 표준 OHLCV를 재사용한다(중복 모델 금지).
  - support_resistance의 `from`은 파이썬 예약어라 alias 처리하고, 출력에서 항상 "from"을 유지한다.
  - 수치는 inf/nan·음수를 허용하지 않고, date는 ISO만, RSI oversold<overbought를 강제한다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ohlcv import OHLCV, IsoDate

# annotation kind 정본은 chart_annotation_spec.md §7 — 전체 10종을 계약상 허용한다.
# (chart_builder는 MVP 8종만 생성; box_breakout·cup_handle은 후속.)
AnnotationKind = Literal[
    "golden_cross",
    "dead_cross",
    "volume_spike",
    "support_touch",
    "resistance_touch",
    "rsi_overbought",
    "rsi_oversold",
    "box_range_candidate",
    "box_breakout_candidate",
    "cup_handle_candidate",
]


class _StrictModel(BaseModel):
    """chart 하위 모델 공통 베이스 — 문서에 없는 key 거부."""
    model_config = ConfigDict(extra="forbid")


# ── overlays ──────────────────────────────────────────────────────────────────
class MaPoint(_StrictModel):
    date: IsoDate
    value: float = Field(ge=0, allow_inf_nan=False)


class MovingAverageOverlay(_StrictModel):
    window: int = Field(gt=0)
    points: list[MaPoint]


class SupportResistanceOverlay(_StrictModel):
    # `from`은 파이썬 예약어 → alias. serialize_by_alias로 기본 직렬화에서도 "from" 유지.
    model_config = ConfigDict(extra="forbid", serialize_by_alias=True)

    type: Literal["support", "resistance"]
    price: float = Field(ge=0, allow_inf_nan=False)
    from_: IsoDate = Field(alias="from")
    to: IsoDate
    touch_count: int = Field(ge=0)


class Overlays(_StrictModel):
    moving_average: list[MovingAverageOverlay]
    support_resistance: list[SupportResistanceOverlay]


# ── subcharts ─────────────────────────────────────────────────────────────────
class RsiPoint(_StrictModel):
    date: IsoDate
    value: float = Field(ge=0, le=100, allow_inf_nan=False)


class RsiSubchart(_StrictModel):
    period: int = Field(gt=0)
    overbought: int = Field(ge=0, le=100)
    oversold: int = Field(ge=0, le=100)
    points: list[RsiPoint]

    @model_validator(mode="after")
    def _oversold_lt_overbought(self) -> RsiSubchart:
        if self.oversold >= self.overbought:
            raise ValueError(f"oversold({self.oversold}) must be < overbought({self.overbought})")
        return self


class VolumeBar(_StrictModel):
    date: IsoDate
    volume: int = Field(ge=0)
    avg_volume: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    is_spike: bool


class VolumeSubchart(_StrictModel):
    avg_window: int = Field(gt=0)
    bars: list[VolumeBar]


class Subcharts(_StrictModel):
    rsi: RsiSubchart
    volume: VolumeSubchart


# ── annotations ───────────────────────────────────────────────────────────────
class ChartAnnotation(_StrictModel):
    id: str
    kind: AnnotationKind
    date: IsoDate
    price: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    label: str
    importance: Literal["low", "medium", "high"]
    source: Literal["code"]  # 필수 (chart_annotation_spec §6). default 없음.
    meta: dict[str, Any] = Field(default_factory=dict)  # 계산 근거 자유 bag


# ── chart_data 최상위 ─────────────────────────────────────────────────────────
class ChartData(_StrictModel):
    candle_unit: Literal["D", "W", "M"]
    candles: list[OHLCV]  # 내부 표준 OHLCV 재사용 (finite·비음수·ISO·high>=low 상속)
    overlays: Overlays
    subcharts: Subcharts
    annotations: list[ChartAnnotation]
