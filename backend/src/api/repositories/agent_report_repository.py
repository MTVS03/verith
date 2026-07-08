"""agent_reports (공통 리포트 인덱스) repository.

agent_report_id 에는 DB FK 가 없으므로, technical 삭제 시 이 repo 로 직접 삭제한다.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.common.agent_report import AgentReport


async def count_reports(
    session: AsyncSession,
    *,
    agent_type: str | None = None,
    client_session_id: str | None = None,
    stock_code: str | None = None,
) -> int:
    """필터 기준 전체 수(archive pagination total)."""
    stmt = select(func.count()).select_from(AgentReport)
    if agent_type is not None:
        stmt = stmt.where(AgentReport.agent_type == agent_type)
    if client_session_id is not None:
        stmt = stmt.where(AgentReport.client_session_id == client_session_id)
    if stock_code is not None:
        stmt = stmt.where(AgentReport.stock_code == stock_code)
    return int(await session.scalar(stmt) or 0)


async def add(session: AsyncSession, agent_report: AgentReport) -> None:
    """agent_reports row 추가. commit 은 호출자가 한다."""
    session.add(agent_report)
    await session.flush()


async def list_reports(
    session: AsyncSession,
    *,
    agent_type: str | None = None,
    client_session_id: str | None = None,
    stock_code: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[AgentReport]:
    """필터 + 최신순(created_at DESC) 페이지 조회."""
    stmt = select(AgentReport)
    if agent_type is not None:
        stmt = stmt.where(AgentReport.agent_type == agent_type)
    if client_session_id is not None:
        stmt = stmt.where(AgentReport.client_session_id == client_session_id)
    if stock_code is not None:
        stmt = stmt.where(AgentReport.stock_code == stock_code)
    stmt = stmt.order_by(AgentReport.created_at.desc()).limit(limit).offset(offset)
    rows = await session.execute(stmt)
    return list(rows.scalars().all())


async def delete_for_technical(session: AsyncSession, report_id: UUID) -> int:
    """agent_type='technical' AND agent_report_id=report_id 인 index row 삭제."""
    result = await session.execute(
        delete(AgentReport).where(
            AgentReport.agent_type == "technical",
            AgentReport.agent_report_id == report_id,
        )
    )
    return result.rowcount or 0
