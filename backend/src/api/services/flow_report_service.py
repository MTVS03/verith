"""flow report 저장/조회/삭제 오케스트레이션 — save-only.

news·fundamental save-only 와 같은 방식: supervisor 가 만든 flow payload(storage-spec v1)를
받아 flow 3테이블(root/interpretation/verification) + agent_reports 인덱스로 매핑·저장한다.
AI 를 다시 호출하지 않는다. 저장 시 승격 컬럼(ticker·stock_name·market·base_date·alignment)은
payload 에서 뽑아 채운다(storage-spec §3-3, 두 소스 금지). report_id 는 AI 발급 uuid4 를 PK 로
그대로 관통한다(§3-5, 확인 A).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.common.agent_report import AgentReport
from db.models.flow.flow_report import FlowReport
from db.models.flow.report_interpretation import FlowReportInterpretation
from db.models.flow.report_verification import FlowReportVerification
from src.api.repositories import agent_report_repository as agent_repo
from src.api.repositories import flow_report_repository as flow_repo
from src.api.schemas.agent_report import AgentReportListItem
from src.api.schemas.flow_report import (
    FlowReportEnvelope,
    FlowReportListResponse,
    FlowReportSaveRequest,
)


class FlowPayloadError(ValueError):
    """flow payload 가 저장 계약(필수 report_id·ticker)을 위반."""


def _parse_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


class FlowReportService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── 저장 ──────────────────────────────────────────────────────────────────
    async def save_report(self, req: FlowReportSaveRequest) -> FlowReportEnvelope:
        payload = req.payload
        raw_id = payload.get("report_id")
        if not raw_id:
            raise FlowPayloadError("flow payload 에 report_id 가 없습니다.")
        try:
            report_id = UUID(str(raw_id))
        except ValueError as exc:
            raise FlowPayloadError("flow payload report_id 형식 오류") from exc

        meta = payload.get("meta") or {}
        signals = payload.get("signals") or {}
        verification = payload.get("verification") or {}
        interp_meta = payload.get("interpretation_meta") or {}
        ticker = meta.get("ticker")
        if not ticker:
            # flow_reports.stock_code 는 stocks FK(NOT NULL) — ticker 없으면 저장 불가.
            raise FlowPayloadError("flow payload meta.ticker 가 없습니다(저장 필수).")

        stock_name = meta.get("stock_name")
        market = meta.get("market")
        base_date = _parse_date(meta.get("base_date"))
        now = datetime.now(UTC)

        def gate(name: str) -> dict[str, Any] | None:
            g = verification.get(name)
            return g if isinstance(g, dict) else None

        def gate_passed(name: str) -> bool | None:
            g = gate(name)
            return g.get("passed") if g else None

        report = FlowReport(
            id=report_id,
            ticker=ticker,
            stock_code=ticker,  # handoff §4.1 — stock_code = meta.ticker
            stock_name=stock_name,
            market=market,
            base_date=base_date,
            alignment=signals.get("alignment"),
            data_status=payload.get("data_status"),
            trace_id=payload.get("trace_id"),
            signals=signals,
            created_at=now,
        )
        interpretation = FlowReportInterpretation(
            id=uuid4(),
            report_id=report_id,
            interpretation=payload.get("interpretation"),
            interpretation_source=interp_meta.get("source"),
            provider=interp_meta.get("provider"),
            model=interp_meta.get("model"),
        )
        verification_row = FlowReportVerification(
            id=uuid4(),
            report_id=report_id,
            gate1_passed=gate_passed("gate1"),
            gate2_passed=gate_passed("gate2"),
            gate3_passed=gate_passed("gate3"),
            # checks: 3게이트 전문(passed/checks/failures) — 조회 시 verification 재구성용.
            checks={"gate1": gate("gate1"), "gate2": gate("gate2"), "gate3": gate("gate3")},
            outcome=verification.get("outcome"),
            regen_count=verification.get("regen_count"),
        )

        agent_report = AgentReport(
            id=uuid4(),
            agent_type="flow",
            agent_report_id=report_id,
            request_id=None,
            client_session_id=req.client_session_id,
            owner_user_id=None,
            owner_session_id=None,
            stock_code=ticker,
            stock_name=stock_name,
            question=req.question,
            answer_text=payload.get("interpretation"),
            data_status=payload.get("data_status"),
            trace_id=payload.get("trace_id"),
            as_of=now,
            created_at=now,
            summary={
                "alignment": signals.get("alignment"),
                "outcome": verification.get("outcome"),
                "base_date": meta.get("base_date"),
            },
        )

        await flow_repo.ensure_stock(
            self._session, stock_code=ticker, stock_name=stock_name, market=market
        )
        await flow_repo.add_report(
            self._session,
            report=report,
            interpretation=interpretation,
            verification=verification_row,
        )
        await agent_repo.add(self._session, agent_report)
        await self._session.commit()

        return FlowReportEnvelope(report_id=report_id, report=payload)

    # ── 조회 ──────────────────────────────────────────────────────────────────
    async def get_report(self, report_id: UUID) -> FlowReportEnvelope | None:
        report = await flow_repo.get_report(self._session, report_id)
        if report is None:
            return None
        interp = await flow_repo.get_interpretation(self._session, report_id)
        verif = await flow_repo.get_verification(self._session, report_id)
        payload = self._reconstruct_payload(report, interp, verif)
        return FlowReportEnvelope(report_id=report.id, report=payload)

    async def list_reports(
        self, *, stock_code: str | None, limit: int, offset: int
    ) -> FlowReportListResponse:
        rows = await agent_repo.list_reports(
            self._session, agent_type="flow", stock_code=stock_code, limit=limit, offset=offset
        )
        items = [AgentReportListItem.model_validate(row) for row in rows]
        return FlowReportListResponse(items=items, limit=limit, offset=offset, count=len(items))

    # ── 삭제 ──────────────────────────────────────────────────────────────────
    async def delete_report(self, report_id: UUID) -> bool:
        await flow_repo.delete_agent_index(self._session, report_id)
        deleted = await flow_repo.delete_root(self._session, report_id)
        await self._session.commit()
        return deleted > 0

    async def delete_all_reports(self) -> int:
        """flow 리포트 전체 삭제(index 먼저, root 는 자식 CASCADE). 삭제 행수 반환."""
        await agent_repo.delete_all_for_type(self._session, "flow")
        result = await self._session.execute(delete(FlowReport))
        deleted = result.rowcount or 0
        await self._session.commit()
        return deleted

    # ── payload 재구성(저장 시 3테이블로 분해한 것을 다시 payload 형태로) ───────
    @staticmethod
    def _reconstruct_payload(
        report: FlowReport,
        interp: FlowReportInterpretation | None,
        verif: FlowReportVerification | None,
    ) -> dict[str, Any]:
        checks = (verif.checks if verif else None) or {}
        verification: dict[str, Any] | None = None
        if verif is not None:
            verification = {
                "gate1": checks.get("gate1"),
                "gate2": checks.get("gate2"),
                "gate3": checks.get("gate3"),
                "outcome": verif.outcome,
                "regen_count": verif.regen_count,
            }
        interpretation_meta: dict[str, Any] | None = None
        if interp is not None:
            interpretation_meta = {
                "source": interp.interpretation_source,
                "provider": interp.provider,
                "model": interp.model,
            }
        return {
            "version": 1,
            "report_id": str(report.id),
            "trace_id": report.trace_id,
            "data_status": report.data_status,
            "meta": {
                "stock_name": report.stock_name,
                "ticker": report.ticker,
                "market": report.market,
                "base_date": report.base_date.isoformat() if report.base_date else None,
            },
            "signals": report.signals,
            "verification": verification,
            "interpretation": interp.interpretation if interp else None,
            "interpretation_meta": interpretation_meta,
        }
