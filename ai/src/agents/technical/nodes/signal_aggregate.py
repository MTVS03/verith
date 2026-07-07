"""노드 6 — 신호종합. daily OHLCV → SignalScoreResult.

얇은 어댑터: `synthesis/signal_score.compute_signal_score`만 호출한다. 가중치·임계값·집계식은
config/모듈에 있으며 노드가 중복 정의하지 않는다. 로컬 dataclass를 그대로 반환한다.

compute_signal_score는 빈 입력이면 (neutral, 0.0)을 조용히 낸다. 노드 어댑터는 그 앞에서
빈 daily를 명시적 예외로 막는다(조용한 빈 결과 금지, technical_coding_guidelines §8.3).
"""

from __future__ import annotations

from collections.abc import Sequence

from ..schemas.ohlcv import OHLCV
from ..synthesis.signal_score import SignalScoreResult, compute_signal_score


def run_signal_aggregate(daily: Sequence[OHLCV]) -> SignalScoreResult:
    """일봉 지표별 신호를 가중 집계해 signal_score·consensus를 반환한다. 빈 입력은 예외."""
    if not daily:
        raise ValueError("daily OHLCV is required for signal_aggregate")
    return compute_signal_score(daily)
