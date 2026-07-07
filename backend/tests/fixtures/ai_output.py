"""테스트용 AI(technical) output 픽스처 — TechnicalAgentOutput 형태의 dict.

실제 AI 계약(ai/src/agents/technical/schemas/contracts.py)의 필드/enum 값과 정합.
NORMAL_OUTPUT 은 정상 리포트이며, technical_signals 에 **중복 indicator(rsi)** 를 포함해
UNIQUE(report_id, indicator) 처리(dedup)를 검증할 수 있게 한다.
"""

from __future__ import annotations

TICKER = "373220"

NORMAL_OUTPUT: dict = {
    "request_id": "ai-req-xyz",  # 저장 시엔 backend 생성 request_id 를 쓴다(이 값은 무시)
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
            # 중복 indicator(rsi) — dedup 대상. 대표 1개만 저장돼야 한다.
            "indicator": "rsi",
            "signal": "neutral",
            "value": 58.0,
            "metrics": ["RSI 58.0 (weekly)"],
            "detail": "주봉 기준",
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
    "risk": {
        "items": [
            {"flag": "near_resistance", "note": "저항 부근", "ref_price": 90000.0},
        ]
    },
    "charts": [
        {
            "period": "3m",
            "chart_data": {"candle_unit": "D", "candles": [], "overlays": []},
        },
    ],
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

# 이 output 기준 기대값
UNIQUE_INDICATORS = {"moving_average", "rsi", "volume"}  # dedup 후 3개
