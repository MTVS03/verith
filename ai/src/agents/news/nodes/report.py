# nodes/report.py — 리포트 노드(얇게). report_renderer 로 HTML 하나를 만들어 state 에 싣는다.
"""조립·렌더 로직은 services/report_renderer 에, 노드는 호출만(CLAUDE.md §2-2).

렌더 실패해도 예외로 흐름을 죽이지 않고 최소 '데이터 제한' HTML 로 통과시킨다(절대규칙 5·§7).
출력은 HTML 리포트 하나이며 ④ 답변은 그 안 '뉴스 흐름 요약' 섹션에 내장된다(별도 텍스트 출력 없음).
"""
from __future__ import annotations

import logging

import services.report_renderer as report_renderer
from schemas.query import Answer, QueryUnderstanding
from schemas.response import SubjectQueryResponse

logger = logging.getLogger(__name__)


def report_node(state: dict) -> dict:
    """understanding·query_response·answer → report_model·html 을 state 에 싣는다."""
    understanding: QueryUnderstanding = state.get("understanding") or QueryUnderstanding()
    response: SubjectQueryResponse = state.get("query_response") or SubjectQueryResponse(
        subject="", subject_found=False)
    answer: Answer = state.get("answer") or Answer(text="", data_limited=True)

    try:
        report_model = report_renderer.build_report_model(understanding, response, answer)
        html = report_renderer.render_html(report_model, answer)
        state["report_model"] = report_model
        state["html"] = html
    except Exception as exc:  # 렌더 실패도 흐름을 죽이지 않는다(정직한 데이터 제한 표기)
        logger.warning("report_node: 렌더 실패 → 최소 데이터 제한 HTML 로 degrade: %s", exc)
        state["report_model"] = None
        state["html"] = _fallback_html(understanding)
    return state


def _fallback_html(understanding: QueryUnderstanding) -> str:
    """렌더 자체가 실패했을 때의 최소 HTML(성공 위장 금지 — '데이터 제한'을 정직히 표기)."""
    subject = " · ".join(understanding.companies) if understanding.companies else "요청 종목"
    return (
        "<!DOCTYPE html><html lang=\"ko\"><head><meta charset=\"UTF-8\">"
        "<title>veriθ — 데이터 제한</title></head><body>"
        f"<h1>{subject} 뉴스 리포트</h1>"
        "<p>리포트를 생성하지 못했습니다. 데이터 제한으로 추정 없이 표기합니다.</p>"
        "</body></html>"
    )
