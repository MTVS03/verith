"""importance(중요도) 계산 상수 — ai `news 에이전트`와 **단일 정의 공유**.

⚠️ **동기화 규칙(중요):** 이 값들은 ai `ai/src/agents/news/config.py` 의 `IMPORTANCE_*` 와
**반드시 동일**해야 한다. backend 는 cleanup(7일 롤링) 이후 살아남은 이벤트의 importance 를
재계산하는데(SCHEMA_SPEC §5, TASK 06 §4.2), 그 공식·가중치가 ai 와 갈라지면 같은 이벤트가
"마지막에 누가 계산했나"에 따라 점수가 출렁여 정렬이 깨진다. 수식/가중치를 바꾸면 **여기와 ai
양쪽을 함께** 고친다(api_contract 승격 시 'importance 공식 단일 소유'로 고정).

언론사 가중치 테이블은 ai 와 마찬가지로 **미확정 임시값**이다(실데이터로 확정).
"""

from __future__ import annotations

# 세 신호 가중치 (ai config.py 와 동일).
IMPORTANCE_W_VOLUME: float = 0.5
IMPORTANCE_W_PUBLISHER: float = 0.3
IMPORTANCE_W_SENTIMENT: float = 0.2

# 기사 수 변환 모드: "log1p" | "sqrt" | "linear" (기본 log1p, 미지원 값은 log1p 폴백).
IMPORTANCE_VOLUME_MODE: str = "log1p"

# ⚠️ 미확정 임시값 — ai config.py 의 표와 동일하게 유지.
IMPORTANCE_PUBLISHER_WEIGHTS: dict[str, float] = {
    "매일경제": 1.0, "한국경제": 1.0,
    "조선일보": 0.9, "동아일보": 0.9, "경향신문": 0.9, "한겨레": 0.9,
    "세계일보": 0.8,
    "디지털타임스": 0.8, "아시아경제": 0.8, "파이낸셜뉴스": 0.8,
}
IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT: float = 0.5
