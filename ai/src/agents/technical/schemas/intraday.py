"""1D intraday(당일 분봉) 계약 모델 — `chart_annotation_spec.md §3.1`(Beta) 정본.

D/W/M `OHLCV`(schemas/ohlcv.py, **날짜 전용**)와 분리한다. 기존 `OHLCV.date`(YYYY-MM-DD)는
변경하지 않고, intraday 봉은 **`timestamp`(YYYY-MM-DDTHH:MM:SS)** 를 쓴다.

원칙:
  - 문서에 없는 key 차단(extra="forbid"). 수치는 inf/nan·음수 불허(OHLCV 정책 재사용).
  - `candle_unit`은 `"1min"` 고정(v1) — `ChartPayload.chart_data` 판별 유니온의 discriminator.
    `"3m"`(=ChartPeriod 3개월)와 혼동을 피하기 위해 분봉 단위는 `"1min"`으로 둔다.
  - 이 단계 범위: **계약 스키마만.** KIS 분봉 fetcher는 공식 API 매핑 확정 후(`kis_mapping.md §12`) 구현한다.
  - v1 필수: candles·volume(candle 내)·previous_close·day_high/low·short_ma.
    vwap·rsi 는 선택/후순위라 빈 배열로 예약한다(계약 확장 없이 이후 채움).
"""

from __future__ import annotations

import re
from datetime import datetime as _datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from .ohlcv import NonNegativeNumber  # inf/nan·음수 불허 재사용(중복 정의 금지)

_ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def _validate_iso_datetime(value: str) -> str:
    """ISO 'YYYY-MM-DDTHH:MM:SS' 형식 + 실제 달력·시각만 허용(초 단위, tz 없음)."""
    if not isinstance(value, str) or not _ISO_DATETIME_RE.match(value):
        raise ValueError(f"timestamp must be ISO 'YYYY-MM-DDTHH:MM:SS': {value!r}")
    try:
        _datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid datetime: {value!r}") from exc
    return value


# 재사용 타입: 초 단위 ISO datetime 문자열(날짜 전용 IsoDate와 구분).
IsoDateTime = Annotated[str, AfterValidator(_validate_iso_datetime)]

# v1은 1분봉 우선. 3/5분은 KIS 분봉 API 매핑·실제 응답 확인 후 확장(kis_mapping §12).
IntradayInterval = Literal["1min"]


class _StrictModel(BaseModel):
    """intraday 하위 모델 공통 베이스 — 문서에 없는 key 거부."""
    model_config = ConfigDict(extra="forbid")


class IntradayCandle(_StrictModel):
    """한 분봉. D/W/M OHLCV와 달리 `timestamp`(날짜+시각)를 가진다."""
    timestamp: IsoDateTime
    open: NonNegativeNumber
    high: NonNegativeNumber
    low: NonNegativeNumber
    close: NonNegativeNumber
    volume: int = Field(ge=0)
    # KIS 분봉 응답에 거래대금이 없을 수 있어 optional (kis_mapping §12.4).
    trading_value: int | None = Field(default=None, ge=0)
    interval: IntradayInterval

    @model_validator(mode="after")
    def _high_ge_low(self) -> IntradayCandle:
        if self.high < self.low:
            raise ValueError(f"high({self.high}) must be >= low({self.low})")
        return self


class IntradayPoint(_StrictModel):
    """시각별 파생 수치 1점 — short MA / VWAP / intraday RSI 공용(라인 시리즈)."""
    timestamp: IsoDateTime
    value: float = Field(ge=0, allow_inf_nan=False)


class IntradayChartData(_StrictModel):
    """1d 차트 데이터. `ChartPayload.chart_data` 판별 유니온의 intraday 분기.

    D/W/M `ChartData`와 완전히 분리된 타입이며, candle_unit="1min"으로 구분된다.
    """
    candle_unit: Literal["1min"]  # 판별 유니온 discriminator
    candles: list[IntradayCandle]
    previous_close: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    day_high: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    day_low: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    short_ma: list[IntradayPoint] = Field(default_factory=list)
    # 선택/후순위(Phase 이후) — 지금은 빈 배열로 예약해 계약 확장 없이 채운다.
    vwap: list[IntradayPoint] = Field(default_factory=list)
    rsi: list[IntradayPoint] = Field(default_factory=list)
