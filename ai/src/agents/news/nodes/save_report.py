# nodes/save_report.py — 리포트 저장 노드(얇게). report_json 을 backend 에 저장하고 report_id 를 state 에 싣는다.
"""질의 흐름의 마지막 단계. report_node 가 만든 report_json 을 report_client 로 넘겨 영속화하고,
backend 가 돌려준 report_id 를 state 에 반영하는 얇은 껍데기(CLAUDE.md §2-2).

HTTP·매핑·재시도는 services/backend/report_client.py 에. 노드는 순서만 담당하고 backend 를 직접(HTTP)
부르지 않는다(절대규칙 1 — save_node 가 save_client 만 부르는 것과 동형). 저장 실패해도 흐름을 죽이지
않는다 — report_id 없이 통과시킨다(인라인 답변은 report_node 에서 이미 만들어져 나간다, §2-5).
"""
from __future__ import annotations

import logging

import src.agents.news.services.backend.report_client as report_client
from src.agents.news.schemas.query import QueryUnderstanding

logger = logging.getLogger(__name__)


def save_report_node(state: dict) -> dict:
    """state["report_json"] 을 backend 에 저장하고 report_id 를 state["report_id"] 에 싣는다.

    - report_json 이 없으면(이론상 report_node 뒤라 항상 있음) 저장을 건너뛴다(환각 금지).
    - question 은 진입 state["question"](없으면 understanding.original_question), intent 는
      understanding 에서 뽑아 표시/검색용 문자열로만 함께 넘긴다.
    - 저장 실패(report_id None)여도 예외로 흐름을 죽이지 않는다 — report_id 없이 통과(§2-5).
    """
    report_json = state.get("report_json")
    if not report_json:
        logger.info("save_report_node: 저장할 report_json 없음 — 통과")
        return state

    understanding: QueryUnderstanding | None = state.get("understanding")
    intent = understanding.intent.value if understanding and understanding.intent else None
    question = state.get("question") or (understanding.original_question if understanding else None)

    try:
        report_id = report_client.save_report(report_json, question=question, intent=intent)
    except Exception as exc:  # report_client 가 이미 None 으로 보고하지만, 예기치 못한 예외도 흐름을 안 죽임
        logger.error("save_report_node: 저장 호출 예외 — report_id 없이 통과: %s", exc)
        report_id = None

    if report_id:
        state["report_id"] = report_id
        logger.info("save_report_node: 리포트 저장 완료(report_id=%s)", report_id)
    else:
        logger.warning("save_report_node: 리포트 미저장(report_id 없음) — 인라인 응답은 유지")
    return state
