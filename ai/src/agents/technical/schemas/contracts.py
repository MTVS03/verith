"""기술적 분석 에이전트 — 입출력 데이터 계약(Pydantic v2).

정본은 `docs/contracts.md`이며, 이 파일은 그 문서의 입력 스키마 1개와 출력 JSON 1개를
Pydantic 모델로 고정한 것이다. 목적:
  - 에이전트 입력/출력 JSON 구조를 코드로 고정한다.
  - LLM·각 모듈이 임의 필드를 만들지 못하게 한다(`extra="forbid"`).
  - 이후 kis_client·regime·synthesis·supervisor가 같은 코드값(enums)을 쓰게 한다.

경계(coding_guidelines §5): 에이전트는 **구조화된 JSON만 반환**한다.
HTML 렌더링·DB 저장은 이 파일 책임이 아니다(각각 frontend·backend).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .chart import ChartData
from .intraday import IntradayChartData, IntradayContext
from .enums import (
    AlignmentFlag,
    ChartPeriod,
    Consensus,
    ConfidenceLevel,
    DataStatus,
    GenerationSource,
    IndicatorType,
    Regime,
    RiskFlag,
    Signal,
    Trend,
    VerificationOutcome,
)


class _StrictModel(BaseModel):
    """모든 계약 모델의 베이스. 계약에 없는 필드가 들어오면 거부한다(임의 필드 유입 방지)."""
    model_config = ConfigDict(extra="forbid")


# ─────────────────────────────────────────────────────────────────────────────
# 입력 계약 (Top Supervisor → ai) — contracts.md §1
# ─────────────────────────────────────────────────────────────────────────────
class TechnicalAgentInput(_StrictModel):
    ticker: str  # 6자리 종목코드. 앞자리 0 보존을 위해 반드시 str.
    query: str  # 기술적 분석 관점으로 변형된 도메인 질의
    request_id: str  # 요청 추적용 런타임 필드. 출력에 되돌려주지만 DB에는 저장하지 않음.
    as_of: datetime  # 분석 기준 시점(ISO8601). 문자열 입력을 Pydantic이 파싱.


# ─────────────────────────────────────────────────────────────────────────────
# 출력 하위 구조 — contracts.md §2
# ─────────────────────────────────────────────────────────────────────────────
class RegimeResult(_StrictModel):
    """멀티프레임 국면. → TECHNICAL_REPORTS. LLM이 바꿀 수 없는 코드 확정값."""
    daily_regime: Regime
    final_regime: Regime
    weekly_trend: Trend
    monthly_trend: Trend
    alignment_flag: AlignmentFlag
    regime_context: str


class SignalSummary(_StrictModel):
    """신호 종합·신뢰도. regime 판단 불가 시 상위에서 null 가능(종합·신뢰도 스킵)."""
    consensus: Consensus
    signal_score: float = Field(ge=-1.0, le=1.0)  # 방향·세기 (glossary: -1.0 ~ 1.0)
    confidence: float = Field(ge=0.0, le=1.0)     # 신뢰도 (0.0 ~ 1.0)
    # confidence_level 은 confidence(float)에서 재계산 가능한 파생값이라 DB에 저장하지 않는다
    # (contracts.md §3·§4, enums.md §6). 출력 JSON에는 표시용으로 포함한다.
    confidence_level: ConfidenceLevel
    confidence_basis: str


class TechnicalSignal(_StrictModel):
    """지표별 기술 신호. → REPORT_SIGNALS.

    코드 확정(indicator·signal·value·metrics·weight)과 LLM 서술(detail)의 경계를 한 항목에 담는다.
    필드명은 `indicator`이며 `strategy`는 쓰지 않는다(contracts.md).
    """
    indicator: IndicatorType  # 코드 확정
    signal: Signal  # 코드 확정 (LLM이 바꿀 수 없음)
    # 코드 확정 대표 수치. 계산 가능하면 숫자, 데이터 부족 등으로 계산 불가하면 None.
    # None은 0을 의미하지 않는다(honest scoping). IndicatorSignalResult.value(float|None)와 정합.
    value: float | None
    metrics: list[str]  # 코드 확정 (표시용 수치 칩 배열, 예: "5MA 82,900")
    detail: str  # LLM 서술 (위 확정값을 자연어로 풀이)
    detail_source: GenerationSource  # detail 문장의 최종 출처
    weight: float = Field(ge=0.0, le=1.0)  # 코드 확정 (config.md INDICATOR_WEIGHTS)


class RiskItem(_StrictModel):
    """리스크 관찰점 1건. → REPORT_RISK_NOTES. flag·note·ref_price를 한 항목에 묶어 짝짓기 오류 방지."""
    flag: RiskFlag
    note: str
    ref_price: float | None = None


class RiskSummary(_StrictModel):
    items: list[RiskItem]


class ChartPayload(_StrictModel):
    """기간별 차트. → REPORT_CHARTS. chart_data는 자유 dict가 아니라 chart_annotation_spec.md 정본
    구조를 따르는 계약으로 검증한다. D/W/M은 ChartData(schemas/chart.py), 1d 장중 분봉은
    IntradayChartData(schemas/intraday.py)로, `candle_unit`을 discriminator로 하는 판별 유니온이다.
    chart_builder가 만든 dict가 여기서 candle_unit에 따라 해당 타입으로 파싱·검증된다."""
    period: ChartPeriod
    # D/W/M → ChartData(candle_unit D/W/M), 1d → IntradayChartData(candle_unit "1min").
    chart_data: ChartData | IntradayChartData = Field(discriminator="candle_unit")

    # period ↔ candle_unit 정합 (chart_annotation_spec §3·§3.1): 3m·1y=D, 5y=W, 1d=1min.
    @model_validator(mode="after")
    def _period_matches_candle_unit(self) -> ChartPayload:
        expected = {ChartPeriod.THREE_MONTHS: "D", ChartPeriod.ONE_YEAR: "D",
                    ChartPeriod.FIVE_YEARS: "W", ChartPeriod.ONE_DAY: "1min"}[self.period]
        if self.chart_data.candle_unit != expected:
            raise ValueError(
                f"period={self.period.value}의 candle_unit은 {expected}여야 합니다: "
                f"{self.chart_data.candle_unit}"
            )
        return self


class InterpretationResult(_StrictModel):
    """종합 해석 문장. → REPORT_INTERPRETATION. 원칙적으로 항상 존재(검증 실패 시 template_fallback 문장)."""
    text: str
    source: GenerationSource


class VerificationResult(_StrictModel):
    """검증 결과. → REPORT_VERIFICATION."""
    calc_passed: bool
    regime_passed: bool
    label_matched: bool
    outcome: VerificationOutcome
    regen_count: int


# ─────────────────────────────────────────────────────────────────────────────
# 출력 계약 (ai → Top Supervisor → backend) — contracts.md §2
# ─────────────────────────────────────────────────────────────────────────────
class TechnicalAgentOutput(_StrictModel):
    """에이전트 최종 반환 JSON. 의미 단위 중첩 구조 유지(backend가 테이블별 flatten 저장)."""
    request_id: str  # 런타임 필드(입력에서 되돌려줌). DB 저장 대상 아님.
    ticker: str
    as_of: datetime
    # 데이터(시세) 출처 라벨. test_plan §7: 최상위 source는 KIS / KIS (stale)만 허용.
    # 문장 출처(interpretation.source·detail_source = GenerationSource, llm 등)와 혼동 금지.
    source: Literal["KIS", "KIS (stale)"]
    trace_id: str  # AI Technical Supervisor가 생성.
    data_status: DataStatus

    regime: RegimeResult
    # signal·risk 는 판단 불가(regime_unavailable / data_limited-B) 시 null 가능(contracts.md §5).
    signal: SignalSummary | None = None
    technical_signals: list[TechnicalSignal] = Field(default_factory=list)
    risk: RiskSummary | None = None
    charts: list[ChartPayload] = Field(default_factory=list)
    # interpretation 은 항상 존재(null 아님) — 불가 시 template_fallback 문장으로 안전 착지.
    interpretation: InterpretationResult
    verification: VerificationResult
    # 1D 장중 분봉 보조 컨텍스트(Beta). 없으면 None — 기존 D/W/M 분석은 그대로 통과한다.
    # final_regime 을 바꾸지 않는 보조 근거이며, 생성·보정 로직은 후속(Phase 2)에서 붙는다.
    intraday_context: IntradayContext | None = None
