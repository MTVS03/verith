"""flow report 영속화(repository)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.common.agent_report import AgentReport
from db.models.common.stock import Stock
from db.models.flow.flow_report import FlowReport
from db.models.flow.report_interpretation import FlowReportInterpretation
from db.models.flow.report_verification import FlowReportVerification


async def ensure_stock(
    session: AsyncSession, *, stock_code: str, stock_name: str | None, market: str | None
) -> None:
    """flow_reports.stock_code 는 stocks FK(NOT NULL) — 없으면 먼저 채운다(멱등)."""
    values: dict[str, object] = {"stock_code": stock_code, "stock_name": stock_name or stock_code}
    if market:
        values["market"] = market
    stmt = pg_insert(Stock).values(**values).on_conflict_do_nothing(index_elements=[Stock.stock_code])
    await session.execute(stmt)


async def add_report(
    session: AsyncSession,
    *,
    report: FlowReport,
    interpretation: FlowReportInterpretation,
    verification: FlowReportVerification,
) -> None:
    session.add(report)
    await session.flush()
    session.add(interpretation)
    session.add(verification)
    await session.flush()


async def get_report(session: AsyncSession, report_id: UUID) -> FlowReport | None:
    return await session.get(FlowReport, report_id)


async def get_interpretation(
    session: AsyncSession, report_id: UUID
) -> FlowReportInterpretation | None:
    return await session.scalar(
        select(FlowReportInterpretation).where(FlowReportInterpretation.report_id == report_id)
    )


async def get_verification(
    session: AsyncSession, report_id: UUID
) -> FlowReportVerification | None:
    return await session.scalar(
        select(FlowReportVerification).where(FlowReportVerification.report_id == report_id)
    )


async def delete_agent_index(session: AsyncSession, report_id: UUID) -> int:
    result = await session.execute(
        delete(AgentReport).where(
            AgentReport.agent_type == "flow",
            AgentReport.agent_report_id == report_id,
        )
    )
    return result.rowcount or 0


async def delete_root(session: AsyncSession, report_id: UUID) -> int:
    # interpretation·verification 은 FK CASCADE 로 함께 지워진다.
    result = await session.execute(delete(FlowReport).where(FlowReport.id == report_id))
    return result.rowcount or 0
