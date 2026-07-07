# tests/test_graph_builder.py
"""services/graph_builder.py + nodes/graph_builder.py 테스트(mock 없음, TASK 07).

그래프 조립은 순수 매핑이라 실제 backend·모델 없이 검증한다(절대규칙 1). 입력은 Article·ExtractResult·
Event·importance_by_event_id fixture 로 구성. 검증 축: 노드/관계 방향·라벨·정체성 키·union/distinct·
감성 미포함·3차 토글·결정성·편입 시나리오·노드 위임/실패격리.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import services.graph_builder as graph_builder
from nodes.graph_builder import graph_node
from schemas.article import Article, ExtractResult
from schemas.event import Event
from schemas.graph import GraphBatch, NodeLabel, RelType

_URL_SEQ = iter(range(1_000_000))


def _article(event_id: str | None = "e1", published_at: datetime | None = None) -> Article:
    n = next(_URL_SEQ)
    return Article(
        title="제목",
        url=f"https://example.com/{n}",
        publisher="매일경제",
        event_id=event_id,
        published_at=published_at,
    )


def _extract(
    companies=None, keywords=None, people=None, countries=None, industries=None,
) -> ExtractResult:
    return ExtractResult(
        summary="요약",
        companies=companies or [],
        keywords=keywords or [],
        people=people or [],
        countries=countries or [],
        industries=industries or [],
    )


def _build(articles, extracts_by_url, events_by_id, importance=None) -> GraphBatch:
    return graph_builder.build_graph_batch(
        articles, extracts_by_url, events_by_id, importance or {},
    )


def _nodes_by_label(batch: GraphBatch, label: NodeLabel):
    return [n for n in batch.nodes if n.label is label]


def _rels_by_type(batch: GraphBatch, rel_type: RelType):
    return [r for r in batch.relationships if r.type is rel_type]


# ---------------------------------------------------------------------------
# 노드/관계 형태 — 방향·라벨
# ---------------------------------------------------------------------------
def test_full_subgraph_shape_labels_and_directions():
    a1, a2 = _article(), _article()
    extracts = {
        str(a1.url): _extract(companies=["삼성전자"], keywords=["HBM"], people=["이재용"], countries=["미국"]),
        str(a2.url): _extract(companies=["SK하이닉스"], keywords=["반도체"]),
    }
    event = Event(canonical_id="e1", canonical_title="HBM 공급 계약", importance=1.5)
    batch = _build([a1, a2], extracts, {"e1": event}, {"e1": 1.5})

    # 노드 라벨
    assert {n.label for n in batch.nodes} == {
        NodeLabel.EVENT, NodeLabel.COMPANY, NodeLabel.KEYWORD,
        NodeLabel.PERSON, NodeLabel.COUNTRY, NodeLabel.NEWS_REF,
    }
    # PARTICIPATES_IN: Company → Event
    for rel in _rels_by_type(batch, RelType.PARTICIPATES_IN):
        assert rel.start_label is NodeLabel.COMPANY
        assert rel.end_label is NodeLabel.EVENT and rel.end_key == "e1"
    # HAS_NEWS: Event → NewsRef, key=url
    news_rels = _rels_by_type(batch, RelType.HAS_NEWS)
    assert len(news_rels) == 2
    for rel in news_rels:
        assert rel.start_label is NodeLabel.EVENT and rel.start_key == "e1"
        assert rel.end_label is NodeLabel.NEWS_REF
        assert rel.end_key.startswith("https://example.com/")
    # HAS_KEYWORD/MENTIONS/ABOUT: Event → 개체
    for rel_type, end_label in (
        (RelType.HAS_KEYWORD, NodeLabel.KEYWORD),
        (RelType.MENTIONS, NodeLabel.PERSON),
        (RelType.ABOUT, NodeLabel.COUNTRY),
    ):
        for rel in _rels_by_type(batch, rel_type):
            assert rel.start_label is NodeLabel.EVENT and rel.start_key == "e1"
            assert rel.end_label is end_label


# ---------------------------------------------------------------------------
# Event 노드 property — 신규 vs 편입, importance 출처
# ---------------------------------------------------------------------------
def test_event_node_new_includes_canonical_title_and_importance():
    a1 = _article()
    event = Event(canonical_id="e1", canonical_title="실적 발표")
    batch = _build([a1], {str(a1.url): _extract()}, {"e1": event}, {"e1": 2.0})
    ev = _nodes_by_label(batch, NodeLabel.EVENT)[0]
    assert ev.key == "e1"
    assert ev.properties["canonical_title"] == "실적 발표"
    assert ev.properties["importance"] == pytest.approx(2.0)


def test_event_node_merged_excludes_canonical_title():
    # 편입(events_by_id 에 없음): canonical_title 미포함(이름 고정), importance 만.
    a1 = _article(event_id="existing-1")
    batch = _build([a1], {str(a1.url): _extract()}, {}, {"existing-1": 3.0})
    ev = _nodes_by_label(batch, NodeLabel.EVENT)[0]
    assert ev.key == "existing-1"
    assert "canonical_title" not in ev.properties
    assert ev.properties["importance"] == pytest.approx(3.0)


def test_event_node_importance_falls_back_to_event_object():
    # importance_by_event_id 에 없으면 Event.importance 사용.
    a1 = _article()
    event = Event(canonical_id="e1", canonical_title="사건", importance=4.2)
    batch = _build([a1], {str(a1.url): _extract()}, {"e1": event}, {})
    ev = _nodes_by_label(batch, NodeLabel.EVENT)[0]
    assert ev.properties["importance"] == pytest.approx(4.2)


def test_event_node_no_importance_omits_property():
    # importance 어디에도 없으면 property 에서 생략(None 을 억지로 넣지 않음).
    a1 = _article(event_id="existing-1")
    batch = _build([a1], {str(a1.url): _extract()}, {}, {})
    ev = _nodes_by_label(batch, NodeLabel.EVENT)[0]
    assert "importance" not in ev.properties
    assert "canonical_title" not in ev.properties


# ---------------------------------------------------------------------------
# NewsRef — url 키, 본문·감성 미포함
# ---------------------------------------------------------------------------
def test_newsref_uses_url_key_and_no_body_or_sentiment():
    published = datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc)
    a1 = _article(published_at=published)
    batch = _build([a1], {str(a1.url): _extract()}, {})
    ref = _nodes_by_label(batch, NodeLabel.NEWS_REF)[0]
    assert ref.key == str(a1.url)
    assert ref.properties["url"] == str(a1.url)
    assert ref.properties["published_at"] == published.isoformat()
    # 본문·요약·감성·news_id 를 넣지 않는다(환각 금지, PostgreSQL 소유).
    for forbidden in ("content", "summary", "sentiment", "news_id", "id"):
        assert forbidden not in ref.properties


def test_newsref_without_published_at_omits_property():
    a1 = _article(published_at=None)
    batch = _build([a1], {str(a1.url): _extract()}, {})
    ref = _nodes_by_label(batch, NodeLabel.NEWS_REF)[0]
    assert set(ref.properties.keys()) == {"url"}


# ---------------------------------------------------------------------------
# union · distinct
# ---------------------------------------------------------------------------
def test_same_company_multiple_articles_single_node_and_rel():
    a1, a2 = _article(), _article()
    extracts = {
        str(a1.url): _extract(companies=["삼성전자"]),
        str(a2.url): _extract(companies=["삼성전자"]),   # 같은 회사, 다른 기사
    }
    event = Event(canonical_id="e1", canonical_title="사건")
    batch = _build([a1, a2], extracts, {"e1": event})
    companies = _nodes_by_label(batch, NodeLabel.COMPANY)
    assert len(companies) == 1
    assert len(_rels_by_type(batch, RelType.PARTICIPATES_IN)) == 1


def test_shared_company_across_events_single_node_rel_per_event():
    a1 = _article(event_id="e1")
    a2 = _article(event_id="e2")
    extracts = {
        str(a1.url): _extract(companies=["삼성전자"]),
        str(a2.url): _extract(companies=["삼성전자"]),
    }
    events = {
        "e1": Event(canonical_id="e1", canonical_title="사건1"),
        "e2": Event(canonical_id="e2", canonical_title="사건2"),
    }
    batch = _build([a1, a2], extracts, events)
    # Company 노드는 1개(공유), PARTICIPATES_IN 은 이벤트마다 1개 = 2개.
    assert len(_nodes_by_label(batch, NodeLabel.COMPANY)) == 1
    rels = _rels_by_type(batch, RelType.PARTICIPATES_IN)
    assert {r.end_key for r in rels} == {"e1", "e2"}


def test_company_name_normalization_merges_variants():
    # (주)·중복 공백 정규화로 같은 회사가 한 노드로 수렴(TASK 05 와 공유 규칙).
    a1, a2 = _article(), _article()
    extracts = {
        str(a1.url): _extract(companies=["㈜삼성전자"]),
        str(a2.url): _extract(companies=["삼성전자"]),
    }
    event = Event(canonical_id="e1", canonical_title="사건")
    batch = _build([a1, a2], extracts, {"e1": event})
    companies = _nodes_by_label(batch, NodeLabel.COMPANY)
    assert len(companies) == 1
    assert companies[0].key == "삼성전자"


# ---------------------------------------------------------------------------
# 빈 개체 제외 (환각 금지)
# ---------------------------------------------------------------------------
def test_blank_entities_excluded():
    a1 = _article()
    extracts = {str(a1.url): _extract(companies=["", "   ", "삼성전자"], keywords=[""])}
    event = Event(canonical_id="e1", canonical_title="사건")
    batch = _build([a1], extracts, {"e1": event})
    companies = _nodes_by_label(batch, NodeLabel.COMPANY)
    assert [c.key for c in companies] == ["삼성전자"]
    assert _nodes_by_label(batch, NodeLabel.KEYWORD) == []


def test_no_entities_means_no_entity_relations():
    a1 = _article()
    batch = _build([a1], {str(a1.url): _extract()}, {"e1": Event(canonical_id="e1", canonical_title="사건")})
    # Event + NewsRef 만, 개체 관계 없음.
    assert _rels_by_type(batch, RelType.PARTICIPATES_IN) == []
    assert _rels_by_type(batch, RelType.HAS_KEYWORD) == []
    assert _rels_by_type(batch, RelType.HAS_NEWS)  # HAS_NEWS 는 있음


# ---------------------------------------------------------------------------
# 3차 토글 — BELONGS_TO / RELATED_TO
# ---------------------------------------------------------------------------
def test_belongs_to_related_to_off_by_default():
    a1 = _article()
    extracts = {str(a1.url): _extract(companies=["삼성전자", "SK하이닉스"], industries=["반도체"])}
    event = Event(canonical_id="e1", canonical_title="사건")
    batch = _build([a1], extracts, {"e1": event})
    assert _rels_by_type(batch, RelType.BELONGS_TO) == []
    assert _rels_by_type(batch, RelType.RELATED_TO) == []
    assert _nodes_by_label(batch, NodeLabel.SECTOR) == []


def test_related_to_generated_when_enabled(monkeypatch):
    monkeypatch.setattr(graph_builder, "GRAPH_ENABLE_RELATED_TO", True)
    a1 = _article()
    extracts = {str(a1.url): _extract(companies=["삼성전자", "SK하이닉스"])}
    event = Event(canonical_id="e1", canonical_title="사건")
    batch = _build([a1], extracts, {"e1": event})
    related = _rels_by_type(batch, RelType.RELATED_TO)
    assert len(related) == 1
    assert related[0].start_label is NodeLabel.COMPANY
    assert related[0].end_label is NodeLabel.COMPANY


def test_belongs_to_generated_when_enabled(monkeypatch):
    monkeypatch.setattr(graph_builder, "GRAPH_ENABLE_BELONGS_TO", True)
    a1 = _article()
    extracts = {str(a1.url): _extract(companies=["삼성전자"], industries=["반도체"])}
    event = Event(canonical_id="e1", canonical_title="사건")
    batch = _build([a1], extracts, {"e1": event})
    assert len(_nodes_by_label(batch, NodeLabel.SECTOR)) == 1
    belongs = _rels_by_type(batch, RelType.BELONGS_TO)
    assert len(belongs) == 1
    assert belongs[0].start_label is NodeLabel.COMPANY
    assert belongs[0].end_label is NodeLabel.SECTOR


# ---------------------------------------------------------------------------
# 감성 미포함
# ---------------------------------------------------------------------------
def test_no_sentiment_property_anywhere():
    a1 = _article()
    extracts = {str(a1.url): _extract(companies=["삼성전자"], keywords=["HBM"])}
    event = Event(canonical_id="e1", canonical_title="사건", importance=1.0)
    batch = _build([a1], extracts, {"e1": event}, {"e1": 1.0})
    for node in batch.nodes:
        for key in node.properties:
            assert "sentiment" not in key.lower()
            assert "count" not in key.lower()
            assert "gauge" not in key.lower()


# ---------------------------------------------------------------------------
# 결정성
# ---------------------------------------------------------------------------
def test_deterministic_same_input_same_output():
    a1, a2 = _article(), _article()
    extracts = {
        str(a1.url): _extract(companies=["삼성전자", "SK하이닉스"], keywords=["HBM", "반도체"]),
        str(a2.url): _extract(companies=["삼성전자"], people=["이재용"]),
    }
    event = Event(canonical_id="e1", canonical_title="사건", importance=1.0)
    b1 = _build([a1, a2], extracts, {"e1": event}, {"e1": 1.0})
    b2 = _build([a1, a2], extracts, {"e1": event}, {"e1": 1.0})
    assert b1.model_dump() == b2.model_dump()
    # 노드·관계가 정체성 키로 정렬돼 있는지.
    node_keys = [(n.label.value, n.key) for n in b1.nodes]
    assert node_keys == sorted(node_keys)


# ---------------------------------------------------------------------------
# 편입 시나리오 — events_by_id 에 없는 event_id 만
# ---------------------------------------------------------------------------
def test_merged_only_scenario_builds_thin_event_and_relations():
    a1 = _article(event_id="existing-1")
    extracts = {str(a1.url): _extract(companies=["삼성전자"], keywords=["HBM"])}
    batch = _build([a1], extracts, {}, {"existing-1": 5.0})
    ev = _nodes_by_label(batch, NodeLabel.EVENT)[0]
    assert ev.key == "existing-1"
    assert "canonical_title" not in ev.properties      # 얇은 노드
    assert _rels_by_type(batch, RelType.HAS_NEWS)       # HAS_NEWS 붙음
    assert _rels_by_type(batch, RelType.PARTICIPATES_IN)  # 개체 관계 붙음


# ---------------------------------------------------------------------------
# 경계 케이스
# ---------------------------------------------------------------------------
def test_articles_without_event_id_excluded():
    a1 = _article(event_id=None)   # 병합 skip
    batch = _build([a1], {str(a1.url): _extract(companies=["삼성전자"])}, {})
    assert batch.nodes == []
    assert batch.relationships == []


def test_empty_batch_when_no_targets():
    batch = _build([], {}, {})
    assert isinstance(batch, GraphBatch)
    assert batch.nodes == []
    assert batch.relationships == []


def test_single_article_single_event():
    a1 = _article()
    batch = _build([a1], {str(a1.url): _extract()}, {"e1": Event(canonical_id="e1", canonical_title="사건")})
    assert len(_nodes_by_label(batch, NodeLabel.EVENT)) == 1
    assert len(_nodes_by_label(batch, NodeLabel.NEWS_REF)) == 1


def test_article_without_extract_still_makes_newsref():
    # 추출 결과 없는 기사도 NewsRef·HAS_NEWS 는 만든다(개체만 없음).
    a1 = _article()
    batch = _build([a1], {}, {"e1": Event(canonical_id="e1", canonical_title="사건")})
    assert len(_nodes_by_label(batch, NodeLabel.NEWS_REF)) == 1
    assert _nodes_by_label(batch, NodeLabel.COMPANY) == []


# ---------------------------------------------------------------------------
# nodes/graph_builder.py — 얇은 노드
# ---------------------------------------------------------------------------
def test_graph_node_fills_state_graph_batch():
    a1 = _article()
    state = {
        "articles": [a1],
        "extracts_by_url": {str(a1.url): _extract(companies=["삼성전자"])},
        "events_by_id": {"e1": Event(canonical_id="e1", canonical_title="사건")},
        "importance_by_event_id": {"e1": 1.0},
    }
    out = graph_node(state)
    assert isinstance(out["graph_batch"], GraphBatch)
    assert out["graph_batch"].nodes


def test_graph_node_zero_targets_empty_batch():
    state = {"articles": [], "events_by_id": {}}
    out = graph_node(state)
    assert isinstance(out["graph_batch"], GraphBatch)
    assert out["graph_batch"].nodes == []


def test_graph_node_isolates_service_failure(monkeypatch):
    # build_graph_batch 가 폭발해도 노드는 빈 GraphBatch 로 통과한다(파이프라인 계속).
    def boom(*args, **kwargs):
        raise RuntimeError("조립 오류")

    monkeypatch.setattr(graph_builder, "build_graph_batch", boom)
    state = {"articles": [_article()], "events_by_id": {}}
    out = graph_node(state)
    assert isinstance(out["graph_batch"], GraphBatch)
    assert out["graph_batch"].nodes == []


def test_build_graph_batch_isolates_one_event_failure(monkeypatch):
    # 한 이벤트 서브그래프 조립 실패 시 그 이벤트만 skip, 나머지 계속(§7).
    real = graph_builder.build_event_subgraph

    def flaky(event_id, event, articles, extracts, importance):
        if event_id == "bad":
            raise RuntimeError("서브그래프 오류")
        return real(event_id, event, articles, extracts, importance)

    monkeypatch.setattr(graph_builder, "build_event_subgraph", flaky)
    a_good = _article(event_id="good")
    a_bad = _article(event_id="bad")
    extracts = {str(a_good.url): _extract(), str(a_bad.url): _extract()}
    events = {
        "good": Event(canonical_id="good", canonical_title="정상"),
        "bad": Event(canonical_id="bad", canonical_title="실패"),
    }
    batch = _build([a_good, a_bad], extracts, events)
    event_keys = {n.key for n in _nodes_by_label(batch, NodeLabel.EVENT)}
    assert event_keys == {"good"}
