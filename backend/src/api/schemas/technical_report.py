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


# ── trace summary 블록(제품용 — "어떻게 생성됐고 얼마나 안정적인지". raw trace dump 아님) ──
class GenerationPathBlock(BaseModel):
    """생성 경로 — 정상/재생성/fallback. 저장값 파생, 재해석 없음."""

    source: str | None = None                       # 시세 출처(KIS / KIS (stale))
    interpretation_source: str | None = None         # llm / llm_regenerated / template_fallback
    template_fallback_used: bool = False
    regen_count: int | None = None
    path_label: str = "normal"                        # normal | regenerated | template_fallback


class DataQualityBlock(BaseModel):
    data_status: str | None = None
    available_periods: list[str] = Field(default_factory=list)
    intraday_available: bool = False
    chart_count: int = 0
    limited: bool = False


class VerificationSummaryBlock(BaseModel):
    """제품용 검증 요약(상세는 `verification` 블록 유지)."""

    outcome: str | None = None
    calc_passed: bool | None = None
    regime_passed: bool | None = None
    label_matched: bool | None = None
    failed_indicators_count: int = 0


class StabilityBlock(BaseModel):
    confidence: float | None = None
    confidence_basis: str | None = None
    verification_consistent: bool | None = None       # calc∧regime∧label


class TraceFlagsBlock(BaseModel):
    """뱃지/서브패널용 boolean projection(저장값 기반, 재해석 없음)."""

    used_fallback: bool = False
    had_regeneration: bool = False
    limited_data: bool = False
    verification_warning: bool = False
    has_intraday_context: bool = False
    has_daily_chart: bool = False
    has_weekly_chart: bool = False
    has_monthly_chart: bool = False


class TraceSummaryBlock(BaseModel):
    """생성/검증/품질 요약 — 결과 해석(summary/interpretation)과 역할 분리."""

    trace_id: str | None = None
    generation_path: GenerationPathBlock
    data_quality: DataQualityBlock
    verification_summary: VerificationSummaryBlock
    stability: StabilityBlock
    flags: TraceFlagsBlock


class TechnicalReportReadModel(BaseModel):
    """POST/GET 단건 응답 — 프론트가 섹션별로 바로 렌더할 수 있는 read model.

    모든 값은 저장/계산된 값의 projection 이다(backend 재해석 없음). optional 필드가 비어도 shape 는 안정적.
    `trace_summary` 는 "어떻게 생성됐고 얼마나 안정적인지"(생성 경로·데이터 품질·검증 요약·flag)를 제품용으로
    요약한다 — raw trace/프롬프트/내부 로그는 노출하지 않는다."""

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
    trace_summary: TraceSummaryBlock
    followup_count: int = 0                            # 이 리포트에 이어진 후속 질문 수(스레드는 별도 endpoint)


# ── follow-up read flow (parent report 기준 대화 흐름) ──────────────────────
class FollowupContextBlock(BaseModel):
    """follow-up 의 base(parent) report context 요약 — raw context_snapshot 미노출, 방어적 projection.

    context_snapshot(JSONB, writer 미정의)에서 알려진 키만 뽑는다. 없으면 None/False 로 안정."""

    has_context_snapshot: bool = False
    base_report_regime: str | None = None
    base_report_bias: str | None = None
    base_report_data_status: str | None = None
    base_report_signal_score: float | None = None
    base_report_as_of: str | None = None


class FollowupItem(BaseModel):
    """단일 후속 질문/답변 — 제품용 메타(raw trace 아님)."""

    followup_id: UUID
    request_id: str | None = None
    question: str | None = None
    answer: str | None = None
    model_name: str | None = None
    trace_id: str | None = None
    created_at: datetime | None = None
    answer_length: int = 0
    context: FollowupContextBlock


class FollowupReportSummary(BaseModel):
    """follow-up 스레드 헤더용 parent report 요약(연결감)."""

    one_line_summary: str | None = None
    directional_bias: str | None = None
    final_regime: str | None = None
    as_of: datetime | None = None


class TechnicalReportFollowupsReadModel(BaseModel):
    """GET /api/technical/reports/{id}/followups — parent report 기준 대화 흐름.

    report(분석 결과)와 followups(이어진 대화)를 역할 분리해 함께 읽게 한다. followups 는 created_at 오름차순
    (대화 순서). 0개면 빈 배열."""

    report_id: UUID
    stock: StockBlock
    report_summary: FollowupReportSummary
    followup_count: int = 0
    followups: list[FollowupItem] = Field(default_factory=list)
