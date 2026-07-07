"""테스트용 AI(technical) output 픽스처 — TechnicalAgentOutput 형태의 dict.

실제 AI 계약(ai/src/agents/technical/schemas/contracts.py)의 필드/enum 값과 정합.
NORMAL_OUTPUT 은 계약을 지키는 정상 응답(중복 indicator 없음)이며, 계약 위반 케이스는
DUP_/MISMATCH_/MALFORMED_ 로 별도 제공한다.
"""

from __future__ import annotations

import copy

TICKER = "373220"

# 저장 시 backend 가 생성한 request_id 로 교체된다(테스트 헬퍼가 주입).
_PLACEHOLDER_REQUEST_ID = "__REQUEST_ID__"

NORMAL_OUTPUT: dict = {
    "request_id": _PLACEHOLDER_REQUEST_ID,
    "ticker": TICKER,
    "as_of": "2026-07-06T00:00:00+09:00",
    "source": "KIS",
    "trace_id": "trace-abc",
    "data_status": "normal",
    "regime": {
        "daily_regime": "uptrend_intact",
        "final_regime": "uptrend_intact",
        "weekly_trend": "up",
        "monthly_trend": "up",
        "alignment_flag": "aligned",
        "regime_context": "상위 추세와 정렬",
    },
    "signal": {
        "consensus": "strong_positive",
        "signal_score": 0.62,
        "confidence": 0.71,
        "confidence_level": "high",
        "confidence_basis": "지표 정합",
    },
    "technical_signals": [
        {
            "indicator": "moving_average",
            "signal": "positive",
            "value": 82900.0,
            "metrics": ["5MA 82,900"],
            "detail": "정배열",
            "detail_source": "llm",
            "weight": 0.3,
        },
        {
            "indicator": "rsi",
            "signal": "positive",
            "value": 61.2,
            "metrics": ["RSI 61.2"],
            "detail": "중립~강세",
            "detail_source": "llm",
            "weight": 0.25,
        },
        {
            "indicator": "volume",
            "signal": "neutral",
            "value": None,
            "metrics": [],
            "detail": "거래량 미확인",
            "detail_source": "template_fallback",
            "weight": 0.2,
        },
    ],
    "risk": {"items": [{"flag": "near_resistance", "note": "저항 부근", "ref_price": 90000.0}]},
    "charts": [{"period": "3m", "chart_data": {"candle_unit": "D", "candles": [], "overlays": []}}],
    "interpretation": {"text": "전반적으로 강세 흐름입니다.", "source": "llm"},
    "verification": {
        "calc_passed": True,
        "regime_passed": True,
        "label_matched": True,
        "outcome": "passed",
        "regen_count": 0,
    },
    "intraday_context": None,
}

INDICATORS = ["moving_average", "rsi", "volume"]  # NORMAL_OUTPUT 기준 3개(중복 없음)


def _clone(**overrides) -> dict:
    d = copy.deepcopy(NORMAL_OUTPUT)
    d.update(overrides)
    return d


# 계약 위반 1: 중복 indicator(rsi 2개) → 502
DUP_OUTPUT: dict = copy.deepcopy(NORMAL_OUTPUT)
DUP_OUTPUT["technical_signals"].append(
    {
        "indicator": "rsi",
        "signal": "neutral",
        "value": 58.0,
        "metrics": ["RSI 58.0 (weekly)"],
        "detail": "주봉 기준",
        "detail_source": "llm",
        "weight": 0.25,
    }
)

# 계약 위반 2: 요청과 다른 ticker → 502
MISMATCH_TICKER_OUTPUT: dict = _clone(ticker="005930")

# 계약 위반 3: 구조 누락(regime 없음) → 502
MALFORMED_OUTPUT: dict = copy.deepcopy(NORMAL_OUTPUT)
del MALFORMED_OUTPUT["regime"]
