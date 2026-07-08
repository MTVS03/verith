"""importance(중요도) 재계산 — ai `services/importance.py` 공식의 backend 복제.

⚠️ backend 는 원칙적으로 분석값을 계산하지 않으나(가이드 §3.1), cleanup(7일 롤링) 이후 살아남은
이벤트의 importance 재계산은 backend 소유의 **예외**다(SCHEMA_SPEC §5, TASK 06 §4.2). 공식·가중치는
ai 와 동일해야 하며 상수는 constants/importance.py(= ai config 값)에서만 읽는다(하드코딩 금지).

공식: importance = W_VOLUME·f(기사수) + W_PUBLISHER·g(언론사 가중치 합) + W_SENTIMENT·h(감성 강도 평균)
- volume: log1p(총 기사수) 등(모드)
- publisher: distinct 언론사들의 가중치 '합(sum)'(평균 아님)
- sentiment: 감성 있는(None 아님) 기사들의 강도(긍/부=score, 중립=0) '평균'. 방향은 버리고 세기만.

cleanup 재계산은 이벤트의 **현재 남은 전체 기사**를 입력으로 받으므로 ai 의 existing(누적 통계)
합산 경로는 필요 없다(전체 집합을 그대로 계산).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Callable, Protocol

from src.api.constants.importance import (
    IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT,
    IMPORTANCE_PUBLISHER_WEIGHTS,
    IMPORTANCE_VOLUME_MODE,
    IMPORTANCE_W_PUBLISHER,
    IMPORTANCE_W_SENTIMENT,
    IMPORTANCE_W_VOLUME,
)

_VOLUME_TRANSFORMS: dict[str, Callable[[float], float]] = {
    "log1p": math.log1p,
    "sqrt": math.sqrt,
    "linear": float,
}
_DEFAULT_VOLUME_MODE = "log1p"
_WS_RE = re.compile(r"\s+")


class _ArticleLike(Protocol):
    """importance 계산에 필요한 기사 필드(PG row 등 duck-typing)."""

    publisher: str | None
    sentiment: str | None
    sentiment_score: float | None


def _normalize_publisher(publisher: str | None) -> str | None:
    if not publisher:
        return None
    text = _WS_RE.sub(" ", publisher).strip()
    return text or None


def _volume_transform(count: int) -> float:
    fn = _VOLUME_TRANSFORMS.get(IMPORTANCE_VOLUME_MODE, _VOLUME_TRANSFORMS[_DEFAULT_VOLUME_MODE])
    return float(fn(count))


def publisher_weight(publisher: str | None) -> float:
    """언론사 가중치 조회. 미등록/None 이면 기본값(ai 와 동일 규칙)."""
    key = _normalize_publisher(publisher)
    if key is None:
        return IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT
    return IMPORTANCE_PUBLISHER_WEIGHTS.get(key, IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT)


def sentiment_magnitude(article: _ArticleLike) -> float | None:
    """기사 1건의 감성 절대값(사건 강도). 긍/부=score, 중립=0.0, None=집계 제외(None 반환)."""
    if article.sentiment is None:
        return None
    if article.sentiment == "중립":
        return 0.0
    score = article.sentiment_score
    return float(score) if score is not None else 0.0


def compute_importance(articles: Iterable[_ArticleLike]) -> float:
    """이벤트의 현재 전체 기사로 importance 재계산(ai 공식). 기사 0건이면 0.0."""
    items = list(articles)
    if not items:
        return 0.0

    volume_score = _volume_transform(len(items))

    publisher_keys: set[str | None] = {_normalize_publisher(a.publisher) for a in items}
    publisher_score = sum(publisher_weight(key) for key in publisher_keys)

    mag_sum = 0.0
    mag_count = 0
    for a in items:
        mag = sentiment_magnitude(a)
        if mag is None:
            continue
        mag_sum += mag
        mag_count += 1
    sentiment_score = mag_sum / mag_count if mag_count > 0 else 0.0

    return (
        IMPORTANCE_W_VOLUME * volume_score
        + IMPORTANCE_W_PUBLISHER * publisher_score
        + IMPORTANCE_W_SENTIMENT * sentiment_score
    )
