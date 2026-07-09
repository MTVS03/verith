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
    weight: float | None = None           # 신호 가중치(저장돼 있으나 그동안 미노출 → 추가)
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


# ── trust/quality summary (상단 카드용 집계 — 저장값 projection, 프론트 재계산 불필요) ──
class SignalQualityBlock(BaseModel):
    signal_score: float | None = None
    signal_label: str | None = None       # consensus 파생 라벨
    consensus: str | None = None
    confidence: float | None = None
    confidence_basis: str | None = None


class VerificationGateBlock(BaseModel):
    outcome: str | None = None
    calc_passed: bool | None = None
    regime_passed: bool | None = None
    label_matched: bool | None = None
    verification_warning: bool = False


class SourceLinkageBlock(BaseModel):
    """signal item 의 detail_source 기준 출처 연결 집계(truthful — 없으면 0)."""

    total_signal_items: int = 0
    sourced_signal_items: int = 0          # detail_source ∈ {llm, llm_regenerated}
    source_coverage_ratio: float = 0.0     # sourced/total (total=0 이면 0.0)


class TrustSummaryBlock(BaseModel):
    """상단 신뢰도/데이터품질/검증게이트/출처연결 카드용 집계."""

    signal_quality: SignalQualityBlock
    data_quality: DataQualityBlock         # trace_summary 와 동일 블록 재사용(data_status·limited·periods 등)
    verification_gate: VerificationGateBlock
    source_linkage: SourceLinkageBlock


# ── indicator card (지표 카드 UI용 — projection only, 새 판단 없음) ──────────
class AnnotationBrief(BaseModel):
    """차트 annotation 요약(패턴 후보/관련 이벤트). raw chart_data 전체가 아니라 카드용 얇은 값."""

    kind: str
    label: str | None = None
    period: str | None = None             # 부모 차트 period(annotation 자체엔 없음)
    date: str | None = None
    importance: str | None = None
    meta: dict | None = None              # kind별 계산 근거(cup_depth_pct 등) — 그대로 전달


class IndicatorCalcBasis(BaseModel):
    """지표별 계산 근거(저장 metrics/value에서 **방어적 파싱** — 실패 시 null, 조작 없음). raw chips 병기."""

    kind: str
    current_value: float | None = None
    ma: dict[str, float] | None = None    # {"5":.., "20":.., "60":..}
    alignment: str | None = None          # 정배열 | 역배열 | 혼조
    rsi_period: int | None = None
    oversold: float | None = None
    overbought: float | None = None
    relative_volume: float | None = None
    support: float | None = None
    resistance: float | None = None
    position: str | None = None           # 지지 근접 | 저항 근접 | 중간
    # 시계열/파생(차트 chart_data projection — 저장값, 계산 재실행 없음). 카드 내 표·스파크라인·바 용.
    disparity_20_pct: float | None = None                          # (현재가−20MA)/20MA ×100
    recent_ma: list[dict] = Field(default_factory=list)            # [{date, ma5?, ma20?, ma60?}] (최근 N)
    rsi_recent_points: list[dict] = Field(default_factory=list)    # [{date, value}] (스파크라인)
    current_volume: float | None = None
    avg_volume: float | None = None
    volume_recent_bars: list[dict] = Field(default_factory=list)   # [{date, volume}] (최근 N)
    metrics: list[str] = Field(default_factory=list)               # raw 계산 칩(프론트 fallback)
    related_annotations: list[AnnotationBrief] = Field(default_factory=list)


class IndicatorCard(BaseModel):
    """지표 카드 1개 — 프론트가 RSI/이동평균/거래량/지지저항/패턴을 바로 렌더."""

    indicator: str
    title: str
    signal: str | None = None
    signal_label: str | None = None       # 긍정/중립/부정
    weight: float | None = None
    llm_detail: str | None = None         # technical_signals[].detail (LLM/템플릿 문장)
    detail_source: str | None = None
    verified: bool = True                 # 리포트 verification 통과 기준(지표별 세부 검증 아님)
    code_metrics: list[str] = Field(default_factory=list)
    calc_basis: IndicatorCalcBasis
    pattern_candidates: list[AnnotationBrief] = Field(default_factory=list)  # pattern 카드만(cup_handle 등)


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
    trust_summary: TrustSummaryBlock                   # 상단 카드용 집계(신뢰도/데이터품질/검증게이트/출처연결)
    indicator_cards: list[IndicatorCard] = Field(default_factory=list)  # 지표 카드 UI용 projection
    followup_count: int = 0                            # 이 리포트에 이어진 후속 질문 수(스레드는 별도 endpoint)


# ── full chart read model (전용 endpoint GET /{id}/charts — 차트 렌더용) ──────
class ChartItemFull(BaseModel):
    """period 별 차트 full payload. chart_data 는 AI ChartData 계약(candles/overlays/subcharts/annotations)."""

    period: str
    candle_unit: str | None = None
    display_order: int
    has_chart_data: bool = False
    annotation_count: int = 0
    chart_data: dict | None = None         # 렌더용 full 구조(raw internal 아님 — AI chart 계약)
    annotations: list = Field(default_factory=list)   # 편의상 chart_data.annotations 를 승격


class TechnicalChartsReadModel(BaseModel):
    """GET /api/technical/reports/{id}/charts — 차트 탭 렌더용 full payload(detail 은 메타만 유지)."""

    report_id: UUID
    stock: StockBlock
    available_periods: list[str] = Field(default_factory=list)
    charts: list[ChartItemFull] = Field(default_factory=list)


# ── detailed trace read model (전용 endpoint GET /{id}/trace — trace drawer) ──
class TraceStepItem(BaseModel):
    """파이프라인 단계 — **저장된 결과값에서 재구성**. duration_ms 는 미측정이라 null(지어내지 않음)."""

    step_order: int
    step_key: str
    title: str
    source: str | None = None              # KIS / computed / llm / template_fallback 등
    duration_ms: int | None = None         # 현재 저장 구조상 단계별 시간 미측정 → 항상 null
    status: str                            # ok / degraded / skipped / fallback
    short_description: str | None = None
    llm_involved: bool = False


class TraceOverallBlock(BaseModel):
    total_steps: int = 0
    total_duration_ms: int | None = None   # 미측정 → null
    llm_used: bool = False
    data_source_summary: str | None = None


class TechnicalTraceDetailReadModel(BaseModel):
    """GET /api/technical/reports/{id}/trace — trace drawer 용. raw internal log dump 아님.

    steps 는 저장된 단계별 결과(source/interpretation/verification)로부터 **truthful 재구성**이며, 단계별
    duration_ms 는 현재 저장 구조에 없어 null 이다(측정/영속화되면 채운다)."""

    report_id: UUID
    overall: TraceOverallBlock
    steps: list[TraceStepItem] = Field(default_factory=list)


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


class FollowupCreateRequest(BaseModel):
    """POST /api/technical/reports/{id}/followups 요청.

    answer 는 **caller(상위/프론트)가 생성**해 전달한다 — backend 는 검증·저장·parent context snapshot 만
    한다(본문 재생성 아님). request_id/trace_id/model_name 은 caller 우선, 없으면 backend fallback/None."""

    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(min_length=1, max_length=50000)
    client_session_id: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    model_name: str | None = None


class FollowupItem(BaseModel):
    """단일 후속 질문/답변 — 제품용 메타(raw trace 아님). POST 응답 == GET list item 동일 shape."""

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


# ── list/index read model (detail 과 분리 — 목록 화면용 경량) ────────────────
class ListSummaryBlock(BaseModel):
    one_line_summary: str | None = None
    directional_bias: str | None = None
    final_regime: str | None = None


class ListStatusBlock(BaseModel):
    data_status: str | None = None
    path_label: str = "normal"
    verification_warning: bool = False
    limited_data: bool = False


class ListEngagementBlock(BaseModel):
    followup_count: int = 0


class ListMetaBlock(BaseModel):
    as_of: datetime | None = None
    created_at: datetime | None = None
    trace_id: str | None = None


class TechnicalReportListItem(BaseModel):
    """목록 1건 — 상세 진입 전 탐색/비교/판단용 핵심값(detail read model 재사용 아님, projection only)."""

    report_id: UUID
    stock: StockBlock
    summary: ListSummaryBlock
    status: ListStatusBlock
    engagement: ListEngagementBlock
    meta: ListMetaBlock


class TechnicalReportListResponse(BaseModel):
    """목록 응답 — created_at DESC. total 은 필터 기준 전체 수(pagination)."""

    items: list[TechnicalReportListItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0


class TechnicalReportFollowupsReadModel(BaseModel):
    """GET /api/technical/reports/{id}/followups — parent report 기준 대화 흐름.

    report(분석 결과)와 followups(이어진 대화)를 역할 분리해 함께 읽게 한다. followups 는 created_at 오름차순
    (대화 순서). 0개면 빈 배열."""

    report_id: UUID
    stock: StockBlock
    report_summary: FollowupReportSummary
    followup_count: int = 0
    followups: list[FollowupItem] = Field(default_factory=list)
