"""technical report 영속화 (repository).

순수 DB 접근만 담당한다. AI output → ORM 매핑·검증은 service 가 한다.
자식 테이블은 ON DELETE CASCADE 이므로 root 삭제만으로 함께 삭제된다.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.common.stock import Stock
from db.models.technical.report_chart import TechnicalReportChart
from db.models.technical.report_followup import TechnicalReportFollowup
from db.models.technical.report_interpretation import TechnicalReportInterpretation
from db.models.technical.report_risk_note import TechnicalReportRiskNote
from db.models.technical.report_signal import TechnicalReportSignal
from db.models.technical.report_verification import TechnicalReportVerification
from db.models.technical.technical_report import TechnicalReport


async def ensure_stock(session: AsyncSession, *, stock_code: str, stock_name: str) -> None:
    """stocks 에 종목이 없을 때만 insert(마스터 보호 — 기존 이름 덮어쓰지 않음).

    ON CONFLICT DO NOTHING 이므로 이미 있으면 stock_name 을 갱신하지 않는다.
    """
    stmt = pg_insert(Stock).values(stock_code=stock_code, stock_name=stock_name)
    stmt = stmt.on_conflict_do_nothing(index_elements=[Stock.stock_code])
    await session.execute(stmt)


async def add_report(
    session: AsyncSession,
    *,
    report: TechnicalReport,
    signals: list[TechnicalReportSignal],
    charts: list[TechnicalReportChart],
    risk_notes: list[TechnicalReportRiskNote],
    interpretation: TechnicalReportInterpretation,
    verification: TechnicalReportVerification,
) -> None:
    """root + 자식 ORM 객체 추가(같은 트랜잭션). commit 은 호출자(service)가 한다.

    관계(relationship)를 두지 않으므로 UOW 자동 정렬에 기대지 않고 **부모 먼저 flush** 해
    자식 FK 가 항상 유효하게 한다.
    """
    session.add(report)
    await session.flush()  # technical_reports 먼저 — 자식 FK 대상 확보
    session.add_all(signals)
    session.add_all(charts)
    session.add_all(risk_notes)
    session.add(interpretation)
    session.add(verification)
    await session.flush()


async def get_report(session: AsyncSession, report_id: UUID) -> TechnicalReport | None:
    """root 조회(없으면 None). read model projection 이 output_payload 를 읽는다."""
    return await session.get(TechnicalReport, report_id)


async def get_stock(session: AsyncSession, stock_code: str) -> Stock | None:
    """canonical 종목(stocks) 조회 — read model stock 블록의 정본 source(없으면 None)."""
    return await session.get(Stock, stock_code)


async def list_followups(
    session: AsyncSession, report_id: UUID
) -> list[TechnicalReportFollowup]:
    """parent report 기준 follow-up 목록 — created_at 오름차순(대화 순서). 인덱스(report_id,created_at) 활용."""
    result = await session.scalars(
        select(TechnicalReportFollowup)
        .where(TechnicalReportFollowup.report_id == report_id)
        .order_by(TechnicalReportFollowup.created_at.asc())
    )
    return list(result)


async def add_followup(session: AsyncSession, followup: TechnicalReportFollowup) -> None:
    """follow-up row 추가(같은 트랜잭션). commit 은 호출자(service)가 한다."""
    session.add(followup)
    await session.flush()


async def count_followups(session: AsyncSession, report_id: UUID) -> int:
    """report 에 연결된 follow-up 수(report detail 의 followup_count 신호용)."""
    n = await session.scalar(
        select(func.count())
        .select_from(TechnicalReportFollowup)
        .where(TechnicalReportFollowup.report_id == report_id)
    )
    return int(n or 0)


async def get_interpretation(
    session: AsyncSession, report_id: UUID
) -> TechnicalReportInterpretation | None:
    """정규화 interpretation 행 조회(model_name 등 payload 밖 backend 필드용). report_id 는 unique."""
    return await session.scalar(
        select(TechnicalReportInterpretation).where(
            TechnicalReportInterpretation.report_id == report_id
        )
    )


async def delete_root(session: AsyncSession, report_id: UUID) -> int:
    """technical_reports root 삭제(자식은 CASCADE). 삭제된 행수 반환."""
    result = await session.execute(
        delete(TechnicalReport).where(TechnicalReport.id == report_id)
    )
    return result.rowcount or 0
