# state.py — 파이프라인 상태 키 계약(단일 출처). TASK 11 소유.
"""배치·질의 두 흐름의 노드가 주고받는 state 키를 한 곳에 못박는 TypedDict 계약.

TASK 02~09 의 노드들은 `state["articles"]`·`state["extracts_by_url"]` 처럼 문자열 키로
데이터를 주고받는다. 키·타입이 문서에 흩어지면 오타·타입 불일치가 런타임에야 드러나므로,
여기 `BatchState`·`QueryState` 를 **키의 유일한 정의(single source of truth)** 로 둔다. 노드가
새 키를 쓰려면 이 표부터 고친다(TASK 11 §3.1).

- `total=False`: 배치는 crawl→…→save 로 진행하며 키가 **점진적으로** 채워진다(초기엔 articles 만,
  나중에 graph_batch). 모든 키를 처음부터 요구하지 않도록 부분 딕셔너리를 허용한다(§0 배경).
- news 전용(자기완결, CLAUDE.md §1). 공유 GraphState 에 얹지 않는다 — 다른 워커와 키가 충돌한다.
- 여기엔 **타입만** 둔다 — 배선·실행 로직은 graph.py, 각 단계 로직은 nodes/services(절대규칙 2).
"""
from __future__ import annotations

from typing import TypedDict

from src.agents.news.schemas.article import Article, ExtractResult
from src.agents.news.schemas.event import Event
from src.agents.news.schemas.graph import GraphBatch
from src.agents.news.schemas.query import Answer, QueryUnderstanding
from src.agents.news.schemas.report import ReportModel
from src.agents.news.schemas.response import SaveResponse, SubjectQueryResponse


class BatchState(TypedDict, total=False):
    """배치 흐름(crawl → … → save)의 상태 키 계약. 채우는/소비하는 노드는 TASK 11 §3.1 표 참조."""

    articles: list[Article]                        # crawl(02) → extract·sentiment·embedding·merge·importance·graph·save
    extracts_by_url: dict[str, ExtractResult]      # extract(03) → merge_event·graph
    events_by_id: dict[str, Event]                 # merge_event(05, 신규 이벤트) → importance·graph
    importance_by_event_id: dict[str, float]       # importance(06, 신규+편입) → graph·save
    graph_batch: GraphBatch                        # graph(07) → save
    save_result: SaveResponse                      # save(08) → (스케줄러 로깅)


class QueryState(TypedDict, total=False):
    """질의 흐름(query → report)의 상태 키 계약. Supervisor 는 question 을 넣고 report_json 을 받는다(§3.1)."""

    question: str                                  # 진입(Supervisor 입력. 종목 프리셋도 문자열) → query
    understanding: QueryUnderstanding              # query(09, ①) → query·report
    query_response: SubjectQueryResponse           # query(②) → query·report
    answer: Answer                                 # query(④) → report
    report_model: ReportModel                      # report(09) → report
    report_json: dict                              # report(최종 산출, JSON) → Supervisor·backend·frontend
    report_id: str                                 # save_report(백엔드 저장 후 backend 발급) → Supervisor·frontend(GET /news/reports/{id})
