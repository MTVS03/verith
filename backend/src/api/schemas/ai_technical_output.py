"""AI(technical) 응답 계약의 backend 미러 스키마.

backend 는 AI 코드(contracts.py)를 import 하지 않으므로, AI 응답을 저장하기 전에 이 미러
스키마로 검증한다(coding_guidelines §7.1: "AI JSON 검증 후 저장, 값 변경 금지").

검증 범위:
  - 필수 필드/중첩 구조(누락 시 실패)
  - 수치 범위(signal_score/confidence/weight)
  - technical_signals 의 indicator **중복 금지**(UNIQUE(report_id, indicator)와 정합)

enum 값 자체는 미러하지 않는다(AI enum 확장 시 backend 가 정상 응답을 거부하는 결합을 피함).
구조·범위·정합성 위반만 잡고, 통과한 원본(dict)은 그대로 저장한다. AI 가 추가 필드
(confidence_level·intraday_context 등)를 보내도 `extra="ignore"` 로 전방호환한다.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MirrorRegime(_Lenient):
    daily_regime: str = Field(min_length=1)
    final_regime: str = Field(min_length=1)
    weekly_trend: str = Field(min_length=1)
    monthly_trend: str = Field(min_length=1)
    alignment_flag: str = Field(min_length=1)
    regime_context: str


class MirrorSignalSummary(_Lenient):
    consensus: str = Field(min_length=1)
    signal_score: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_basis: str


class MirrorTechnicalSignal(_Lenient):
    indicator: str = Field(min_length=1)
    signal: str = Field(min_length=1)
    value: float | None = None
    metrics: list[str] = Field(default_factory=list)
    detail: str = ""
    detail_source: str = Field(min_length=1)
    weight: float = Field(ge=0.0, le=1.0)


class MirrorRiskItem(_Lenient):
    flag: str = Field(min_length=1)
    note: str
    ref_price: float | None = None


class MirrorRisk(_Lenient):
    items: list[MirrorRiskItem] = Field(default_factory=list)


class MirrorChart(_Lenient):
    period: str = Field(min_length=1)
    chart_data: dict


class MirrorInterpretation(_Lenient):
    text: str
    source: str = Field(min_length=1)
    # AI 해석 고도화(additive) — 구조화 섹션. 없어도(구버전 output) 전방호환(전부 optional).
    one_line_summary: str | None = None
    directional_bias: str | None = None
    trend_interpretation: str | None = None
    signal_interpretation: str | None = None
    risk_interpretation: str | None = None
    timeframe_alignment: str | None = None
    key_drivers: list[str] = Field(default_factory=list)
    warning_points: list[str] = Field(default_factory=list)
    what_to_watch_next: str | None = None
    invalidation_or_caution: str | None = None

    def sections_dict(self) -> dict | None:
        """구조화 섹션을 JSONB(sections 컬럼) 저장용 dict 로. 하나도 없으면(구버전) None."""
        data = {
            "one_line_summary": self.one_line_summary,
            "directional_bias": self.directional_bias,
            "trend_interpretation": self.trend_interpretation,
            "signal_interpretation": self.signal_interpretation,
            "risk_interpretation": self.risk_interpretation,
            "timeframe_alignment": self.timeframe_alignment,
            "key_drivers": self.key_drivers,
            "warning_points": self.warning_points,
            "what_to_watch_next": self.what_to_watch_next,
            "invalidation_or_caution": self.invalidation_or_caution,
        }
        has_any = any(
            v for v in data.values() if not isinstance(v, list)
        ) or self.key_drivers or self.warning_points
        return data if has_any else None


class MirrorVerification(_Lenient):
    calc_passed: bool
    regime_passed: bool
    label_matched: bool
    outcome: str = Field(min_length=1)
    regen_count: int = Field(ge=0)


class TechnicalAgentOutputMirror(_Lenient):
    """AI TechnicalAgentOutput 의 backend 검증 미러."""

    request_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    as_of: datetime
    source: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    data_status: str = Field(min_length=1)

    regime: MirrorRegime
    signal: MirrorSignalSummary | None = None
    technical_signals: list[MirrorTechnicalSignal] = Field(default_factory=list)
    risk: MirrorRisk | None = None
    charts: list[MirrorChart] = Field(default_factory=list)
    interpretation: MirrorInterpretation
    verification: MirrorVerification
    # KIS output1 best-effort 종목명(표시용). stocks 마스터에 없는 코드(ETF·외국주 등)의 이름 보강 소스.
    # 미상이면 None — _resolve_stock_name 이 `DB > 요청값 > 이 값 > ticker` 순으로 최종 선택한다.
    resolved_stock_name: str | None = None

    @model_validator(mode="after")
    def _indicators_unique(self) -> "TechnicalAgentOutputMirror":
        indicators = [s.indicator for s in self.technical_signals]
        if len(indicators) != len(set(indicators)):
            raise ValueError("technical_signals 에 중복 indicator 가 있습니다")
        return self
