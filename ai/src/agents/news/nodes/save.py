# nodes/save.py — 저장 노드(얇게, TASK 08)
"""배치 흐름의 마지막 단계. state 의 산출물을 save_client 로 넘기고 결과를 반영하는 얇은 껍데기.

노드는 순서만 담당한다(CLAUDE.md §2-2). HTTP·매핑·재시도·원자성 계약은 services/backend/save_client.py 에.
backend 를 직접(HTTP) 부르지 않는다 — save_client 만 호출한다(절대규칙 1 경계 유지).

정직 보고(§2-5): 저장 실패를 성공으로 위장하지 않는다. save_client 가 실패를 SaveResponse(ok=False)
로 돌려주면 그대로 state 에 남기고 로깅한다. 저장 호출이 예외를 던져도 스케줄러 루프를 죽이지 않고
(다음 주기 재시도, TASK 10) ok=False 로 통과시킨다.
"""
from __future__ import annotations

import logging

import src.agents.news.services.backend.save_client as save_client
from src.agents.news.schemas.graph import GraphBatch
from src.agents.news.schemas.response import SaveResponse

logger = logging.getLogger(__name__)


def save_node(state: dict) -> dict:
    """state["articles"] + state["graph_batch"] 를 save_client.save_batch 로 저장하고 결과를 반영한다.

    - 원자성 계약(§3.3): 같은 state 에서 나온 articles·graph_batch 짝을 함께 넘긴다(서로 다른 배치 안 섞음).
    - 대상 0건(articles 없음·graph_batch 비었음)이면 예외 없이 통과한다(환각 금지, backend 호출 없음).
    - 결과는 state["save_result"] 에 반영. ok=False 면 실패를 명확히 로깅(성공 위장 금지).
    - 저장 호출이 실패/예외여도 루프를 죽이지 않는다 — 로깅 후 ok=False 로 통과(TASK 10 이 다음 주기 재시도).
    """
    articles = state.get("articles") or []
    graph_batch: GraphBatch | None = state.get("graph_batch")
    graph_empty = graph_batch is None or (not graph_batch.nodes and not graph_batch.relationships)

    if not articles and graph_empty:
        logger.info("save_node: 저장 대상 0건 — backend 호출 없이 통과")
        return state

    if graph_batch is None:  # 방어: articles 는 있는데 graph 가 없으면 빈 델타로(원자성 유지)
        graph_batch = GraphBatch()

    try:
        result = save_client.save_batch(articles, graph_batch)
    except Exception as exc:  # save_client 가 이미 ok=False 로 보고하지만, 예기치 못한 예외도 루프를 안 죽임(§3.6-3)
        logger.error("save_node: 저장 호출 예외 — ok=False 로 통과(다음 주기 재시도): %s", exc)
        result = SaveResponse(ok=False, saved=0, message=str(exc))

    state["save_result"] = result
    if result.ok:
        logger.info("save_node: 저장 완료(saved=%d)", result.saved)
    else:
        logger.error("save_node: 저장 실패(ok=False) — %s", result.message)
    return state
