"""기술적 분석 에이전트 — 내부 표준 OHLCV 모델.

KIS 국내주식기간별시세 응답(`output2`)을 코드 전역에서 쓰는 내부 표준 구조로 바꾼 결과다.
KIS 원본 필드명(`stck_bsop_date` 등)은 `services/kis_client.py` 변환 경계까지만 존재하고,
그 이후 모듈(indicators·regime·charts)은 이 모델만 본다(technical_coding_guidelines §8.2).

정본: `docs/kis_mapping.md §7`(필드 매핑)·§11(실측). `date`는 ISO(`YYYY-MM-DD`)로 정규화한다.
이번 단계 범위: 순수 데이터 모델만. pandas DataFrame·지표 계산용 파생 컬럼은 만들지 않는다.

계약 강화: 가격·거래량은 음수·inf·nan 불허(비정상 시세는 fail-fast), date는 ISO만, high는 low 이상.
"""

from __future__ import annotations

import math
import re
from datetime import date as _date
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_iso_date(value: str) -> str:
    """ISO 'YYYY-MM-DD' 형식 + 실제 달력 날짜만 허용 (schema 내부 validator, service 의존 없음)."""
    if not isinstance(value, str) or not _ISO_DATE_RE.match(value):
        raise ValueError(f"date must be ISO 'YYYY-MM-DD': {value!r}")
    try:
        _date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid calendar date: {value!r}") from exc
    return value


def _validate_finite_non_negative(value: int | float) -> int | float:
    """inf/nan 불허 + 음수 불허. int/float 표현은 그대로 보존(강제 캐스팅 없음)."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("must be a finite number (no inf/nan)")
    if value < 0:
        raise ValueError("must be >= 0")
    return value


# 재사용 타입: ISO 날짜 / 음수·inf·nan 없는 수(정수·실수 표현 보존).
IsoDate = Annotated[str, AfterValidator(_validate_iso_date)]
NonNegativeNumber = Annotated[int | float, AfterValidator(_validate_finite_non_negative)]


class OHLCV(BaseModel):
    """한 봉(일/주/월)의 내부 표준 OHLCV. 계약에 없는 필드 유입 차단(extra=forbid)."""
    model_config = ConfigDict(extra="forbid")

    date: IsoDate  # ISO "YYYY-MM-DD" (KIS 원본 "YYYYMMDD"를 kis_client에서 정규화)
    open: NonNegativeNumber
    high: NonNegativeNumber
    low: NonNegativeNumber
    close: NonNegativeNumber
    volume: int = Field(ge=0)
    trading_value: int = Field(ge=0)  # KIS `acml_tr_pbmn`(누적 거래대금). 유동성 판정 근거값.

    @model_validator(mode="after")
    def _high_ge_low(self) -> OHLCV:
        if self.high < self.low:
            raise ValueError(f"high({self.high}) must be >= low({self.low})")
        return self
