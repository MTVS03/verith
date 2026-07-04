"""confidence(신뢰도) 계산 — signal_score와 다른 축.

정본: `config.md §5.1`. 4요소(agreement·volume_confirm·trend_clarity·conflict_absence)를
0~1로 계산해 가중합한다. 모든 요소는 "높을수록 confidence↑" 방향. LLM은 confidence를 만들지 않는다.
`confidence_level`은 표시용 파생값이며 DB 저장 대상이 아니다(저장은 confidence 숫자).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_WEIGHTS,
)
from ..schemas.enums import AlignmentFlag, ConfidenceLevel, Regime, Signal
from .signal_score import SignalScoreResult, _SIGNAL_ENCODING

_DIRECTIONAL_REGIMES = frozenset(
    {Regime.BULLISH_REVERSAL_WATCH, Regime.UPTREND_INTACT, Regime.DOWNTREND}
)
_CONFIDENCE_LABEL = {ConfidenceLevel.HIGH: "높음", ConfidenceLevel.MEDIUM: "보통", ConfidenceLevel.LOW: "낮음"}


@dataclass(frozen=True)
class ConfidenceResult:
    confidence: float
    confidence_level: ConfidenceLevel
    confidence_basis: str
    agreement: float
    volume_confirm: float
    trend_clarity: float
    conflict_absence: float


def _clamp(x: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, x))


def compute_agreement(signal_result: SignalScoreResult) -> float:
    """|Σ w·s| / Σ w·|s|. 전부 neutral(분모 0)이면 0.0."""
    numerator = abs(sum(r.weight * _SIGNAL_ENCODING[r.signal] for r in signal_result.technical_signals))
    denominator = sum(r.weight * abs(_SIGNAL_ENCODING[r.signal]) for r in signal_result.technical_signals)
    return numerator / denominator if denominator > 0 else 0.0


def compute_volume_confirm(volume_ratio: float | None) -> float:
    """거래량 확인 = clamp(volume_ratio, 0, 1). 계산 불가면 0.0."""
    if volume_ratio is None:
        return 0.0
    return _clamp(volume_ratio)


def compute_trend_clarity(final_regime: Regime, alignment_flag: AlignmentFlag) -> float:
    """국면·상위 추세 정합성 (config.md §5.1)."""
    if final_regime in (Regime.SIDEWAYS, Regime.UNAVAILABLE):
        return 0.0
    if alignment_flag == AlignmentFlag.ALIGNED:
        return 1.0
    if alignment_flag == AlignmentFlag.COUNTER_TREND:
        return 0.3
    if alignment_flag == AlignmentFlag.NEUTRAL and final_regime in _DIRECTIONAL_REGIMES:
        return 0.6
    return 0.0


def compute_conflict_absence(signal_result: SignalScoreResult) -> float:
    """1 − 2·min(pos_weight, neg_weight), clamp[0,1]. 한 방향만/전부 neutral이면 1.0."""
    pos_weight = sum(r.weight for r in signal_result.technical_signals if r.signal == Signal.POSITIVE)
    neg_weight = sum(r.weight for r in signal_result.technical_signals if r.signal == Signal.NEGATIVE)
    return _clamp(1.0 - 2.0 * min(pos_weight, neg_weight))


def _confidence_basis(signal_result: SignalScoreResult, level: ConfidenceLevel) -> str:
    pos = sum(1 for r in signal_result.technical_signals if r.signal == Signal.POSITIVE)
    neu = sum(1 for r in signal_result.technical_signals if r.signal == Signal.NEUTRAL)
    neg = sum(1 for r in signal_result.technical_signals if r.signal == Signal.NEGATIVE)
    total = pos + neu + neg
    return f"지표 {total}개 중 긍정 {pos}·중립 {neu}·부정 {neg}로 신뢰도는 {_CONFIDENCE_LABEL[level]}입니다."


def classify_confidence_level(confidence: float) -> ConfidenceLevel:
    if confidence >= CONFIDENCE_HIGH:
        return ConfidenceLevel.HIGH
    if confidence >= CONFIDENCE_MEDIUM:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def compute_confidence(
    signal_result: SignalScoreResult,
    *,
    volume_ratio: float | None,
    final_regime: Regime,
    alignment_flag: AlignmentFlag,
) -> ConfidenceResult:
    """4요소 가중합 → confidence(0~1) + 표시용 confidence_level + 근거 문장."""
    agreement = compute_agreement(signal_result)
    volume_confirm = compute_volume_confirm(volume_ratio)
    trend_clarity = compute_trend_clarity(final_regime, alignment_flag)
    conflict_absence = compute_conflict_absence(signal_result)

    confidence = _clamp(
        agreement * CONFIDENCE_WEIGHTS["agreement"]
        + volume_confirm * CONFIDENCE_WEIGHTS["volume_confirm"]
        + trend_clarity * CONFIDENCE_WEIGHTS["trend_clarity"]
        + conflict_absence * CONFIDENCE_WEIGHTS["conflict_absence"]
    )
    level = classify_confidence_level(confidence)
    return ConfidenceResult(
        confidence=confidence,
        confidence_level=level,
        confidence_basis=_confidence_basis(signal_result, level),
        agreement=agreement,
        volume_confirm=volume_confirm,
        trend_clarity=trend_clarity,
        conflict_absence=conflict_absence,
    )
