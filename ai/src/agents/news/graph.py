# graph.py — LangGraph 배선 & 진입점(얇게). TASK 11 소유.
"""TASK 02~09 가 만든 노드들을 두 개의 실제 파이프라인으로 잇고, Supervisor·스케줄러가 부를
진입점을 노출한다.

- 배치 그래프: crawl → extract → sentiment → embedding → merge_event → importance → graph → save
  (CLAUDE.md §3). merge_event·importance 에는 조회 Provider(TASK 08)를 **주입**한다.
- 질의 그래프: query → report(query_spec §1). backend 접근은 query 노드 내부 query_client 로만.

⚠️ 절대규칙 1·2: 이 파일은 노드를 **등록·순서 지정·Provider 주입·컴파일**만 한다. backend·LLM·DB 를
   직접 부르지 않고(SQL·Cypher·HTTP 없음), 파이프라인/질의 로직을 복제하지 않는다(§4·§5). 실제 로직은
   nodes/services(TASK 02~09) 소유.
⚠️ 배선 라이브러리(LangGraph) import 는 이 파일의 **build 함수 안에만** 가둔다 — 모듈은 라이브러리
   없이도 import 되고, 배선 수단을 갈아끼울 여지를 남긴다(CLAUDE.md §7, 스케줄러의 APScheduler 격리와 동형).
"""
from __future__ import annotations

import functools
import logging
from dataclasses import dataclass

from config import GRAPH_RECURSION_LIMIT
from nodes.crawl import crawl_node
from nodes.embedding import embedding_node
from nodes.extract import extract_node
from nodes.graph_builder import graph_node
from nodes.importance import importance_node
from nodes.merge_event import merge_event_node
from nodes.query import query_node
from nodes.report import report_node
from nodes.save import save_node
from nodes.sentiment import sentiment_node
from state import BatchState, QueryState

logger = logging.getLogger(__name__)


@dataclass
class BatchProviders:
    """merge_event·importance 에 주입할 조회 Provider 묶음(TASK 05/06 인터페이스).

    - recent_event: RecentEventProvider(병합 후보 조회) — merge_event_node 에 주입.
    - event_stats: EventArticleStatsProvider(누적 통계 조회) — importance_node 에 주입.
    둘 다 None 이면 각 노드의 기본(degrade) provider 로 동작한다(모든 기사 신규·근사 importance, TASK 05/06).
    """

    recent_event: object | None = None
    event_stats: object | None = None


def _default_batch_providers() -> BatchProviders:
    """운영 기본 = backend HTTP 구현(TASK 08). lazy import 로 두어 (1) 모듈 top-level 을 얇게 유지하고,
    (2) 테스트가 fake Provider 를 주입해 backend 없이 배선을 검증할 수 있게 한다(절대규칙 1 경계).

    생성자는 BackendClient 를 만들 뿐 네트워크를 치지 않는다. 실제 조회 실패는 각 Provider 가 []/None 으로
    degrade 하므로(providers.py §4.2), backend 미연결에서도 배치가 죽지 않는다.
    """
    from services.backend.providers import (
        BackendEventArticleStatsProvider,
        BackendRecentEventProvider,
    )

    return BatchProviders(
        recent_event=BackendRecentEventProvider(),
        event_stats=BackendEventArticleStatsProvider(),
    )


def build_batch_graph(providers: BatchProviders | None = None):
    """배치 노드를 crawl→…→save 순서로 등록·연결한 컴파일된 앱을 반환한다.

    merge_event·importance 에 Provider 를 `functools.partial(node, provider=…)` 로 주입해 `(state)->state`
    형태를 유지한다(노드는 backend 를 직접 import 하지 않고, 배선만 인프라를 안다, §2). providers 미지정 시
    운영 기본(backend, TASK 08). 테스트는 fake 또는 `BatchProviders()`(둘 다 None → degrade)를 넘긴다.
    """
    from langgraph.graph import END, START, StateGraph

    if providers is None:
        providers = _default_batch_providers()

    builder = StateGraph(BatchState)
    builder.add_node("crawl", crawl_node)
    builder.add_node("extract", extract_node)
    builder.add_node("sentiment", sentiment_node)
    builder.add_node("embedding", embedding_node)
    # Provider 주입: 노드는 (state, provider=…) 계약(TASK 05/06). partial 로 (state)->state 로 감싼다.
    builder.add_node("merge_event", functools.partial(merge_event_node, provider=providers.recent_event))
    builder.add_node("importance", functools.partial(importance_node, provider=providers.event_stats))
    builder.add_node("graph", graph_node)
    builder.add_node("save", save_node)

    builder.add_edge(START, "crawl")
    builder.add_edge("crawl", "extract")
    builder.add_edge("extract", "sentiment")
    builder.add_edge("sentiment", "embedding")
    builder.add_edge("embedding", "merge_event")
    builder.add_edge("merge_event", "importance")
    builder.add_edge("importance", "graph")
    builder.add_edge("graph", "save")
    builder.add_edge("save", END)
    return builder.compile()


def build_query_graph():
    """질의 노드 query → report 를 연결한 컴파일된 앱을 반환한다.

    backend 접근은 query 노드 내부의 query_client(TASK 08)로만 일어난다 — 이 파일은 주입할 Provider 도
    없이 노드를 잇기만 한다(질의측은 노드가 서비스를 직접 부르는 구조, TASK 09).
    """
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(QueryState)
    builder.add_node("query", query_node)
    builder.add_node("report", report_node)

    builder.add_edge(START, "query")
    builder.add_edge("query", "report")
    builder.add_edge("report", END)
    return builder.compile()


def _run_config() -> dict:
    """LangGraph invoke 실행 옵션. 배선 옵션은 config 에서 읽는다(하드코딩 금지, §3.3)."""
    return {"recursion_limit": GRAPH_RECURSION_LIMIT}


def run_batch(state: BatchState | None = None) -> BatchState:
    """배치 그래프를 초기 state 로 invoke 해 최종 state 를 반환한다.

    TASK 10 `run_batch_once` 가 이 진입점을 부른다(초기 state = 빈 dict). 운영 Provider(backend)로 조립한다.
    """
    app = build_batch_graph()
    return app.invoke(dict(state or {}), config=_run_config())


def run_query(question: str) -> dict:
    """질의 그래프를 질문 문자열로 invoke 해 최종 JSON 리포트(state["report_json"])를 반환한다.

    Supervisor 진입점(CLAUDE.md §1: Supervisor 는 graph.py 만 호출). 출력은 HTML 이 아니라 JSON 이다
    (팀 계약: ai·backend·frontend JSON 통일 — backend 저장·frontend 렌더). 종목 프리셋도 question
    문자열로 온다. 렌더 실패 시에도 report 노드가 최소 '데이터 제한' JSON 으로 degrade 하므로(TASK 09)
    항상 dict 를 돌려준다.
    """
    app = build_query_graph()
    result = app.invoke({"question": question}, config=_run_config())
    return result.get("report_json") or {}
