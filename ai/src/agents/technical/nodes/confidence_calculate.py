"""노드 7 — 신뢰도계산. SignalScoreResult + IndicatorBundle + MultiframeRegimeResult → ConfidenceResult.

얇은 어댑터: `synthesis/confidence.compute_confidence`만 호출한다. confidence 4요소 계산식은
모듈에 있으며 노드가 재구현하지 않는다. 필요한 스칼라(volume_ratio)와 국면(final_regime·
alignment_flag)만 각 입력에서 뽑아 넘긴다. 로컬 dataclass(ConfidenceResult)를 그대로 반환한다.
"""

from __future__ import annotations

from ..regime.multiframe import MultiframeRegimeResult
from ..synthesis.confidence import ConfidenceResult, compute_confidence
from ..synthesis.signal_score import SignalScoreResult
from .indicator_calculate import IndicatorBundle


def run_confidence_calculate(
    signal_result: SignalScoreResult,
    bundle: IndicatorBundle,
    regime_result: MultiframeRegimeResult,
) -> ConfidenceResult:
    """신호 종합·거래량 확인·추세 정합·신호 충돌로 confidence를 계산한다."""
    if signal_result is None or bundle is None or regime_result is None:
        raise ValueError("signal_result, bundle, regime_result are required for confidence_calculate")
    return compute_confidence(
        signal_result,
        volume_ratio=bundle.volume_ratio,
        final_regime=regime_result.final_regime,
        alignment_flag=regime_result.alignment_flag,
    )
