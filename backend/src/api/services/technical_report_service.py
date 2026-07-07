"""technical report 저장/조회/삭제 오케스트레이션.

저장 흐름: request_id 생성 → input_payload → AI 호출 → output_payload 보존 →
stock_name resolve → stocks upsert → technical_reports + 자식 → agent_reports → commit.

AI output → DB 매핑 규칙(D-4): output 에 없는 nullable 컬럼은 NULL, NOT NULL 컬럼은 계약값
또는 안전한 기본값. AI response/backend payload 전체는 output_payload/input_payload 로 보존.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.common.agent_report import AgentReport
from db.models.technical.report_chart import TechnicalReportChart
from db.models.technical.report_interpretation import TechnicalReportInterpretation
from db.models.technical.report_risk_note import TechnicalReportRiskNote
from db.models.technical.report_signal import TechnicalReportSignal
from db.models.technical.report_verification import TechnicalReportVerification
from db.models.technical.technical_report import TechnicalReport
from src.api.clients.ai_client import AIClient
from src.api.constants.stocks import resolve_stock_name
from src.api.repositories import agent_report_repository as agent_repo
from src.api.repositories import technical_report_repository as tr_repo
from src.api.schemas.agent_report import AgentReportListItem
from src.api.schemas.technical_report import (
    ChartItem,
    FollowupItem,
    InterpretationItem,
    RiskNoteItem,
    SignalItem,
    TechnicalReportCreateRequest,
    TechnicalReportDetail,
    TechnicalReportSummary,
    VerificationItem,
)

_ROOT_ONLY_FIELDS = set(TechnicalReportDetail.model_fields) - {
    "signals",
    "charts",
    "risk_notes",
    "interpretation",
    "verification",
    "followups",
}


def _parse_dt(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None


class TechnicalReportService:
    def __init__(self, session: AsyncSession, ai_client: AIClient) -> None:
        self._session = session
        self._ai = ai_client

    # ── 저장 ──────────────────────────────────────────────────────────────────
    async def create_report(
        self, req: TechnicalReportCreateRequest
    ) -> TechnicalReportSummary:
        request_id = f"req-{uuid4().hex}"
        as_of = req.as_of or datetime.now(UTC)
        ai_input = {
            "ticker": req.ticker,
            "query": req.query,
            "request_id": request_id,
            "as_of": as_of.isoformat(),
        }

        output = await self._ai.analyze_technical(ai_input)  # 도메인 예외는 route 가 매핑

        stock_name = resolve_stock_name(req.ticker, req.stock_name)
        report_id = uuid4()
        now = datetime.now(UTC)
        report_as_of = _parse_dt(output.get("as_of")) or as_of

        regime = output["regime"]
        sig = output.get("signal")  # dict | None
        interp = output["interpretation"]
        verif = output["verification"]

        report = TechnicalReport(
            id=report_id,
            request_id=request_id,
            client_session_id=req.client_session_id,
            ticker=output["ticker"],
            stock_name=stock_name,
            original_query=req.query,
            normalized_query=None,
            analysis_focus=None,
            final_regime=regime["final_regime"],
            daily_regime=regime["daily_regime"],
            weekly_trend=regime.get("weekly_trend"),
            monthly_trend=regime.get("monthly_trend"),
            alignment_flag=regime["alignment_flag"],
            regime_context=regime.get("regime_context"),
            consensus=(sig["consensus"] if sig else None),
            signal_score=(sig["signal_score"] if sig else None),
            confidence=(sig["confidence"] if sig else None),
            confidence_basis=(sig["confidence_basis"] if sig else None),
            data_status=output["data_status"],
            source=output["source"],
            trace_id=output["trace_id"],
            model_name=None,
            as_of=report_as_of,
            created_at=now,
            input_payload=ai_input,
            output_payload=output,
        )

        signals: list[TechnicalReportSignal] = []
        seen: set[str] = set()
        for s in output.get("technical_signals", []):
            indicator = s["indicator"]
            if indicator in seen:  # UNIQUE(report_id, indicator) 보호 — 대표 1개만
                continue
            seen.add(indicator)
            signals.append(
                TechnicalReportSignal(
                    id=uuid4(),
                    report_id=report_id,
                    indicator=indicator,
                    timeframe=None,
                    signal=s["signal"],
                    value=s.get("value"),
                    value_unit=None,
                    metrics=s.get("metrics"),
                    detail=s.get("detail"),
                    detail_source=s.get("detail_source"),
                    weight=s["weight"],
                    display_order=len(signals),
                )
            )

        charts: list[TechnicalReportChart] = []
        for i, c in enumerate(output.get("charts", [])):
            chart_data = c.get("chart_data") or {}
            candle_unit = chart_data.get("candle_unit") if isinstance(chart_data, dict) else None
            charts.append(
                TechnicalReportChart(
                    id=uuid4(),
                    report_id=report_id,
                    period=c["period"],
                    candle_unit=candle_unit,
                    chart_data=chart_data,
                    annotations=None,
                    chart_payload=None,
                    display_order=i,
                )
            )

        risk_notes: list[TechnicalReportRiskNote] = []
        risk = output.get("risk")
        risk_items = (risk or {}).get("items", []) if risk else []
        for i, r in enumerate(risk_items):
            risk_notes.append(
                TechnicalReportRiskNote(
                    id=uuid4(),
                    report_id=report_id,
                    flag=r.get("flag"),
                    severity=None,
                    note=r.get("note"),
                    ref_price=r.get("ref_price"),
                    note_metadata=None,
                    display_order=i,
                )
            )

        interpretation = TechnicalReportInterpretation(
            id=uuid4(),
            report_id=report_id,
            interpretation=interp["text"],
            interpretation_source=interp["source"],
            model_name=None,
            template_fallback_used=(interp["source"] == "template_fallback"),
            detail_source_count=None,
            sections=None,
        )
        verification = TechnicalReportVerification(
            id=uuid4(),
            report_id=report_id,
            calc_passed=verif["calc_passed"],
            regime_passed=verif["regime_passed"],
            label_matched=verif["label_matched"],
            outcome=verif["outcome"],
            regen_count=verif.get("regen_count") or 0,
            failed_indicators=None,
            validation_summary=None,
        )

        agent_report = AgentReport(
            id=uuid4(),
            agent_type="technical",
            agent_report_id=report_id,
            request_id=request_id,
            client_session_id=req.client_session_id,
            owner_user_id=None,
            owner_session_id=None,
            stock_code=output["ticker"],
            stock_name=stock_name,
            question=req.query,
            answer_text=interp["text"],
            data_status=output["data_status"],
            trace_id=output["trace_id"],
            as_of=report_as_of,
            created_at=now,
            summary={
                "final_regime": regime["final_regime"],
                "daily_regime": regime["daily_regime"],
                "alignment_flag": regime["alignment_flag"],
                "signal_score": (sig["signal_score"] if sig else None),
                "confidence": (sig["confidence"] if sig else None),
            },
        )

        # 트랜잭션: stocks 먼저(agent_reports FK) → report+자식 → agent index → commit.
        await tr_repo.upsert_stock(
            self._session, stock_code=output["ticker"], stock_name=stock_name
        )
        await tr_repo.add_report(
            self._session,
            report=report,
            signals=signals,
            charts=charts,
            risk_notes=risk_notes,
            interpretation=interpretation,
            verification=verification,
        )
        await agent_repo.add(self._session, agent_report)
        await self._session.commit()

        return TechnicalReportSummary(
            report_id=report_id,
            request_id=request_id,
            agent_type="technical",
            ticker=report.ticker,
            stock_name=stock_name,
            data_status=report.data_status,
            created_at=now,
        )

    # ── 조회 ──────────────────────────────────────────────────────────────────
    async def get_report_detail(self, report_id: UUID) -> TechnicalReportDetail | None:
        rows = await tr_repo.get_detail(self._session, report_id)
        if rows is None:
            return None
        root = {f: getattr(rows.report, f) for f in _ROOT_ONLY_FIELDS}
        return TechnicalReportDetail(
            **root,
            signals=[SignalItem.model_validate(s) for s in rows.signals],
            charts=[ChartItem.model_validate(c) for c in rows.charts],
            risk_notes=[RiskNoteItem.model_validate(r) for r in rows.risk_notes],
            interpretation=(
                InterpretationItem.model_validate(rows.interpretation)
                if rows.interpretation
                else None
            ),
            verification=(
                VerificationItem.model_validate(rows.verification)
                if rows.verification
                else None
            ),
            followups=[FollowupItem.model_validate(f) for f in rows.followups],
        )

    async def list_reports(
        self,
        *,
        agent_type: str | None,
        client_session_id: str | None,
        stock_code: str | None,
        limit: int,
        offset: int,
    ) -> list[AgentReportListItem]:
        rows = await agent_repo.list_reports(
            self._session,
            agent_type=agent_type,
            client_session_id=client_session_id,
            stock_code=stock_code,
            limit=limit,
            offset=offset,
        )
        return [AgentReportListItem.model_validate(r) for r in rows]

    # ── 삭제 ──────────────────────────────────────────────────────────────────
    async def delete_report(self, report_id: UUID) -> bool:
        # 1) agent_reports index(FK 없음) 먼저, 2) technical_reports root(자식 CASCADE).
        await agent_repo.delete_for_technical(self._session, report_id)
        deleted = await tr_repo.delete_root(self._session, report_id)
        await self._session.commit()
        return deleted > 0
