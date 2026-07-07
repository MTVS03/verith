"""technical report API 스키마.

응답은 api_spec §5·§6 의 wrapper 구조 `{ report_id, report }` 를 따른다. `report` 는
AI contracts.md Agent Output JSON(원본)을 그대로 담고, backend 는 report_id 만 부착한다.
정규화된 자식 테이블은 내부 SQL 조회·분석용이며 API 응답 형태를 결정하지 않는다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class TechnicalReportCreateRequest(BaseModel):
    """POST /api/technical/reports 요청. request_id 는 backend 가 생성한다(입력받지 않음)."""

    ticker: str = Field(pattern=r"^\d{6}$")  # 6자리 종목코드(앞자리 0 보존)
    query: str = Field(min_length=1)
    client_session_id: str | None = None
    # stock_name 은 종목 마스터가 우선. 요청값은 미지 종목일 때만 보조로 쓰인다(서비스에서 판단).
    stock_name: str | None = None
    as_of: datetime | None = None  # 없으면 서버가 현재시각으로 채움


class TechnicalReportEnvelope(BaseModel):
    """POST/GET 응답 wrapper — { report_id, report }.

    report 는 AI Agent Output JSON 원본(dict). GET(저장본)에서는 request_id 가 포함될 수 있다
    (물리 정본상 technical_reports.request_id 를 저장하므로 — api_spec §4.1 갱신 참고).
    """

    report_id: UUID
    report: dict[str, Any]
