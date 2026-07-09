"""industry report 저장/조회/삭제 오케스트레이션."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.common.agent_report import AgentReport
from db.models.industry.industry_report import IndustryReport
from src.api.clients.ai_client import AIClient, AIContractError
from src.api.repositories import agent_report_repository as agent_repo
from src.api.repositories import industry_report_repository as ir_repo
from src.api.schemas.agent_report import AgentReportListItem
from src.api.schemas.industry_report import (
    IndustryReportCreateRequest,
    IndustryReportEnvelope,
    IndustryReportListResponse,
)


def _parse_dt(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None


def _d(node: object) -> dict:
    return node if isinstance(node, dict) else {}


def _require_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AIContractError(f"AI 응답 계약 위반: {key} 누락")
    return value


def _validate_payload(raw: dict[str, Any]) -> None:
    if not isinstance(raw, dict):
        raise AIContractError("AI 응답 계약 위반: object 아님")
    if _require_str(raw, "schemaVersion") != "research-report.v1":
        raise AIContractError("AI 응답 schemaVersion 이 research-report.v1 이 아님")
    _require_str(raw, "reportId")
    question = _d(raw.get("question"))
    answer = _d(raw.get("answer"))
    if not isinstance(question.get("text"), str) or not question["text"].strip():
        raise AIContractError("AI 응답 question.text 누락")
    if not isinstance(answer.get("body"), str) or not answer["body"].strip():
        raise AIContractError("AI 응답 answer.body 누락")


def _answer_text(raw: dict[str, Any]) -> str:
    return str(_d(raw.get("answer")).get("body") or "")


def _headline(raw: dict[str, Any]) -> str | None:
    value = _d(raw.get("answer")).get("headline")
    return str(value) if value is not None else None


class IndustryReportService:
    def __init__(self, session: AsyncSession, ai_client: AIClient) -> None:
        self._session = session
        self._ai = ai_client

    async def create_report(self, req: IndustryReportCreateRequest) -> IndustryReportEnvelope:
        request_id = f"req-{uuid4().hex}"
        trace_id = f"trace-{uuid4().hex}"
        ai_input = {
            "question": req.question,
            "request_id": request_id,
            "trace_id": trace_id,
        }
        raw = await self._ai.analyze_industry(ai_input)
        _validate_payload(raw)

        report_id = uuid4()
        now = datetime.now(UTC)
        question = _d(raw.get("question"))
        answer = _d(raw.get("answer"))
        metrics = _d(raw.get("metrics"))
        faithfulness = _d(answer.get("faithfulness"))
        report_as_of = _parse_dt(raw.get("createdAt")) or now

        report = IndustryReport(
            id=report_id,
            report_id=str(raw["reportId"]),
            request_id=request_id,
            client_session_id=req.client_session_id,
            question=str(question["text"]),
            question_type=(
                str(question.get("type")) if question.get("type") is not None else None
            ),
            answer_text=_answer_text(raw),
            status="completed",
            data_status="completed",
            trace_id=trace_id,
            payload=raw,
            schema_version=str(raw["schemaVersion"]),
            error_message=None,
            as_of=report_as_of,
            created_at=now,
            input_payload=ai_input,
            output_payload=raw,
        )

        agent_report = AgentReport(
            id=uuid4(),
            agent_type="industry",
            agent_report_id=report_id,
            request_id=request_id,
            client_session_id=req.client_session_id,
            owner_user_id=None,
            owner_session_id=None,
            stock_code=None,
            stock_name=None,
            question=str(question["text"]),
            answer_text=_answer_text(raw),
            data_status="completed",
            trace_id=trace_id,
            as_of=report_as_of,
            created_at=now,
            summary={
                "headline": _headline(raw),
                "question_type": question.get("type"),
                "faithfulness_status": faithfulness.get("status"),
                "metrics": metrics,
            },
        )

        await ir_repo.add_report(self._session, report)
        await agent_repo.add(self._session, agent_report)
        await self._session.commit()
        return IndustryReportEnvelope(report_id=report_id, report=raw)

    async def get_report(self, report_id: UUID) -> IndustryReportEnvelope | None:
        report = await ir_repo.get_report(self._session, report_id)
        if report is None:
            return None
        return IndustryReportEnvelope(report_id=report.id, report=report.payload)

    async def get_report_html(self, report_id: UUID) -> str | None:
        """저장된 payload → AI 렌더 → 완결 HTML(text). 없으면 None(→404).

        payload 손상 시 AI 가 422 → AIValidationError 를 그대로 올린다(라우트가 422).
        """
        report = await ir_repo.get_report(self._session, report_id)
        if report is None:
            return None
        return await self._ai.render_industry_html(report.payload)

    async def list_reports(
        self,
        *,
        client_session_id: str | None,
        limit: int,
        offset: int,
    ) -> IndustryReportListResponse:
        rows = await agent_repo.list_reports(
            self._session,
            agent_type="industry",
            client_session_id=client_session_id,
            limit=limit,
            offset=offset,
        )
        return IndustryReportListResponse(
            items=[AgentReportListItem.model_validate(row) for row in rows],
            limit=limit,
            offset=offset,
            count=len(rows),
        )

    async def delete_report(self, report_id: UUID) -> bool:
        await ir_repo.delete_agent_index(self._session, report_id)
        deleted = await ir_repo.delete_root(self._session, report_id)
        await self._session.commit()
        return deleted > 0

    async def delete_all_reports(self) -> int:
        """industry 리포트 전체 삭제(index 먼저, root 는 자식 CASCADE). 삭제 행수 반환."""
        await agent_repo.delete_all_for_type(self._session, "industry")
        result = await self._session.execute(delete(IndustryReport))
        deleted = result.rowcount or 0
        await self._session.commit()
        return deleted
