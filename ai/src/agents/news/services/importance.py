# services/importance.py
"""중요도(importance) 계산 서비스 — 순수·결정적(TASK 06).

공식은 pipeline_spec §9 / erd.dbml 그대로:
    importance = W_VOLUME·f(기사 개수) + W_PUBLISHER·g(언론사 가중치) + W_SENTIMENT·h(감성 절대값)
세 신호(노출량·출처·사건 강도)를 config 가중치로 결합한 '관측 신호의 결정적 함수'다. 같은 입력이면
항상 같은 출력 — 난수·시간·LLM 없음(CLAUDE.md §2-4/§2-5, pipeline_spec §9).

⚠️ 계산 경계(절대규칙 1): 이 서비스는 LLM(services/llm.py)·감성 모델(services/finbert.py)을
   호출하지 않고, DB/backend 도 직접 부르지 않는다. 기존(저장된) 이벤트 통계가 필요하면 주입된
   EventArticleStatsProvider 로만 얻는다(실제 구현은 TASK 08). 저장·state 갱신은 노드가 한다.
⚠️ 감성은 '세기'만 쓰고 '방향'은 버린다 — importance 는 좋다/나쁘다가 아니라 중요하다/아니다를
   잰다. 강한 긍정·강한 부정 모두 중요도↑, 중립↓. (감성 판정 자체는 TASK 04, 여기선 소비만.)
"""
from __future__ import annotations

import logging
import math
import re
from typing import Callable, Protocol

from config import (
    IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT,
    IMPORTANCE_PUBLISHER_WEIGHTS,
    IMPORTANCE_VOLUME_MODE,
    IMPORTANCE_W_PUBLISHER,
    IMPORTANCE_W_SENTIMENT,
    IMPORTANCE_W_VOLUME,
)
from schemas.article import Article, Sentiment
from schemas.event import EventArticleStats

logger = logging.getLogger(__name__)

# 기사 수 변환 함수 테이블. bool 토글이 아니라 모드 문자열로 갈아끼운다(config IMPORTANCE_VOLUME_MODE).
# log1p·sqrt·linear 모두 count=0 에서 0 을 돌려준다(감성 0건과 마찬가지로 없으면 0, 환각 금지).
_VOLUME_TRANSFORMS: dict[str, Callable[[float], float]] = {
    "log1p": math.log1p,   # 근접 중복 홍수가 순위를 독점하지 못하게 체감(diminishing) 반영(기본)
    "sqrt": math.sqrt,
    "linear": float,
}
_DEFAULT_VOLUME_MODE = "log1p"

_WS_RE = re.compile(r"\s+")


class EventArticleStatsProvider(Protocol):
    """기존(저장된) 이벤트의 누적 기사 통계 조회 계약. 실제 구현은 TASK 08(backend 클라이언트)."""

    def get_event_article_stats(self, event_id: str) -> EventArticleStats | None:
        """이미 저장된 그 이벤트의 누적 기사 통계 반환(이번 배치 기사는 미저장 → 중복 없음).
        미주입 기본 구현은 None 을 반환(backend 미연결에서도 파이프라인이 안 죽고, 배치 기사만으로
        계산 — 신규 이벤트는 정확, 편입 이벤트는 근사)."""
        ...


class DefaultEventArticleStatsProvider:
    """미주입 시 기본 provider. backend 없이도 계산이 돌게 항상 None 을 반환한다.

    → 기존 통계가 없으니 이번 배치 기사만으로 importance 를 계산한다. 신규 이벤트는 이번 배치가 곧
    전체 집합이라 정확하고, 편입 이벤트는 기존 기사가 빠져 근사가 된다. TASK 08 의 backend 클라이언트가
    이 자리에 실제 조회 provider 를 주입한다.
    """

    def get_event_article_stats(self, event_id: str) -> EventArticleStats | None:
        return None


def _normalize_publisher(publisher: str | None) -> str | None:
    """언론사명 최소 정규화(공백만). 앞뒤/중복 공백 정리, 빈 문자열/None → None.

    ⚠️ 최소한만 정규화한다 — 대소문자·별칭·표기 canonical 은 하지 않는다(테이블 키가 RSS_CANDIDATES
    표기와 정합한다는 전제, config IMPORTANCE_PUBLISHER_WEIGHTS 주석). None 은 '미상 출처'로 distinct
    집합에서 하나의 원소가 되어 기본 가중치 한 번을 기여한다.
    """
    if not publisher:
        return None
    text = _WS_RE.sub(" ", publisher).strip()
    return text or None


def _volume_transform(count: int) -> float:
    """총 기사 수를 IMPORTANCE_VOLUME_MODE 에 따라 변환. 미지원 모드는 로깅 후 log1p 로 폴백."""
    fn = _VOLUME_TRANSFORMS.get(IMPORTANCE_VOLUME_MODE)
    if fn is None:
        logger.warning(
            "미지원 IMPORTANCE_VOLUME_MODE=%r → %s 로 폴백",
            IMPORTANCE_VOLUME_MODE, _DEFAULT_VOLUME_MODE,
        )
        fn = _VOLUME_TRANSFORMS[_DEFAULT_VOLUME_MODE]
    return float(fn(count))


def publisher_weight(publisher: str | None) -> float:
    """IMPORTANCE_PUBLISHER_WEIGHTS 조회. 없거나 None 이면 IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT.

    가중치 테이블 적용은 오직 이 함수에서만 한다(backend·다른 곳에 중복 두지 않음, TASK 06 §3.2).
    ⚠️ 테이블 값은 미확정(임시) — 실데이터로 확정(CLAUDE.md §8).
    """
    key = _normalize_publisher(publisher)
    if key is None:
        return IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT
    return IMPORTANCE_PUBLISHER_WEIGHTS.get(key, IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT)


def sentiment_magnitude(article: Article) -> float | None:
    """기사 1건의 감성 절대값(사건 강도). 방향(부호)은 쓰지 않고 세기만 쓴다.

    - 긍정/부정 → sentiment_score(0~1, KR-FinBert 분류 confidence, TASK 04). 그래서 긍정 0.99 와
      부정 0.99 는 importance 기여가 같다(방향은 버리고 세기만 — 의도된 동작).
    - 중립 → 0.0(중립은 강도 없음, 단 집계 분모에는 포함).
    - None(감성 없음, 본문 없는 속보 등) → None 을 반환해 집계에서 제외(강제 중립 금지, TASK 04 §4.1).

    방어: 긍/부인데 sentiment_score 가 None(데이터 불일치)이면 강도 0.0 으로 본다(집계엔 포함).
    """
    if article.sentiment is None:
        return None
    if article.sentiment is Sentiment.NEUTRAL:
        return 0.0
    # 긍정/부정: 방향 버리고 세기(confidence)만.
    score = article.sentiment_score
    return float(score) if score is not None else 0.0


def compute_importance(
    articles: list[Article], existing: EventArticleStats | None = None,
) -> float:
    """한 이벤트의 importance. (existing + 이번 배치 기사)를 합산해 전체 재계산한다.

    이번 배치 기사는 아직 미저장(신규)이라 existing 과 중복되지 않는다(§3.2). 신규 이벤트는 existing
    이 None 이라 배치 기사만으로 정확하고, 편입 이벤트는 provider 가 준 기존 통계와 합산해 전체를 낸다.

    - volume: len(articles) + existing.article_count 를 IMPORTANCE_VOLUME_MODE 로 변환.
    - publisher: (배치 언론사 ∪ existing.publishers) distinct 에 publisher_weight '합(sum)'(평균 아님).
      distinct → 같은 매체 중복이 언론사 항을 부풀리지 않게(그 중복은 volume 이 반영). sum → 매체가
      늘수록 항이 단조 증가(여러/권위 매체가 함께 다룰수록 도달·신뢰↑, §3.2).
    - sentiment: None 아닌 기사들의 sentiment_magnitude 평균 = (배치 합 + existing.sum)/(배치 수 +
      existing.count). 감성 있는 기사가 0건이면 감성 항 0(환각 금지, §2-5).
    - LLM·DB 호출 없음(결정적). 값·가중치·테이블은 전부 config 에서 읽는다.
    """
    existing_count = existing.article_count if existing else 0
    total_volume = len(articles) + existing_count
    volume_score = _volume_transform(total_volume)

    # 언론사: 배치 ∪ existing 의 distinct(정규화 키) 집합. None(미상)도 하나의 원소로 기본 가중치 기여.
    publisher_keys: set[str | None] = {_normalize_publisher(a.publisher) for a in articles}
    if existing:
        publisher_keys.update(_normalize_publisher(p) for p in existing.publishers)
    publisher_score = sum(publisher_weight(key) for key in publisher_keys)

    # 감성: None 아닌 강도의 합·개수를 existing 과 합산해 평균. 0건이면 0.
    batch_sum = 0.0
    batch_count = 0
    for article in articles:
        mag = sentiment_magnitude(article)
        if mag is None:
            continue  # 감성 없음 → 분모에서 제외(강제 중립 금지)
        batch_sum += mag
        batch_count += 1
    total_sentiment_sum = batch_sum + (existing.sentiment_magnitude_sum if existing else 0.0)
    total_sentiment_count = batch_count + (existing.sentiment_count if existing else 0)
    sentiment_score = (
        total_sentiment_sum / total_sentiment_count if total_sentiment_count > 0 else 0.0
    )

    return (
        IMPORTANCE_W_VOLUME * volume_score
        + IMPORTANCE_W_PUBLISHER * publisher_score
        + IMPORTANCE_W_SENTIMENT * sentiment_score
    )
