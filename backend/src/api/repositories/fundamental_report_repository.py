"""fundamental report 영속화(repository)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.common.agent_report import AgentReport
from db.models.common.stock import Stock
from db.models.fundamental.fundamental_report import FundamentalReport
from db.models.fundamental.report_evidence import ReportEvidence
from db.models.fundamental.report_filing_snippet import ReportFilingSnippet
from db.models.fundamental.report_insight import ReportInsight
from db.models.fundamental.report_interpretation import FundamentalReportInterpretation
from db.models.fundamental.report_ratio import ReportRatio
from db.models.fundamental.report_verification import FundamentalReportVerification


async def ensure_stock(session: AsyncSession, *, stock_code: str, stock_name: str) -> None:
    stmt = pg_insert(Stock).values(stock_code=stock_code, stock_name=stock_name)
    stmt = stmt.on_conflict_do_nothing(index_elements=[Stock.stock_code])
    await session.execute(stmt)


async def add_report(
    session: AsyncSession,
    *,
    report: FundamentalReport,
    ratios: list[ReportRatio],
    evidence: list[ReportEvidence],
    interpretation: FundamentalReportInterpretation,
    verification: FundamentalReportVerification,
    insights: list[ReportInsight],
    filing_snippets: list[ReportFilingSnippet],
) -> None:
    session.add(report)
    await session.flush()
    session.add_all(ratios)
    await session.flush()
    session.add_all(evidence)
    session.add(interpretation)
    session.add(verification)
    session.add_all(insights)
    session.add_all(filing_snippets)
    await session.flush()


async def get_report(session: AsyncSession, report_id: UUID) -> FundamentalReport | None:
    return await session.get(FundamentalReport, report_id)


async def list_reports_by_stock(
    session: AsyncSession,
    *,
    stock_code: str,
    limit: int,
    offset: int,
) -> list[FundamentalReport]:
    stmt = (
        select(FundamentalReport)
        .where(FundamentalReport.stock_code == stock_code)
        .order_by(FundamentalReport.as_of.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = await session.execute(stmt)
    return list(rows.scalars().all())


async def list_ratios(session: AsyncSession, report_id: UUID) -> list[ReportRatio]:
    rows = await session.execute(select(ReportRatio).where(ReportRatio.report_id == report_id))
    return list(rows.scalars().all())


async def list_evidence(session: AsyncSession, report_id: UUID) -> list[ReportEvidence]:
    rows = await session.execute(select(ReportEvidence).where(ReportEvidence.report_id == report_id))
    return list(rows.scalars().all())


async def get_interpretation(
    session: AsyncSession,
    report_id: UUID,
) -> FundamentalReportInterpretation | None:
    return await session.scalar(
        select(FundamentalReportInterpretation).where(
            FundamentalReportInterpretation.report_id == report_id
        )
    )


async def get_verification(
    session: AsyncSession,
    report_id: UUID,
) -> FundamentalReportVerification | None:
    return await session.scalar(
        select(FundamentalReportVerification).where(
            FundamentalReportVerification.report_id == report_id
        )
    )


async def list_insights(session: AsyncSession, report_id: UUID) -> list[ReportInsight]:
    rows = await session.execute(select(ReportInsight).where(ReportInsight.report_id == report_id))
    return list(rows.scalars().all())


async def list_filing_snippets(
    session: AsyncSession,
    report_id: UUID,
) -> list[ReportFilingSnippet]:
    rows = await session.execute(
        select(ReportFilingSnippet).where(ReportFilingSnippet.report_id == report_id)
    )
    return list(rows.scalars().all())


async def delete_agent_index(session: AsyncSession, report_id: UUID) -> int:
    result = await session.execute(
        delete(AgentReport).where(
            AgentReport.agent_type == "fundamental",
            AgentReport.agent_report_id == report_id,
        )
    )
    return result.rowcount or 0


async def delete_root(session: AsyncSession, report_id: UUID) -> int:
    result = await session.execute(
        delete(FundamentalReport).where(FundamentalReport.id == report_id)
    )
    return result.rowcount or 0
