# nodes/report.py — 리포트 노드(얇게). report_renderer 로 JSON 리포트 하나를 만들어 state 에 싣는다.
"""조립·직렬화 로직은 services/report_renderer 에, 노드는 호출만(CLAUDE.md §2-2).

출력은 **JSON 리포트 하나**다(팀 계약: ai·backend·frontend JSON 통일 — backend 저장, frontend 렌더).
④ 답변은 별도 채널이 아니라 report_json 의 answer_text·근거 칩으로 내장된다(별도 텍스트 출력 없음).
렌더 실패해도 예외로 흐름을 죽이지 않고 최소 '데이터 제한' JSON 으로 통과시킨다(절대규칙 5·§7).
"""
from __future__ import annotations

import logging

import services.report_renderer as report_renderer
from schemas.query import Answer, QueryUnderstanding
from schemas.response import SubjectQueryResponse

logger = logging.getLogger(__name__)


def report_node(state: dict) -> dict:
    """understanding·query_response·answer → report_model·report_json 을 state 에 싣는다."""
    understanding: QueryUnderstanding = state.get("understanding") or QueryUnderstanding()
    response: SubjectQueryResponse = state.get("query_response") or SubjectQueryResponse(
        subject="", subject_found=False)
    answer: Answer = state.get("answer") or Answer(text="", data_limited=True)

    try:
        report_model = report_renderer.build_report_model(understanding, response, answer)
        state["report_model"] = report_model
        # 프론트/백엔드 계약 = JSON. datetime 등은 mode="json" 으로 직렬화 가능한 형태로 변환.
        state["report_json"] = report_model.model_dump(mode="json")
    except Exception as exc:  # 조립 실패도 흐름을 죽이지 않는다(정직한 데이터 제한 표기)
        logger.warning("report_node: 리포트 조립 실패 → 최소 데이터 제한 JSON 으로 degrade: %s", exc)
        state["report_model"] = None
        state["report_json"] = report_renderer.fallback_report_json(understanding)
    return state
