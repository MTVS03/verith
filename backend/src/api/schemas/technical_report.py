"""technical report API 스키마 (요청/요약응답/상세응답).

상세 응답 하위 모델은 `from_attributes=True` 로 ORM row 에서 직접 구성한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TechnicalReportCreateRequest(BaseModel):
    """POST /technical/reports 요청. request_id 는 backend 가 생성한다(입력받지 않음)."""

    ticker: str = Field(pattern=r"^\d{6}$")  # 6자리 종목코드(앞자리 0 보존)
    query: str = Field(min_length=1)
    client_session_id: str | None = None
    # stock_name 우선순위 1순위. 없으면 backend allowlist → ticker fallback.
    stock_name: str | None = None
    as_of: datetime | None = None  # 없으면 서버가 현재시각으로 채움


class TechnicalReportSummary(BaseModel):
    """POST 응답 — 저장 결과 요약."""

    report_id: UUID
    request_id: str
    agent_type: str
    ticker: str
    stock_name: str | None
    data_status: str
    created_at: datetime


# ── 상세 응답 하위 모델 (ORM row → schema) ──────────────────────────────────────
class _FromORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SignalItem(_FromORM):
    indicator: str
    timeframe: str | None
    signal: str
    value: float | None
    value_unit: str | None
    metrics: Any | None
    detail: str | None
    detail_source: str | None
    weight: float
    display_order: int | None


class ChartItem(_FromORM):
    period: str
    candle_unit: str | None
    chart_data: Any | None
    annotations: Any | None
    chart_payload: Any | None
    display_order: int | None


class RiskNoteItem(_FromORM):
    flag: str | None
    severity: str | None
    note: str | None
    ref_price: float | None
    display_order: int | None


class InterpretationItem(_FromORM):
    interpretation: str
    interpretation_source: str
    model_name: str | None
    template_fallback_used: bool
    detail_source_count: int | None
    sections: Any | None


class VerificationItem(_FromORM):
    calc_passed: bool
    regime_passed: bool
    label_matched: bool
    outcome: str
    regen_count: int
    failed_indicators: Any | None
    validation_summary: Any | None


class FollowupItem(_FromORM):
    id: UUID
    request_id: str | None
    client_session_id: str | None
    question: str | None
    answer: str | None
    model_name: str | None
    trace_id: str | None
    created_at: datetime


class TechnicalReportDetail(_FromORM):
    """GET /technical/reports/{report_id} 상세 — root + 자식들."""

    id: UUID
    request_id: str
    client_session_id: str | None
    ticker: str
    stock_name: str | None
    original_query: str | None
    normalized_query: str | None
    analysis_focus: Any | None
    final_regime: str
    daily_regime: str
    weekly_trend: str | None
    monthly_trend: str | None
    alignment_flag: str
    regime_context: str | None
    consensus: str | None
    signal_score: float | None
    confidence: float | None
    confidence_basis: str | None
    data_status: str
    source: str
    trace_id: str
    model_name: str | None
    as_of: datetime
    created_at: datetime

    signals: list[SignalItem] = Field(default_factory=list)
    charts: list[ChartItem] = Field(default_factory=list)
    risk_notes: list[RiskNoteItem] = Field(default_factory=list)
    interpretation: InterpretationItem | None = None
    verification: VerificationItem | None = None
    followups: list[FollowupItem] = Field(default_factory=list)
