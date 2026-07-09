# nodes/graph_builder.py
"""그래프 조립 노드(얇게) — event_id 배정 기사를 GraphBatch 로 조립해 state 에 싣는다(TASK 07).

노드는 대상 묶기·서비스 호출·state 반영만 담당하는 얇은 껍데기다(CLAUDE.md §2-2). 노드·관계 생성·dedup·
정렬은 services/graph_builder.py 가 한다. 이 노드에 조립 로직을 두지 않는다.

⚠️ backend 를 직접 호출하지 않는다 — payload(GraphBatch)만 만들고 실제 Neo4j MERGE/저장은 TASK 08 이
   backend HTTP 로 한다(절대규칙 1).
"""
from __future__ import annotations

import logging

import src.agents.news.services.graph_builder as graph_builder
from src.agents.news.schemas.graph import GraphBatch

logger = logging.getLogger(__name__)


def graph_node(state: dict) -> dict:
    """event_id 배정 기사를 build_graph_batch 로 조립해 state["graph_batch"] 에 싣는다.

    - 편입(기존) 이벤트도 델타에 포함된다(HAS_NEWS·개체 관계가 기존 이벤트에도 붙어야 함). 노드는
      이를 걸러내지 않는다 — events_by_id 에 없는 event_id 는 서비스가 얇은 Event 노드로 만든다.
    - 한 이벤트 조립이 실패해도 서비스가 그 이벤트만 skip 하고 나머지를 계속한다(실패 격리, §7).
    - 대상(event_id 배정 기사) 0건이면 예외 없이 빈 GraphBatch 로 통과한다(환각 금지, §2-5).
    - 서비스 전체가 예기치 못하게 실패해도 빈 GraphBatch 로 파이프라인을 살린다(후속·리포트가 "데이터 제한" 처리).
    """
    articles = state.get("articles") or []
    extracts_by_url: dict = state.get("extracts_by_url") or {}
    events_by_id: dict = state.get("events_by_id") or {}
    importance_by_event_id: dict = state.get("importance_by_event_id") or {}

    try:
        batch = graph_builder.build_graph_batch(
            articles, extracts_by_url, events_by_id, importance_by_event_id,
        )
    except Exception as exc:  # 서비스 전체 실패도 파이프라인을 죽이지 않는다(§7)
        logger.warning("graph_node: 그래프 조립 실패 — 빈 GraphBatch 로 통과 (%s)", exc)
        batch = GraphBatch()

    state["graph_batch"] = batch
    logger.info(
        "graph_node: 노드 %d개·관계 %d개 조립(GraphBatch)",
        len(batch.nodes), len(batch.relationships),
    )
    return state
