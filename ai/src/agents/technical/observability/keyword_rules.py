"""검증 ③ 키워드 사전 — LLM 문장이 코드 확정 라벨·신호를 왜곡했는지 판정하는 표현 규칙.

정본: `docs/test_plan.md §5.4`(라벨 사전)·§5.3(매칭 규칙). 여기는 **사전(데이터)만** 두고,
판정 로직은 `observability/trajectory_eval.py`가 갖는다(config는 수치, 사전은 검증 코드 옆).

- `required_any`: 확정 라벨을 문장에 담았다고 볼 수 있는 대표 표현(하나 이상 등장해야 통과).
- `conflict_any`: 확정 라벨과 반대되는 충돌 표현(등장하면 실패). 대표 표현과 겹치는 짧은
  충돌어는 판정 로직에서 무효화한다(test_plan §5.3 규칙 3).
- `require_representative=False`: 대표 표현 존재를 요구하지 않고 충돌 표현만 검사한다.
  (중립 정합·지표별 detail은 "특정 문구를 반드시 써야 한다"가 과함이라 충돌만 본다 —
   detail 왜곡 테스트 DETAIL-01·02는 전부 충돌 케이스다.)

`forbidden_terms`(매수·매도 등)는 라벨과 무관하게 어느 문장에서든 등장하면 실패다(부정문 안이어도).
표시 라벨(한글) 표현은 template fallback 문장에서도 공유하기 위해 여기에 모아 둔다(test_plan §5.1).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas.enums import (
    AlignmentFlag,
    ConfidenceLevel,
    Consensus,
    IndicatorType,
    Regime,
    RiskFlag,
    Signal,
)


@dataclass(frozen=True)
class LabelRule:
    """한 확정값(라벨/신호)에 대한 대표 표현·충돌 표현 규칙."""
    required_any: tuple[str, ...] = ()
    conflict_any: tuple[str, ...] = ()
    require_representative: bool = True


# ── regime (final_regime) — test_plan §5.4. unavailable은 template fallback 경로라 사전 없음.
REGIME_RULES: dict[Regime, LabelRule] = {
    Regime.SIDEWAYS: LabelRule(
        required_any=("횡보", "박스권", "방향성 제한"),
        conflict_any=("상승 전환", "상승 추세", "하락 추세"),
    ),
    Regime.OVERHEATED: LabelRule(
        required_any=("과열", "단기 과열", "과매수"),
        conflict_any=("과매도", "하락 추세"),
    ),
    Regime.OVERSOLD_REBOUND_WATCH: LabelRule(
        required_any=("과매도", "과매도 반등", "반등 관찰"),
        conflict_any=("과열", "상승 추세 유지"),
    ),
    Regime.BULLISH_REVERSAL_WATCH: LabelRule(
        required_any=("상승 전환 관찰", "반등 신호 관찰", "상승 전환"),
        conflict_any=("하락 추세", "부정 우세"),
    ),
    Regime.UPTREND_INTACT: LabelRule(
        required_any=("상승 추세 유지", "정배열 유지"),
        conflict_any=("하락 추세", "횡보"),
    ),
    Regime.DOWNTREND: LabelRule(
        required_any=("하락 추세", "약세 흐름"),
        conflict_any=("상승 전환", "상승 추세"),
    ),
}


# ── consensus — test_plan §5.4.
CONSENSUS_RULES: dict[Consensus, LabelRule] = {
    Consensus.STRONG_POSITIVE: LabelRule(
        required_any=("강한 긍정", "긍정 우세"),
        conflict_any=("부정", "약세"),
    ),
    Consensus.WEAK_POSITIVE: LabelRule(
        required_any=("약한 긍정", "제한적 긍정", "긍정 신호 일부"),
        conflict_any=("부정 우세", "약세 우세"),
    ),
    Consensus.NEUTRAL: LabelRule(
        required_any=("중립", "신호 엇갈림", "방향성 제한"),
        conflict_any=("긍정 우세", "부정 우세"),
    ),
    Consensus.WEAK_NEGATIVE: LabelRule(
        required_any=("약한 부정", "부정 신호 일부"),
        conflict_any=("긍정 우세", "강한 긍정"),
    ),
    Consensus.STRONG_NEGATIVE: LabelRule(
        required_any=("강한 부정", "부정 우세"),
        conflict_any=("긍정", "강세"),
    ),
}


# ── alignment_flag — test_plan §5.4. 중립은 "정합/역행을 단정하지 않았는지"만 본다(대표어 미요구).
ALIGNMENT_RULES: dict[AlignmentFlag, LabelRule] = {
    AlignmentFlag.ALIGNED: LabelRule(
        required_any=("정합", "상위 추세와 일치", "방향이 일치"),
        conflict_any=("역행", "상위 추세와 반대"),
    ),
    AlignmentFlag.COUNTER_TREND: LabelRule(
        required_any=("역행", "상위 추세와 반대", "대세 흐름과 반대"),
        conflict_any=("정합", "방향이 일치"),
    ),
    # 중립은 대표어를 강제하지 않되(require_representative=False), 대표어를 문장에 쓴 경우
    # 그 안의 "정합"·"역행"이 충돌어로 오판되지 않도록 required_any로 등록해 무효화한다(§5.3 규칙 3).
    AlignmentFlag.NEUTRAL: LabelRule(
        required_any=("정합/역행 판정 대상 아님", "방향성 판정 없음", "중립"),
        conflict_any=("정합", "역행"),
        require_representative=False,
    ),
}


# ── 지표별 detail signal — 대표어 필수 + 반전 서술 차단(test_plan §5.4·§5.6).
# neutral 충돌어는 "긍정/부정" 단독이 아니라 방향 단정 표현으로 둔다 — "긍정도 부정도 아닌 중립"
# 같은 정상 중립 서술을 오탐하지 않기 위함.
SIGNAL_RULES: dict[Signal, LabelRule] = {
    Signal.POSITIVE: LabelRule(
        required_any=("긍정",),
        conflict_any=("부정", "약세"),
    ),
    Signal.NEUTRAL: LabelRule(
        required_any=("중립",),
        conflict_any=("강한 긍정", "강한 부정", "긍정 우세", "부정 우세"),
    ),
    Signal.NEGATIVE: LabelRule(
        required_any=("부정",),
        conflict_any=("긍정", "강세"),
    ),
}


# ── confidence_level — 반대 라벨 신뢰도 단정만 잡는다(대표어 미요구, test_plan §5.4).
# medium은 양방향 단정을 결정론으로 가르기 어려워 검사하지 않는다(Future Work).
CONFIDENCE_RULES: dict[ConfidenceLevel, LabelRule] = {
    ConfidenceLevel.LOW: LabelRule(
        conflict_any=("높은 신뢰도", "신뢰도가 높", "신뢰도는 높", "신뢰도 높음", "매우 높은 신뢰"),
        require_representative=False,
    ),
    ConfidenceLevel.HIGH: LabelRule(
        conflict_any=("낮은 신뢰도", "신뢰도가 낮", "신뢰도는 낮", "신뢰도 낮음"),
        require_representative=False,
    ),
    ConfidenceLevel.MEDIUM: LabelRule(require_representative=False),
}


# ── risk 언급 판정어 — risk.items가 있는데 interpretation이 하나도 언급 안 하면 실패(test_plan §5.4).
# 확정 flag 중 최소 1개의 판정어가 문장에 있으면 통과(전부 나열할 필요 없음).
RISK_MENTION_TERMS: dict[RiskFlag, tuple[str, ...]] = {
    RiskFlag.VOLUME_NOT_CONFIRMED: ("거래량",),
    RiskFlag.NEAR_RESISTANCE: ("저항",),
    RiskFlag.NEAR_SUPPORT: ("지지",),
    RiskFlag.MIXED_SIGNALS: ("엇갈", "혼재"),
    RiskFlag.OVERHEATED_MOMENTUM: ("과열", "과매수"),
    RiskFlag.COUNTER_HIGHER_TREND: ("역행", "상위 추세"),
    RiskFlag.LOW_LIQUIDITY: ("유동성", "거래대금"),
}


# ── 금지어 — test_plan §5.4. 부정문 안에 있어도 실패(사용자 노출 문구 정책 위반).
# 투자 조언성 표현·미래 단정·수익 보장·목표가(회피형 포함). 출력 숫자 전면 대조는 하지 않되,
# 조언성 숫자 표현(목표 가격/목표주가)은 금지어로 막는다(§5.4·§5.8).
FORBIDDEN_TERMS: tuple[str, ...] = (
    "매수",
    "매도",
    "손절",
    "목표가",
    "목표 가격",
    "목표주가",
    "진입",
    "추천",
    "예상 수익률",
    "목표 수익률",
    "수익 가능성",
    "수익 보장",
    "보장합니다",
    "보장됩니다",
    "확실합니다",
    "상승할 가능성",
    "하락할 것",
)


# ── template fallback·표시용 한글 라벨(대표 표현 공유). 새 판단이 아니라 확정값의 표시 문구다.
REGIME_LABELS: dict[Regime, str] = {
    Regime.OVERSOLD_REBOUND_WATCH: "과매도 반등 관찰",
    Regime.OVERHEATED: "과열",
    Regime.BULLISH_REVERSAL_WATCH: "상승 전환 관찰",
    Regime.UPTREND_INTACT: "상승 추세 유지",
    Regime.DOWNTREND: "하락 추세",
    Regime.SIDEWAYS: "횡보",
    Regime.UNAVAILABLE: "판단 불가",
}

CONSENSUS_LABELS: dict[Consensus, str] = {
    Consensus.STRONG_POSITIVE: "긍정 우세",
    Consensus.WEAK_POSITIVE: "약한 긍정",
    Consensus.NEUTRAL: "중립",
    Consensus.WEAK_NEGATIVE: "약한 부정",
    Consensus.STRONG_NEGATIVE: "부정 우세",
}

CONFIDENCE_LABELS: dict[ConfidenceLevel, str] = {
    ConfidenceLevel.HIGH: "높음",
    ConfidenceLevel.MEDIUM: "보통",
    ConfidenceLevel.LOW: "낮음",
}

SIGNAL_LABELS: dict[Signal, str] = {
    Signal.POSITIVE: "긍정",
    Signal.NEUTRAL: "중립",
    Signal.NEGATIVE: "부정",
}

INDICATOR_LABELS: dict[IndicatorType, str] = {
    IndicatorType.MOVING_AVERAGE: "이동평균",
    IndicatorType.RSI: "RSI",
    IndicatorType.VOLUME: "거래량",
    IndicatorType.SUPPORT_RESISTANCE: "지지·저항",
    IndicatorType.PATTERN: "캔들 패턴",
}

RISK_LABELS: dict[RiskFlag, str] = {
    RiskFlag.VOLUME_NOT_CONFIRMED: "거래량 확인 약함",
    RiskFlag.NEAR_RESISTANCE: "저항 구간 근접",
    RiskFlag.NEAR_SUPPORT: "지지 구간 근접",
    RiskFlag.MIXED_SIGNALS: "신호 엇갈림",
    RiskFlag.OVERHEATED_MOMENTUM: "단기 과열 관찰",
    RiskFlag.COUNTER_HIGHER_TREND: "상위 추세와 역행",
    RiskFlag.LOW_LIQUIDITY: "유동성 낮음",
}
