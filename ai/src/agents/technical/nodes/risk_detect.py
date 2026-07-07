"""노드 8 — 리스크관찰점. SignalScoreResult + IndicatorBundle + MultiframeRegimeResult → list[RiskItem].

얇은 어댑터: `synthesis/risk.detect_risks`만 호출한다. risk flag 조건·note 템플릿·ref_price 정책은
모듈에 있으며 노드가 임의로 flag/note를 만들지 않는다. 필요한 스칼라를 각 입력에서 뽑아 넘긴다.

detect_risks가 이미 contracts.RiskItem 리스트를 반환하므로(모듈 계약), 노드는 그것을 그대로
반환한다 — 노드가 새 계약을 조립하는 것이 아니라 모듈 산출물을 통과시킨다.
"""

from __future__ import annotations

from ..regime.multiframe import MultiframeRegimeResult
from ..schemas.contracts import RiskItem
from ..synthesis.risk import detect_risks
from ..synthesis.signal_score import SignalScoreResult
from .indicator_calculate import IndicatorBundle


def run_risk_detect(
    signal_result: SignalScoreResult,
    bundle: IndicatorBundle,
    regime_result: MultiframeRegimeResult,
) -> list[RiskItem]:
    """조건을 만족하는 기술적 위험 관찰점을 고정 순서로 반환한다."""
    if signal_result is None or bundle is None or regime_result is None:
        raise ValueError("signal_result, bundle, regime_result are required for risk_detect")
    return detect_risks(
        signal_result,
        close=bundle.close,
        support=bundle.support,
        resistance=bundle.resistance,
        rsi=bundle.rsi,
        final_regime=regime_result.final_regime,
        alignment_flag=regime_result.alignment_flag,
        volume_ratio=bundle.volume_ratio,
        avg_volume=bundle.avg_volume,
        avg_trading_value=bundle.avg_trading_value,
    )
