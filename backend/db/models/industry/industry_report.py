"""industry_reports — 산업/섹터 에이전트 PostgreSQL 리포트 저장 테이블.

통합 ERD placeholder 를 산업 에이전트 명세로 확장한다. **Neo4j 의 Company/Industry/Product/
Policy/Person/Chunk 는 PostgreSQL 테이블로 만들지 않는다**(그래프는 backend app 레벨에서 별도 처리).

역할 분리(통합 호환 컬럼 유지):
- `id`(uuid PK, 내부) ↔ `report_id`(외부 노출 ID, payload.reportId, UNIQUE)
- `status`(산업 lifecycle 정본: pending/processing/completed/failed) ↔ `data_status`(통합 호환/reserved)
- `payload`(research-report.v1 전체 JSON 정본) ↔ `input_payload`/`output_payload`(통합 호환/reserved)

`agent_reports.agent_report_id` 는 기존 정책대로 `industry_reports.id`(report_id 아님)를 app-level
reference 로 가리킨다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models._shared import created_at, uuid_pk


class IndustryReport(Base):
    __tablename__ = "industry_reports"

    id: Mapped[uuid.UUID] = uuid_pk()
    # 외부 노출 리포트 ID (payload.reportId) — UNIQUE.
    report_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    client_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # 사용자 질문 원문 (payload.question.text) — 산업 명세상 NOT NULL.
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # 질문 유형 (payload.question.type).
    question_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 산업 리포트 lifecycle 상태 정본: pending/processing/completed/failed.
    status: Mapped[str] = mapped_column(Text, nullable=False)
    # 통합 agent schema 호환용(reserved). 필요 시 agent_reports.data_status 로 복사 가능.
    data_status: Mapped[str | None] = mapped_column(String, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # research-report.v1 전체 JSON 정본.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # payload.schemaVersion.
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    # 실패 시 오류 메시지.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at()
    # 레코드 최종 수정 시각.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    # 통합 schema 호환용(reserved) — raw response 등.
    input_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        # 팀원 명세 3종(필수).
        Index("idx_industry_reports_created_at", text("created_at DESC")),
        Index("idx_industry_reports_question_type", "question_type"),
        Index("idx_industry_reports_payload_gin", "payload", postgresql_using="gin"),
        # 통합 패턴 정합(선택).
        Index("idx_industry_reports_request_id", "request_id"),
        Index("idx_industry_reports_trace_id", "trace_id"),
    )
