"""news report API 스키마.

뉴스 질의 결과 리포트(ai `ReportModel`)를 backend 가 받아 저장/조회한다. technical 과 달리
backend 는 AI 를 호출하지 않는다 — 이미 완성된 리포트 JSON 을 받아 그대로 보관하고,
검색 편의를 위해 answer_text·evidence 만 승격 컬럼으로 복사한다(재해석 금지, handoff §5.3).

응답 wrapper 는 technical 과 동일하게 `{ report_id, report }` 구조를 따른다.
`report` 는 ai `ReportModel` JSON 원본(dict)이며 backend 는 report_id 만 부착한다.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class NewsReportCreateRequest(BaseModel):
    """POST /news/reports 요청.

    report 는 ai `ReportModel.model_dump(mode="json")` 원본이다. question/intent 는
    ReportModel 에 담기지 않으므로(리포트는 subject 만 가짐) 상위 계층이 별도로 넘긴다.
    없으면 null 로 저장한다(둘 다 nullable).
    """

    report: dict[str, Any] = Field(description="ai ReportModel JSON 원본")
    question: str | None = None  # 사용자 질문 원문 (ReportModel 에 없음 → 별도 수신)
    intent: str | None = None  # query understanding intent (ReportModel 에 없음)
    client_session_id: str | None = None


class NewsReportEnvelope(BaseModel):
    """POST/GET 응답 wrapper — { report_id, report }.

    report 는 저장된 ai ReportModel JSON 원본(dict). frontend 는 이 JSON 을 받아 렌더한다.
    """

    report_id: UUID
    report: dict[str, Any]
