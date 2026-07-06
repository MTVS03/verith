"""노드 5 — 국면분류. daily/weekly/monthly OHLCV → MultiframeRegimeResult.

얇은 어댑터: `regime/rules.classify_daily_regime` → `regime/multiframe.analyze_multiframe`만
호출한다. regime 규칙·멀티프레임 보정을 노드 안에 다시 쓰지 않는다.

로컬 dataclass(MultiframeRegimeResult)를 그대로 반환한다 — contracts.RegimeResult 조립은
supervisor 몫(regime/multiframe.py 주석).
"""

from __future__ import annotations

from collections.abc import Sequence

from ..regime.multiframe import MultiframeRegimeResult, analyze_multiframe
from ..regime.rules import classify_daily_regime
from ..schemas.ohlcv import OHLCV


def run_regime_classify(
    daily: Sequence[OHLCV],
    weekly: Sequence[OHLCV],
    monthly: Sequence[OHLCV],
) -> MultiframeRegimeResult:
    """일봉 국면 판정 후 주/월봉 추세로 보정한 멀티프레임 결과를 반환한다.

    weekly/monthly가 부족하면 각 모듈이 trend=unavailable로 처리한다(정상 정책). daily는 필수.
    """
    if not daily:
        raise ValueError("daily OHLCV is required for regime_classify")
    daily_regime = classify_daily_regime(daily)
    return analyze_multiframe(daily_regime, weekly, monthly)
