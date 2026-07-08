"""technical report API 스키마.

**조회 계약 = read model**(프론트 친화적, 카드 렌더용). 저장 계약(DB raw output_payload)과 분리한다 —
DB 에는 raw payload 를 계속 보존(디버깅/백오피스)하되, API 응답은 구조화 read model 로 정리한다.
POST(저장 직후)·GET(단건) 모두 이 read model 로 일관되게 반환한다. 목록 조회는 경량 인덱스
(`AgentReportListItem`)로 별도 유지한다(표준 REST: list=요약, detail=full).

값은 **기존 계산/저장값만** 사용한다 — backend 는 LLM 내용을 재생성/재추론하지 않고 구조만 정리한다.
`stock` 블록은 **canonical stocks 기준**(technical 저장 당시 중복 문자열보다 우선).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TechnicalReportCreateRequest(BaseModel):
    """POST /api/technical/reports 요청. request_id 는 backend 가 생성한다(입력받지 않음)."""

    ticker: str = Field(pattern=r"^\d{6}$")  # 6자리 종목코드(앞자리 0 보존)
    query: str = Field(min_length=1)
    client_session_id: str | None = None
    # stock_name 은 종목 마스터가 우선. 요청값은 미지 종목일 때만 보조로 쓰인다(서비스에서 판단).
    stock_name: str | None = None
    as_of: datetime | None = None  # 없으면 서버가 현재시각으로 채움


# ── read model 블록 ──────────────────────────────────────────────────────────
class StockBlock(BaseModel):
    """canonical 종목 context(stocks 기준)."""

    stock_code: str
    stock_name: str | None = None
    market: str | None = None


class MetaBlock(BaseModel):
    request_id: str | None = None
    trace_id: str | None = None
    as_of: datetime | None = None
    source: str | None = None
    data_status: str | None = None
    model_name: str | None = None


class SummaryBlock(BaseModel):
    """한눈 요약 — 카드 헤더용."""

    one_line_summary: str | None = None
    directional_bias: str | None = None      # bullish/neutral/bearish (AI 파생)
    final_regime: str | None = None
    daily_regime: str | None = None
    weekly_trend: str | None = None
    monthly_trend: str | None = None
    alignment_flag: str | None = None
    timeframe_alignment: str | None = None


class InterpretationBlock(BaseModel):
    """structured 해석 — 프론트가 text blob 파싱에 의존하지 않게. text 는 호환/백업용 유지."""

    text: str | None = None
    source: str | None = None
    trend_interpretation: str | None = None
    signal_interpretation: str | None = None
    risk_interpretation: str | None = None
    what_to_watch_next: str | None = None
    invalidation_or_caution: str | None = None


class DriversBlock(BaseModel):
    key_drivers: list[str] = Field(default_factory=list)
    warning_points: list[str] = Field(default_factory=list)


class SignalItem(BaseModel):
    indicator: str
    signal: str | None = None
    value: float | None = None
    metrics: list[str] = Field(default_factory=list)
    detail: str | None = None
    detail_source: str | None = None


class SignalsBlock(BaseModel):
    signal_score: float | None = None
    consensus: str | None = None
    confidence: float | None = None
    confidence_basis: str | None = None
    items: list[SignalItem] = Field(default_factory=list)


class RiskItemBlock(BaseModel):
    flag: str
    note: str | None = None
    ref_price: float | None = None


class RisksBlock(BaseModel):
    items: list[RiskItemBlock] = Field(default_factory=list)


class ChartItem(BaseModel):
    period: str
    candle_unit: str | None = None
    display_order: int
    has_chart_data: bool = False
    annotation_count: int = 0


class ChartsBlock(BaseModel):
    available_periods: list[str] = Field(default_factory=list)
    items: list[ChartItem] = Field(default_factory=list)


class VerificationBlock(BaseModel):
    outcome: str | None = None
    calc_passed: bool | None = None
    regime_passed: bool | None = None
    label_matched: bool | None = None
    regen_count: int | None = None
    failed_indicators: list[str] = Field(default_factory=list)
    summary: str | None = None


class TechnicalReportReadModel(BaseModel):
    """POST/GET 단건 응답 — 프론트가 섹션별로 바로 렌더할 수 있는 read model.

    모든 값은 저장/계산된 값의 projection 이다(backend 재해석 없음). optional 필드가 비어도 shape 는 안정적."""

    report_id: UUID
    stock: StockBlock
    meta: MetaBlock
    summary: SummaryBlock
    interpretation: InterpretationBlock
    drivers: DriversBlock
    signals: SignalsBlock
    risks: RisksBlock
    charts: ChartsBlock
    verification: VerificationBlock
