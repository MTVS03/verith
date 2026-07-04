"""기술적 분석 에이전트 — 열거값(enum) 코드값 정본 반영.

정본은 `docs/enums.md`이며, 이 파일은 그 문서의 코드값(영문 snake_case)을 코드로 1:1 옮긴 것이다.
- 코드값(영문)만 코드·DB·API에서 쓴다. **한글 표시 라벨은 여기 두지 않는다**(프론트가 매핑).
- 값 추가·변경은 문서(enums.md)를 먼저 고친 뒤 반영한다. 문서에 없는 값을 임의로 만들지 않는다.
- 매수/매도 같은 표현은 코드값·라벨·필드 어디에도 쓰지 않는다(honest scoping, enums.md 사용 규약 3).
"""

from __future__ import annotations

from enum import Enum


class Regime(str, Enum):
    """국면 — `daily_regime` · `final_regime` 공통 값 집합 (enums.md §1)."""
    OVERSOLD_REBOUND_WATCH = "oversold_rebound_watch"
    OVERHEATED = "overheated"
    BULLISH_REVERSAL_WATCH = "bullish_reversal_watch"
    UPTREND_INTACT = "uptrend_intact"
    DOWNTREND = "downtrend"
    SIDEWAYS = "sideways"
    UNAVAILABLE = "unavailable"


class Consensus(str, Enum):
    """신호 종합 — `signal.consensus` (enums.md §2). 경계값은 config(MVP 잠정)."""
    STRONG_POSITIVE = "strong_positive"
    WEAK_POSITIVE = "weak_positive"
    NEUTRAL = "neutral"
    WEAK_NEGATIVE = "weak_negative"
    STRONG_NEGATIVE = "strong_negative"


class Signal(str, Enum):
    """지표별 개별 신호 — `technical_signals[].signal` (enums.md §3)."""
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class Trend(str, Enum):
    """타임프레임 추세 — `weekly_trend` · `monthly_trend` (enums.md §4)."""
    UP = "up"
    DOWN = "down"
    SIDEWAYS = "sideways"
    UNAVAILABLE = "unavailable"


class AlignmentFlag(str, Enum):
    """멀티프레임 정합 — `alignment_flag` (enums.md §5)."""
    ALIGNED = "aligned"
    COUNTER_TREND = "counter_trend"
    NEUTRAL = "neutral"


class ConfidenceLevel(str, Enum):
    """신뢰도 구간(표시용) — `confidence`에서 파생. **DB 저장 안 함** (enums.md §6, contracts.md §3)."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RiskFlag(str, Enum):
    """리스크 라벨(코드 생성 배열) — `risk.items[].flag` (enums.md §7)."""
    VOLUME_NOT_CONFIRMED = "volume_not_confirmed"
    NEAR_RESISTANCE = "near_resistance"
    NEAR_SUPPORT = "near_support"
    MIXED_SIGNALS = "mixed_signals"
    OVERHEATED_MOMENTUM = "overheated_momentum"
    COUNTER_HIGHER_TREND = "counter_higher_trend"
    LOW_LIQUIDITY = "low_liquidity"


class DataStatus(str, Enum):
    """데이터/분석 상태 — `data_status` (enums.md §8)."""
    NORMAL = "normal"
    STALE_CACHE = "stale_cache"
    DATA_LIMITED = "data_limited"
    REGIME_UNAVAILABLE = "regime_unavailable"


class GenerationSource(str, Enum):
    """LLM 문장 최종 출처 — `interpretation.source` · `technical_signals[].detail_source` 공유 (enums.md §9).

    필드명은 contracts 기준대로 `source` / `detail_source`를 각각 유지하되, 값 집합은 이 하나를 공유한다.
    """
    LLM = "llm"
    LLM_REGENERATED = "llm_regenerated"
    TEMPLATE_FALLBACK = "template_fallback"


class ChartPeriod(str, Enum):
    """차트 기간 — `charts[].period` (enums.md §10). 멤버명은 숫자로 시작 못 해 영문으로 둔다."""
    THREE_MONTHS = "3m"
    ONE_YEAR = "1y"
    FIVE_YEARS = "5y"


class VerificationOutcome(str, Enum):
    """검증 최종 결과 — `verification.outcome`.

    enums.md에 별도 표는 없고 contracts.md 예시에서 확인되는 값만 반영한다.
    재생성/부분 실패 등은 별도 값이 아니라 `regen_count`·`interpretation_source`·`detail_source`로 표현한다.
    """
    PASSED = "passed"
    TEMPLATE_FALLBACK = "template_fallback"


class IndicatorType(str, Enum):
    """지표 종류 — `technical_signals[].indicator` (contracts.md). 기본 5개만 허용(오타·임의값 방지)."""
    MOVING_AVERAGE = "moving_average"
    RSI = "rsi"
    VOLUME = "volume"
    SUPPORT_RESISTANCE = "support_resistance"
    PATTERN = "pattern"
