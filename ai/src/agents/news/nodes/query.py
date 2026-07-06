# nodes/query.py — 질의 노드(얇게). ①질문이해 → ②그래프순회 → ④답변생성 순서만 담당.
"""로직은 services 에, 노드는 순서만(CLAUDE.md §2-2). backend·LLM 을 직접 부르지 않고 서비스만 호출한다.

한 단계 실패(LLM 파싱·BackendError)해도 예외로 흐름을 죽이지 않고 '데이터 제한'으로 통과시킨다
(절대규칙 5·§7). ③ 근거 기사 조회는 answer_generator 가 query_client 로 대행한다(§4.1).
"""
from __future__ import annotations

import logging

import services.answer_generator as answer_generator
import services.graph_query as graph_query
import services.query_understanding as query_understanding
from schemas.query import QueryUnderstanding

logger = logging.getLogger(__name__)


def query_node(state: dict) -> dict:
    """state["question"](또는 state["subject"]) → understanding·query_response·answer 를 state 에 싣는다."""
    subject = state.get("subject")
    question = state.get("question")

    # ① 질문이해: 종목 선택은 프리셋, 자유 질문은 사전+LLM. 실패해도 빈 회사로 degrade.
    try:
        if subject:
            understanding = query_understanding.from_subject(subject)
        else:
            understanding = query_understanding.understand_query(question or "")
    except Exception as exc:  # 방어: 서비스가 이미 degrade 하지만 노드도 흐름을 죽이지 않는다
        logger.warning("query_node: 질문이해 실패 → 빈 이해로 degrade: %s", exc)
        understanding = QueryUnderstanding(original_question=question or subject or "")

    # ② 그래프순회(설계→backend). BackendError 는 서비스가 degrade(빈/subject_found=False).
    response = graph_query.fetch_events(understanding)

    # ④ 답변생성(③ 근거는 answer_generator 가 query_client 로 조회). 실패 시 data_limited.
    answer = answer_generator.generate_answer(understanding, response)

    state["understanding"] = understanding
    state["query_response"] = response
    state["answer"] = answer
    return state
