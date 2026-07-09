# tests/test_importance.py
"""services/importance.py + nodes/importance.py 테스트(mock/fake 기반, TASK 06).

importance 는 관측 신호(기사 수·언론사·감성 세기)의 '결정적 함수'라 대부분 mock 없이 검증되고,
기존(저장된) 이벤트 통계는 fake EventArticleStatsProvider 로 주입한다(실제 backend·DB 없음, 절대규칙 1).
공식: importance = W_VOLUME·f(기사수) + W_PUBLISHER·g(언론사 distinct 합) + W_SENTIMENT·h(감성 평균 세기).
값·가중치·테이블은 config 에서 읽으므로(튜닝 대상) 기대값도 config 를 참조해 계산한다(하드코딩 안 함).
"""
from __future__ import annotations

import math

import pytest

import src.agents.news.services.importance as importance
from src.agents.news.config import (
    IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT,
    IMPORTANCE_W_PUBLISHER,
    IMPORTANCE_W_SENTIMENT,
    IMPORTANCE_W_VOLUME,
)
from src.agents.news.nodes.importance import importance_node
from src.agents.news.schemas.article import Article, Sentiment
from src.agents.news.schemas.event import Event, EventArticleStats

_URL_SEQ = iter(range(1_000_000))


def _article(
    publisher: str | None = "매일경제",
    sentiment: Sentiment | None = None,
    score: float | None = None,
    event_id: str | None = None,
) -> Article:
    n = next(_URL_SEQ)
    return Article(
        title="제목",
        url=f"https://example.com/{n}",
        publisher=publisher,
        sentiment=sentiment,
        sentiment_score=score,
        event_id=event_id,
    )


class FakeStatsProvider:
    """주입 가능한 통계 조회 시임. event_id → EventArticleStats 매핑을 돌려주고 호출을 기록한다."""

    def __init__(self, stats: dict[str, EventArticleStats | None] | None = None):
        self.stats = stats or {}
        self.calls: list[str] = []

    def get_event_article_stats(self, event_id: str) -> EventArticleStats | None:
        self.calls.append(event_id)
        return self.stats.get(event_id)


# ---------------------------------------------------------------------------
# publisher_weight — 테이블 조회 + 미등록/None 기본값
# ---------------------------------------------------------------------------
def test_publisher_weight_registered_uses_table():
    # 테이블에 등록된 매체는 그 값(임시값이라도 default 와 구분되게 검증).
    assert importance.publisher_weight("매일경제") == pytest.approx(1.0)
    assert importance.publisher_weight("한겨레") == pytest.approx(0.9)


def test_publisher_weight_unregistered_and_none_use_default():
    assert importance.publisher_weight("듣보일보") == IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT
    assert importance.publisher_weight(None) == IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT
    assert importance.publisher_weight("   ") == IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT


def test_publisher_weight_normalizes_whitespace():
    # 최소 정규화(앞뒤/중복 공백)로 테이블 키와 매칭.
    assert importance.publisher_weight("  매일경제 ") == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# sentiment_magnitude — 방향 버리고 세기만, 중립 0, None 제외
# ---------------------------------------------------------------------------
def test_sentiment_magnitude_positive_and_negative_use_score():
    pos = _article(sentiment=Sentiment.POSITIVE, score=0.91)
    neg = _article(sentiment=Sentiment.NEGATIVE, score=0.91)
    assert importance.sentiment_magnitude(pos) == pytest.approx(0.91)
    # 방향 무관: 같은 세기면 긍정=부정.
    assert importance.sentiment_magnitude(neg) == importance.sentiment_magnitude(pos)


def test_sentiment_magnitude_neutral_is_zero():
    art = _article(sentiment=Sentiment.NEUTRAL, score=0.99)
    assert importance.sentiment_magnitude(art) == 0.0


def test_sentiment_magnitude_none_is_excluded():
    art = _article(sentiment=None, score=None)
    assert importance.sentiment_magnitude(art) is None


# ---------------------------------------------------------------------------
# compute_importance — 결정성·공식·합산
# ---------------------------------------------------------------------------
def test_compute_importance_exact_formula_new_event():
    # 신규 이벤트(existing=None): 배치 기사만으로 정확. 기본 모드 log1p.
    articles = [
        _article(publisher="매일경제", sentiment=Sentiment.POSITIVE, score=0.8),  # weight 1.0
        _article(publisher="한국경제", sentiment=Sentiment.POSITIVE, score=0.8),  # weight 1.0
    ]
    expected = (
        IMPORTANCE_W_VOLUME * math.log1p(2)
        + IMPORTANCE_W_PUBLISHER * (1.0 + 1.0)   # distinct 두 매체 합
        + IMPORTANCE_W_SENTIMENT * 0.8           # 평균 세기
    )
    assert importance.compute_importance(articles) == pytest.approx(expected)


def test_compute_importance_is_deterministic():
    articles = [_article(sentiment=Sentiment.NEGATIVE, score=0.7) for _ in range(3)]
    a = importance.compute_importance(articles)
    b = importance.compute_importance(articles)
    assert a == b


def test_compute_importance_volume_monotonic_more_articles_higher():
    # 다른 조건 동일, 기사 수만 증가 → importance 증가(단조).
    few = [_article(publisher="X", sentiment=Sentiment.NEUTRAL) for _ in range(2)]
    many = [_article(publisher="X", sentiment=Sentiment.NEUTRAL) for _ in range(10)]
    assert importance.compute_importance(many) > importance.compute_importance(few)


def test_compute_importance_volume_log1p_diminishes():
    # log1p 는 체감: 기사 1건 추가의 한계 기여가 기사 수가 많을수록 작아진다(근접중복 독점 방지).
    # 같은 +1 증분을 낮은 구간(1→2)과 높은 구간(10→11)에서 비교한다.
    def vol_only(n):
        arts = [_article(publisher="X", sentiment=Sentiment.NEUTRAL) for _ in range(n)]
        return importance.compute_importance(arts)

    gain_low = vol_only(2) - vol_only(1)
    gain_high = vol_only(11) - vol_only(10)
    assert gain_low > gain_high


def test_compute_importance_volume_mode_linear(monkeypatch):
    # 모드 문자열로 변환 함수를 갈아끼운다: linear 는 count 그대로.
    monkeypatch.setattr(importance, "IMPORTANCE_VOLUME_MODE", "linear")
    arts = [_article(publisher=None, sentiment=None) for _ in range(4)]
    # publisher: None distinct 1개 → default. sentiment: 전부 None → 0.
    expected = (
        IMPORTANCE_W_VOLUME * 4.0
        + IMPORTANCE_W_PUBLISHER * IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT
        + IMPORTANCE_W_SENTIMENT * 0.0
    )
    assert importance.compute_importance(arts) == pytest.approx(expected)


def test_compute_importance_volume_mode_sqrt(monkeypatch):
    monkeypatch.setattr(importance, "IMPORTANCE_VOLUME_MODE", "sqrt")
    arts = [_article(publisher=None, sentiment=None) for _ in range(9)]
    expected = (
        IMPORTANCE_W_VOLUME * 3.0   # sqrt(9)
        + IMPORTANCE_W_PUBLISHER * IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT
        + IMPORTANCE_W_SENTIMENT * 0.0
    )
    assert importance.compute_importance(arts) == pytest.approx(expected)


def test_compute_importance_unsupported_mode_falls_back_to_log1p(monkeypatch, caplog):
    monkeypatch.setattr(importance, "IMPORTANCE_VOLUME_MODE", "bogus")
    arts = [_article(publisher=None, sentiment=None) for _ in range(4)]
    got = importance.compute_importance(arts)
    expected = (
        IMPORTANCE_W_VOLUME * math.log1p(4)   # log1p 폴백
        + IMPORTANCE_W_PUBLISHER * IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT
    )
    assert got == pytest.approx(expected)


def test_compute_importance_publisher_distinct_not_inflated_by_duplicates():
    # 같은 매체가 여러 기사를 써도 언론사 항은 안 오른다(distinct). 감성 없음으로 감성 항 고정.
    one = [_article(publisher="조선일보", sentiment=None)]
    three_same = [_article(publisher="조선일보", sentiment=None) for _ in range(3)]

    # 언론사 항만 비교하기 위해 volume 차이를 상쇄: 공식에서 언론사 기여 = 총 - volume - sentiment.
    def publisher_term(arts):
        total = importance.compute_importance(arts)
        vol = IMPORTANCE_W_VOLUME * math.log1p(len(arts))
        return total - vol   # sentiment 항 0

    assert publisher_term(one) == pytest.approx(publisher_term(three_same))


def test_compute_importance_publisher_sum_increases_with_distinct_publishers():
    # 서로 다른 매체가 늘면 언론사 항이 오른다(sum → 단조 증가, 평균 아님).
    def publisher_term(arts):
        total = importance.compute_importance(arts)
        vol = IMPORTANCE_W_VOLUME * math.log1p(len(arts))
        return total - vol

    one_pub = [_article(publisher="조선일보", sentiment=None)]
    two_pub = [
        _article(publisher="조선일보", sentiment=None),
        _article(publisher="동아일보", sentiment=None),
    ]
    assert publisher_term(two_pub) > publisher_term(one_pub)


def test_compute_importance_sentiment_direction_irrelevant():
    # 강한 긍정 일색 vs 강한 부정 일색: 다른 조건 동일하면 감성 기여가 같다(세기만).
    pos = [_article(publisher="X", sentiment=Sentiment.POSITIVE, score=0.95) for _ in range(3)]
    neg = [_article(publisher="X", sentiment=Sentiment.NEGATIVE, score=0.95) for _ in range(3)]
    assert importance.compute_importance(pos) == pytest.approx(importance.compute_importance(neg))


def test_compute_importance_sentiment_none_excluded_from_average():
    # None 은 분모에서 제외: [0.8, None] 의 감성 평균은 0.8 (0.4 아님).
    arts = [
        _article(publisher="X", sentiment=Sentiment.POSITIVE, score=0.8),
        _article(publisher="X", sentiment=None),
    ]
    total = importance.compute_importance(arts)
    vol = IMPORTANCE_W_VOLUME * math.log1p(2)
    pub = IMPORTANCE_W_PUBLISHER * importance.publisher_weight("X")  # distinct 1개
    sentiment_term = total - vol - pub
    assert sentiment_term == pytest.approx(IMPORTANCE_W_SENTIMENT * 0.8)


def test_compute_importance_no_sentiment_articles_zero_sentiment_term():
    arts = [_article(publisher="X", sentiment=None) for _ in range(3)]
    total = importance.compute_importance(arts)
    vol = IMPORTANCE_W_VOLUME * math.log1p(3)
    pub = IMPORTANCE_W_PUBLISHER * importance.publisher_weight("X")
    assert total == pytest.approx(vol + pub)   # 감성 항 0


def test_compute_importance_merges_existing_stats():
    # 편입 이벤트: existing(기존 통계) + 배치 기사 합산으로 전체 재계산.
    existing = EventArticleStats(
        article_count=3,
        publishers=["한국경제"],                 # 배치와 다른 매체 → distinct 합에 추가
        sentiment_magnitude_sum=1.8,             # 기존 감성 강도 합
        sentiment_count=2,                       # 기존 감성 기사 2건
    )
    batch = [_article(publisher="매일경제", sentiment=Sentiment.POSITIVE, score=0.6)]
    got = importance.compute_importance(batch, existing)
    expected = (
        IMPORTANCE_W_VOLUME * math.log1p(3 + 1)              # 총 4건
        + IMPORTANCE_W_PUBLISHER * (1.0 + 1.0)               # {매일경제, 한국경제} distinct 합
        + IMPORTANCE_W_SENTIMENT * ((1.8 + 0.6) / (2 + 1))   # (합)/(개수)
    )
    assert got == pytest.approx(expected)


def test_compute_importance_existing_publishers_distinct_with_batch():
    # existing.publishers 와 배치 매체가 겹치면 distinct 로 한 번만 계산(부풀지 않음).
    existing = EventArticleStats(article_count=1, publishers=["조선일보"])
    batch = [_article(publisher="조선일보", sentiment=None)]
    total = importance.compute_importance(batch, existing)
    vol = IMPORTANCE_W_VOLUME * math.log1p(1 + 1)
    # 조선일보 하나만 distinct → 가중치 한 번.
    assert total == pytest.approx(vol + IMPORTANCE_W_PUBLISHER * importance.publisher_weight("조선일보"))


# ---------------------------------------------------------------------------
# nodes/importance.py — 묶기·반영·격리(얇은 노드)
# ---------------------------------------------------------------------------
def test_node_fills_new_event_importance_and_map():
    e1 = Event(canonical_id="e1", canonical_title="사건1")
    state = {
        "articles": [
            _article(event_id="e1", sentiment=Sentiment.POSITIVE, score=0.9),
            _article(event_id="e1", sentiment=Sentiment.POSITIVE, score=0.9),
        ],
        "events_by_id": {"e1": e1},
    }
    out = importance_node(state)
    # 신규 이벤트 객체의 importance 가 채워지고, map 에도 같은 값이 실린다.
    assert e1.importance is not None
    assert out["importance_by_event_id"]["e1"] == pytest.approx(e1.importance)


def test_node_covers_merged_event_without_event_object():
    # 편입(기존) 이벤트는 events_by_id 에 Event 객체가 없어도 map 에는 실려야 한다(TASK 08 반영용).
    state = {
        "articles": [_article(event_id="existing-1", sentiment=None)],
        "events_by_id": {},   # 신규 없음
    }
    out = importance_node(state)
    assert "existing-1" in out["importance_by_event_id"]


def test_node_uses_provider_for_existing_stats():
    provider = FakeStatsProvider({
        "e1": EventArticleStats(article_count=5, publishers=["한국경제"], sentiment_magnitude_sum=0.0, sentiment_count=0),
    })
    e1 = Event(canonical_id="e1", canonical_title="사건1")
    state = {
        "articles": [_article(event_id="e1", publisher="매일경제", sentiment=None)],
        "events_by_id": {"e1": e1},
    }
    importance_node(state, provider=provider)
    assert provider.calls == ["e1"]
    # existing.article_count=5 가 합산됐는지: volume = log1p(5+1).
    expected_vol = IMPORTANCE_W_VOLUME * math.log1p(6)
    pub = IMPORTANCE_W_PUBLISHER * (importance.publisher_weight("매일경제") + importance.publisher_weight("한국경제"))
    assert e1.importance == pytest.approx(expected_vol + pub)


def test_node_ignores_articles_without_event_id():
    e1 = Event(canonical_id="e1", canonical_title="사건1")
    state = {
        "articles": [
            _article(event_id="e1", sentiment=None),
            _article(event_id=None, sentiment=None),   # 병합 skip → 대상 아님
        ],
        "events_by_id": {"e1": e1},
    }
    out = importance_node(state)
    assert set(out["importance_by_event_id"].keys()) == {"e1"}


def test_node_isolates_failure_and_continues():
    # 한 이벤트 계산이 실패해도 다른 이벤트는 계속 계산된다(실패 격리).
    class FlakyProvider:
        def get_event_article_stats(self, event_id):
            if event_id == "bad":
                raise RuntimeError("backend 오류")
            return None

    good = Event(canonical_id="good", canonical_title="정상")
    bad = Event(canonical_id="bad", canonical_title="실패")
    state = {
        "articles": [
            _article(event_id="good", sentiment=None),
            _article(event_id="bad", sentiment=None),
        ],
        "events_by_id": {"good": good, "bad": bad},
    }
    out = importance_node(state, provider=FlakyProvider())
    assert "good" in out["importance_by_event_id"]
    assert "bad" not in out["importance_by_event_id"]
    assert good.importance is not None
    assert bad.importance is None


def test_node_zero_targets_passes_through():
    state = {"articles": [], "events_by_id": {}}
    out = importance_node(state)
    assert out["importance_by_event_id"] == {}
