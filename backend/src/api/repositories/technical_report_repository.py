"""technical report 영속화 (repository).

순수 DB 접근만 담당한다. AI output → ORM 매핑은 service 가 한다.
자식 테이블은 ON DELETE CASCADE 이므로 root 삭제만으로 함께 삭제된다.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass
class TechnicalReportDetailRows:
    """상세 조회 결과 묶음(root + 자식들)."""

    report: TechnicalReport
    signals: list[TechnicalReportSignal]
    charts: list[TechnicalReportChart]
    risk_notes: list[TechnicalReportRiskNote]
    interpretation: TechnicalReportInterpretation | None
    verification: TechnicalReportVerification | None
    followups: list[TechnicalReportFollowup]


async def upsert_stock(session: AsyncSession, *, stock_code: str, stock_name: str) -> None:
    """stocks upsert. 있으면 stock_name·updated_at 갱신(마스터는 삭제하지 않음)."""
    stmt = pg_insert(Stock).values(stock_code=stock_code, stock_name=stock_name)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Stock.stock_code],
        set_={"stock_name": stmt.excluded.stock_name, "updated_at": func.now()},
    )
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


async def get_detail(session: AsyncSession, report_id: UUID) -> TechnicalReportDetailRows | None:
    """root + 전 자식 조회. 없으면 None."""
    report = await session.get(TechnicalReport, report_id)
    if report is None:
        return None

    async def _children(model, order_col):
        rows = await session.execute(
            select(model).where(model.report_id == report_id).order_by(order_col)
        )
        return list(rows.scalars().all())

    signals = await _children(TechnicalReportSignal, TechnicalReportSignal.display_order)
    charts = await _children(TechnicalReportChart, TechnicalReportChart.display_order)
    risk_notes = await _children(TechnicalReportRiskNote, TechnicalReportRiskNote.display_order)
    followups = await _children(TechnicalReportFollowup, TechnicalReportFollowup.created_at)

    interp = await session.execute(
        select(TechnicalReportInterpretation).where(
            TechnicalReportInterpretation.report_id == report_id
        )
    )
    verif = await session.execute(
        select(TechnicalReportVerification).where(
            TechnicalReportVerification.report_id == report_id
        )
    )
    return TechnicalReportDetailRows(
        report=report,
        signals=signals,
        charts=charts,
        risk_notes=risk_notes,
        interpretation=interp.scalar_one_or_none(),
        verification=verif.scalar_one_or_none(),
        followups=followups,
    )


async def delete_root(session: AsyncSession, report_id: UUID) -> int:
    """technical_reports root 삭제(자식은 CASCADE). 삭제된 행수 반환."""
    result = await session.execute(
        delete(TechnicalReport).where(TechnicalReport.id == report_id)
    )
    return result.rowcount or 0
