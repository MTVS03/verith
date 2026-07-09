"""industry report 영속화(repository)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.common.agent_report import AgentReport
from db.models.industry.industry_report import IndustryReport


async def add_report(session: AsyncSession, report: IndustryReport) -> None:
    """industry_reports row 추가. commit 은 호출자가 한다."""
    session.add(report)
    await session.flush()


async def get_report(session: AsyncSession, report_id: UUID) -> IndustryReport | None:
    return await session.get(IndustryReport, report_id)


async def list_reports(
    session: AsyncSession,
    *,
    client_session_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[IndustryReport]:
    stmt = select(IndustryReport)
    if client_session_id is not None:
        stmt = stmt.where(IndustryReport.client_session_id == client_session_id)
    stmt = stmt.order_by(IndustryReport.created_at.desc()).limit(limit).offset(offset)
    return list(await session.scalars(stmt))


async def delete_agent_index(session: AsyncSession, report_id: UUID) -> int:
    result = await session.execute(
        delete(AgentReport).where(
            AgentReport.agent_type == "industry",
            AgentReport.agent_report_id == report_id,
        )
    )
    return result.rowcount or 0


async def delete_root(session: AsyncSession, report_id: UUID) -> int:
    result = await session.execute(
        delete(IndustryReport).where(IndustryReport.id == report_id)
    )
    return result.rowcount or 0
