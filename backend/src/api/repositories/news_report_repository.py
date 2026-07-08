"""news_reports 영속화 (repository).

순수 DB 접근만 담당한다. ReportModel JSON → 승격 컬럼 추출·매핑은 service 가 한다.
news_reports 는 자식 테이블이 없어(report_json JSONB 단일 보관) root 하나만 다룬다.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.common.agent_report import AgentReport
from db.models.news.news_report import NewsReport


async def add_report(session: AsyncSession, report: NewsReport) -> None:
    """news_reports row 추가. commit 은 호출자(service)가 한다."""
    session.add(report)
    await session.flush()  # report_id server_default 확정(응답/인덱스 연결용)


async def get_report(session: AsyncSession, report_id: UUID) -> NewsReport | None:
    """root 조회(없으면 None). API 는 report.report_json 을 report 로 반환한다."""
    return await session.get(NewsReport, report_id)


async def delete_root(session: AsyncSession, report_id: UUID) -> int:
    """news_reports row 삭제. 삭제된 행수 반환."""
    result = await session.execute(
        delete(NewsReport).where(NewsReport.report_id == report_id)
    )
    return result.rowcount or 0


async def delete_agent_index(session: AsyncSession, report_id: UUID) -> int:
    """agent_reports 목록 인덱스(agent_type='news') 삭제. FK 없어 root 와 별도로 지운다.

    공용 agent_reports 테이블을 news 쪽에서 직접 지운다(공용 repository 는 건드리지 않음).
    """
    result = await session.execute(
        delete(AgentReport).where(
            AgentReport.agent_type == "news",
            AgentReport.agent_report_id == report_id,
        )
    )
    return result.rowcount or 0
