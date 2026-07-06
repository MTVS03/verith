"""intraday 기반 confidence 보정·risk note 계산 helper — 순수 계산(Beta).

이미 hint/alignment가 채워진 `IntradayContext`를 읽어 **context 내부의** `confidence_adjustment`·
`risk_notes`만 채운다. **output의 top-level confidence/signal_score/risk 구조는 바꾸지 않는다**
(그 반영은 이후 별도 결정). KIS 호출 없음. final_regime과 무관하다.

정책:
  - confidence_adjustment: aligned=+cap, counter=-cap, 그 외 0.0. volatile은 양수 금지. cap ±0.05.
  - signal_score_adjustment: v1은 계속 0.0(미조정).
  - risk_notes: 기존 RiskFlag(enums)를 확장하지 않고 중립 표현의 문자열로만. 최대 3개.
    투자 권유·주문 지시 표현을 쓰지 않고, 투자판단으로 오해될 표현 대신 "변동성 확대/흐름 충돌" 사용.
"""

from __future__ import annotations

from ..schemas.intraday import IntradayContext

# 보정 상한(정식 config화는 후속). aligned/counter일 때만 ±이 값.
INTRADAY_CONFIDENCE_ADJUSTMENT_CAP = 0.05
# risk_notes 최대 개수(차트 과밀·과잉 경고 방지).
INTRADAY_MAX_RISK_NOTES = 3


def compute_intraday_confidence_adjustment(context: IntradayContext) -> float:
    """regime_alignment 기반 confidence 보정값. 반드시 [-cap, +cap] 이내. 미보정은 0.0.

    - status≠normal → 0.0
    - aligned → +cap, counter → -cap, neutral/unavailable/None → 0.0
    - volatile_intraday → 양수(신뢰도 상향) 금지
    """
    if context.status != "normal":
        return 0.0
    cap = INTRADAY_CONFIDENCE_ADJUSTMENT_CAP
    alignment = context.regime_alignment
    if alignment == "aligned":
        adjustment = cap
    elif alignment == "counter":
        adjustment = -cap
    else:  # neutral / unavailable / None
        adjustment = 0.0
    if context.intraday_regime_hint == "volatile_intraday":
        adjustment = min(adjustment, 0.0)  # 변동성 확대 국면에서는 신뢰도 상향 금지
    return max(-cap, min(cap, adjustment))  # 방어적 하드 cap


def build_intraday_risk_notes(context: IntradayContext) -> list[str]:
    """중립 표현의 intraday 관찰 note(최대 INTRADAY_MAX_RISK_NOTES). status≠normal이면 빈 리스트."""
    if context.status != "normal":
        return []
    notes: list[str] = []
    if context.regime_alignment == "counter":
        notes.append("단기 흐름이 상위 추세와 충돌합니다.")
    if context.intraday_regime_hint == "volatile_intraday":
        notes.append("장중 변동성이 확대되었습니다.")
    if context.volume_spike:
        notes.append("장중 거래량이 평균 대비 확대되었습니다.")
    if context.day_range_position is not None:
        if context.day_range_position >= 0.9:
            notes.append("현재가가 당일 고가 부근에 있습니다.")
        elif context.day_range_position <= 0.1:
            notes.append("현재가가 당일 저가 부근에 있습니다.")
    return notes[:INTRADAY_MAX_RISK_NOTES]


def apply_intraday_adjustments(context: IntradayContext) -> IntradayContext:
    """confidence_adjustment·signal_score_adjustment(0.0)·risk_notes를 채운 **새 context** 반환.

    hint/alignment 등 다른 관측값은 그대로 두고, top-level output 값도 건드리지 않는다.
    """
    return context.model_copy(
        update={
            "confidence_adjustment": compute_intraday_confidence_adjustment(context),
            "signal_score_adjustment": 0.0,  # v1 미조정
            "risk_notes": build_intraday_risk_notes(context),
        }
    )
