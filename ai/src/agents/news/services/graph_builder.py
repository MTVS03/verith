# services/graph_builder.py
"""지식그래프 조립 서비스 — 순수·결정적(TASK 07).

입력(이벤트 배정된 기사 · ExtractResult · Event · importance) → 출력(GraphBatch)의 순수 함수다.
이번 배치가 backend 로 보낼 "델타 payload"만 만든다. 실제 Neo4j MERGE/저장은 backend(TASK 08)가
HTTP 로 한다(절대규칙 1).

⚠️ 경계:
 - LLM(services/llm.py)·감성 모델·backend/DB 를 호출하지 않는다. 기존 그래프를 읽지 않는다(합치기는 backend MERGE).
 - 감성·importance·병합을 재계산하지 않는다(이미 계산된 값을 소비만).
 - 결정적: 난수·시간·UUID 생성이 없다(canonical_id 는 TASK 05 가 이미 부여). 노드·관계를 정렬 순서로 방출.
 - 환각 금지: 추출된 개체·있는 url 만 그래프에 넣는다. 없는 news_id·근거 없는 관계를 지어내지 않는다.

정체성 키(backend MERGE 계약, TASK 07 §0.2):
 - Event = canonical_id(UUID) · 개체 = 정규화된 이름 · NewsRef = str(url).
 - 개체 이름 정규화는 TASK 05(company_overlap)와 공유하는 utils.entity.normalize_entity_name(최소·결정적)로
   통일한다 — 정규화가 갈라지면 같은 회사가 다른 노드로 쪼개진다.
"""
from __future__ import annotations

import logging

from src.agents.news.config import (
    GRAPH_ENABLE_BELONGS_TO,
    GRAPH_ENABLE_RELATED_TO,
)
from src.agents.news.schemas.article import Article, ExtractResult
from src.agents.news.schemas.event import Event
from src.agents.news.schemas.graph import (
    GraphBatch,
    GraphNode,
    GraphRelationship,
    NodeLabel,
    RelType,
)
from src.agents.news.utils.entity import normalize_entity_name

logger = logging.getLogger(__name__)


def event_node(event: Event | None, event_id: str, importance: float | None) -> GraphNode:
    """Event 노드. key=canonical_id, props={canonical_title(신규만), importance}.

    편입(기존) 이벤트로 `event`가 None 일 때는 canonical_title 없이 canonical_id + importance 만 담는
    얇은 노드를 만든다(이름 고정, event_merge.md §6 — backend 에 이미 canonical_title 이 있으므로 안 바꾼다).
    importance 가 None 이면 property 에서 생략한다(None 을 억지로 넣지 않음).
    """
    properties: dict = {}
    # 신규 이벤트만 canonical_title 을 실어 full 노드로. 편입 이벤트는 이름을 payload 에 넣지 않는다.
    if event is not None and event.canonical_title:
        properties["canonical_title"] = event.canonical_title
    if importance is not None:
        properties["importance"] = importance
    return GraphNode(label=NodeLabel.EVENT, key=event_id, properties=properties)


def _entity_names(extracts: list[ExtractResult], attr: str) -> list[str]:
    """이벤트 소속 기사들의 ExtractResult 에서 한 개체 종류(attr)의 이름을 union·정규화·distinct 로 모은다.

    빈/공백 이름은 제외한다(환각 금지). 최초 등장 순서를 보존해 결정적으로 반환(최종 dedup·정렬은 배치에서).
    """
    seen: dict[str, None] = {}
    for extract in extracts:
        for raw in getattr(extract, attr, None) or []:
            name = normalize_entity_name(raw)
            if name:
                seen.setdefault(name, None)
    return list(seen.keys())


def entity_nodes_and_rels(
    event_id: str, articles: list[Article], extracts: list[ExtractResult],
) -> tuple[list[GraphNode], list[GraphRelationship]]:
    """한 이벤트의 개체 서브그래프(회사/키워드/인물/국가 + 관계). member 기사 union·이름 distinct.

    - 회사   → Company + (Company)-[:PARTICIPATES_IN]->(Event)
    - 키워드 → Keyword + (Event)-[:HAS_KEYWORD]->(Keyword)
    - 인물   → Person  + (Event)-[:MENTIONS]->(Person)
    - 국가   → Country + (Event)-[:ABOUT]->(Country)
    빈/공백 이름 제외(환각 금지). BELONGS_TO/RELATED_TO 는 config 토글이 켜진 경우에만 생성(기본 미생성).
    """
    nodes: list[GraphNode] = []
    rels: list[GraphRelationship] = []

    companies = _entity_names(extracts, "companies")
    keywords = _entity_names(extracts, "keywords")
    people = _entity_names(extracts, "people")
    countries = _entity_names(extracts, "countries")

    # 회사: 방향이 Company→Event(PARTICIPATES_IN) 로 나머지와 반대다.
    for name in companies:
        nodes.append(GraphNode(label=NodeLabel.COMPANY, key=name, properties={"name": name}))
        rels.append(
            GraphRelationship(
                type=RelType.PARTICIPATES_IN,
                start_label=NodeLabel.COMPANY, start_key=name,
                end_label=NodeLabel.EVENT, end_key=event_id,
            )
        )

    # 키워드/인물/국가: Event→개체 방향.
    for names, label, rel_type in (
        (keywords, NodeLabel.KEYWORD, RelType.HAS_KEYWORD),
        (people, NodeLabel.PERSON, RelType.MENTIONS),
        (countries, NodeLabel.COUNTRY, RelType.ABOUT),
    ):
        for name in names:
            nodes.append(GraphNode(label=label, key=name, properties={"name": name}))
            rels.append(
                GraphRelationship(
                    type=rel_type,
                    start_label=NodeLabel.EVENT, start_key=event_id,
                    end_label=label, end_key=name,
                )
            )

    # --- 3차·보류 관계(기본 미생성, config 토글이 켜질 때만) ---------------------------
    if GRAPH_ENABLE_BELONGS_TO:
        # ⚠️ 회사↔산업 매핑이 추출에 없어 같은 기사 회사×산업 전조합을 잇는다(근거 약함, pipeline_spec §12).
        industries = _entity_names(extracts, "industries")
        for sector in industries:
            nodes.append(GraphNode(label=NodeLabel.SECTOR, key=sector, properties={"name": sector}))
        for company in companies:
            for sector in industries:
                rels.append(
                    GraphRelationship(
                        type=RelType.BELONGS_TO,
                        start_label=NodeLabel.COMPANY, start_key=company,
                        end_label=NodeLabel.SECTOR, end_key=sector,
                    )
                )
    if GRAPH_ENABLE_RELATED_TO:
        # ⚠️ 같은 이벤트를 공유한 회사쌍을 잇는다(3차, pipeline_spec §12). 무방향이라 정렬쌍 한 방향만.
        for i, a in enumerate(companies):
            for b in companies[i + 1:]:
                start, end = sorted((a, b))
                rels.append(
                    GraphRelationship(
                        type=RelType.RELATED_TO,
                        start_label=NodeLabel.COMPANY, start_key=start,
                        end_label=NodeLabel.COMPANY, end_key=end,
                    )
                )

    return nodes, rels


def news_nodes_and_rels(
    event_id: str, articles: list[Article],
) -> tuple[list[GraphNode], list[GraphRelationship]]:
    """이벤트 기사마다 NewsRef(key=str(url)) + (Event)-[:HAS_NEWS]->(NewsRef).

    본문·요약·감성은 넣지 않는다(PostgreSQL 소유). news_id 는 저장 시 backend 가 url 로 해소(§2).
    Article.url 은 HttpUrl 이므로 문자열로 변환해 key·property 를 일관 유지한다.
    빈 url 은 스키마상 발생하지 않지만(Article.url 필수) 방어적으로 제외한다.
    """
    nodes: list[GraphNode] = []
    rels: list[GraphRelationship] = []
    for article in articles:
        url = str(article.url).strip()
        if not url:
            continue
        properties: dict = {"url": url}
        if article.published_at is not None:
            # datetime → ISO8601 문자열(JSON 직렬화 가능, backend 합의 포맷).
            properties["published_at"] = article.published_at.isoformat()
        nodes.append(GraphNode(label=NodeLabel.NEWS_REF, key=url, properties=properties))
        rels.append(
            GraphRelationship(
                type=RelType.HAS_NEWS,
                start_label=NodeLabel.EVENT, start_key=event_id,
                end_label=NodeLabel.NEWS_REF, end_key=url,
            )
        )
    return nodes, rels


def build_event_subgraph(
    event_id: str,
    event: Event | None,
    articles: list[Article],
    extracts: list[ExtractResult],
    importance: float | None,
) -> tuple[list[GraphNode], list[GraphRelationship]]:
    """한 이벤트의 Event 노드 + 개체 서브그래프 + NewsRef 를 합쳐 반환(dedup·정렬은 build_graph_batch)."""
    nodes: list[GraphNode] = [event_node(event, event_id, importance)]
    rels: list[GraphRelationship] = []

    entity_nodes, entity_rels = entity_nodes_and_rels(event_id, articles, extracts)
    news_nodes, news_rels = news_nodes_and_rels(event_id, articles)

    nodes.extend(entity_nodes)
    nodes.extend(news_nodes)
    rels.extend(entity_rels)
    rels.extend(news_rels)
    return nodes, rels


def _node_identity(node: GraphNode) -> tuple[str, str]:
    return (node.label.value, node.key)


def _rel_identity(rel: GraphRelationship) -> tuple[str, str, str, str, str]:
    return (rel.type.value, rel.start_label.value, rel.start_key, rel.end_label.value, rel.end_key)


def build_graph_batch(
    articles: list[Article],
    extracts_by_url: dict,
    events_by_id: dict,
    importance_by_event_id: dict,
) -> GraphBatch:
    """event_id 배정 기사를 이벤트별로 묶어 서브그래프를 조립한 뒤 배치 전체 dedup·정렬해 반환한다.

    - 대상: event_id 가 배정된 기사만(병합 통과, TASK 05). 없으면 빈 GraphBatch.
    - 신규 이벤트 = events_by_id(full 노드), 편입 = events_by_id 에 없으면 얇은 노드(canonical_id+importance).
    - importance = importance_by_event_id 우선, 없으면 Event.importance(신규만 있음).
    - dedup: 노드 (label,key), 관계 (type,start,end). 공유 Company·Country 는 노드 1개, 관계는 이벤트마다.
    - 결정성: 정체성 키 기준 정렬 방출. 한 이벤트 조립이 실패해도 로깅 후 그 이벤트만 skip, 나머지 계속(§7).
    """
    extracts_by_url = extracts_by_url or {}
    events_by_id = events_by_id or {}
    importance_by_event_id = importance_by_event_id or {}

    # 이벤트별로 기사·추출을 묶는다(event_id 없는 기사 = 병합 skip → 대상 아님).
    grouped_articles: dict[str, list[Article]] = {}
    grouped_extracts: dict[str, list[ExtractResult]] = {}
    for article in articles or []:
        event_id = article.event_id
        if not event_id:
            continue
        grouped_articles.setdefault(event_id, []).append(article)
        extract = extracts_by_url.get(str(article.url))
        if extract is not None:
            grouped_extracts.setdefault(event_id, []).append(extract)

    node_by_id: dict[tuple[str, str], GraphNode] = {}
    rel_by_id: dict[tuple[str, str, str, str, str], GraphRelationship] = {}

    for event_id, event_articles in grouped_articles.items():
        try:
            event = events_by_id.get(event_id)
            importance = importance_by_event_id.get(event_id)
            if importance is None and event is not None:
                importance = event.importance
            nodes, rels = build_event_subgraph(
                event_id, event, event_articles, grouped_extracts.get(event_id, []), importance,
            )
        except Exception as exc:  # 한 이벤트 실패가 전체 배치를 죽이지 않도록 격리(§7)
            logger.warning("그래프 서브그래프 조립 실패, skip: event_id=%s (%s)", event_id, exc)
            continue

        # 배치 전체 dedup: 같은 (label,key)/(type,start,end)는 최초 1개만 유지.
        for node in nodes:
            node_by_id.setdefault(_node_identity(node), node)
        for rel in rels:
            rel_by_id.setdefault(_rel_identity(rel), rel)

    # 결정성: 정체성 키로 정렬 방출(같은 입력 → 같은 GraphBatch).
    sorted_nodes = [node_by_id[k] for k in sorted(node_by_id.keys())]
    sorted_rels = [rel_by_id[k] for k in sorted(rel_by_id.keys())]
    return GraphBatch(nodes=sorted_nodes, relationships=sorted_rels)
