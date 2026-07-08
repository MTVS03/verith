"""importance 재계산(backend 복제 공식) 단위 테스트.

ai `services/importance.py` 와 동일한 결과여야 한다(SCHEMA_SPEC §5 단일 정의). 순수 계산이라
mock 불필요. 공식이 갈라지면(경우 B) 정렬이 깨지므로 수치까지 고정 검증한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.api.services.importance import (
    compute_importance,
    publisher_weight,
    sentiment_magnitude,
)


@dataclass
class Art:
    publisher: str | None = None
    sentiment: str | None = None
    sentiment_score: float | None = None


def test_publisher_weight_table_and_default():
    assert publisher_weight("한국경제") == 1.0      # 등록 매체
    assert publisher_weight("세계일보") == 0.8
    assert publisher_weight("듣보잡뉴스") == 0.5     # 미등록 → 기본값
    assert publisher_weight(None) == 0.5             # None → 기본값
    assert publisher_weight("  한국경제 ") == 1.0    # 공백 정규화


def test_sentiment_magnitude_direction_dropped():
    assert sentiment_magnitude(Art(sentiment="긍정", sentiment_score=0.9)) == 0.9
    assert sentiment_magnitude(Art(sentiment="부정", sentiment_score=0.9)) == 0.9  # 방향 무관
    assert sentiment_magnitude(Art(sentiment="중립")) == 0.0
    assert sentiment_magnitude(Art(sentiment=None)) is None                        # 집계 제외


def test_compute_importance_formula():
    arts = [
        Art("한국경제", "긍정", 0.8),
        Art("매일경제", "부정", 0.6),
    ]
    # volume=log1p(2), publisher=1.0+1.0=2.0(distinct sum), sentiment=(0.8+0.6)/2=0.7
    expected = 0.5 * math.log1p(2) + 0.3 * 2.0 + 0.2 * 0.7
    assert compute_importance(arts) == expected


def test_compute_importance_distinct_publisher_and_none_sentiment():
    # 같은 매체 2건 → publisher 항은 1.0 (distinct), 감성 None 은 분모에서 제외
    arts = [Art("한국경제", None), Art("한국경제", "긍정", 0.5)]
    # volume=log1p(2), publisher=1.0, sentiment=0.5(감성 1건만)
    expected = 0.5 * math.log1p(2) + 0.3 * 1.0 + 0.2 * 0.5
    assert compute_importance(arts) == expected


def test_compute_importance_empty_and_deterministic():
    assert compute_importance([]) == 0.0
    arts = [Art("한겨레", "중립"), Art("조선일보", "긍정", 0.7)]
    assert compute_importance(arts) == compute_importance(arts)  # 결정적
