"""technical report 저장/조회/삭제 오케스트레이션.

저장 흐름: request_id 생성 → input_payload → AI 호출 → **응답 계약 검증(미러 스키마 +
ticker/request_id 정합)** → stock_name resolve(마스터 우선) → stocks ensure → technical_reports
+ 자식 → agent_reports → commit.

검증 실패(구조/범위/중복/정합성)는 upstream AI 오류이므로 저장하지 않고 AIContractError → 502.
API 가 반환/조회하는 report 는 AI 원본(output_payload)이며, 정규화 자식 테이블은 내부용이다(D-4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.common.agent_report import AgentReport
from db.models.common.stock import Stock
from db.models.technical.report_chart import TechnicalReportChart
from db.models.technical.report_interpretation import TechnicalReportInterpretation
from db.models.technical.report_risk_note import TechnicalReportRiskNote
from db.models.technical.report_signal import TechnicalReportSignal
from db.models.technical.report_verification import TechnicalReportVerification
from db.models.technical.technical_report import TechnicalReport
from src.api.clients.ai_client import AIClient, AIContractError
from src.api.constants.stocks import allowlist_name
from src.api.repositories import agent_report_repository as agent_repo
from src.api.repositories import technical_report_repository as tr_repo
from src.api.schemas.agent_report import AgentReportListItem
from src.api.schemas.ai_technical_output import TechnicalAgentOutputMirror
from src.api.schemas.technical_report import (
    ChartItem,
    ChartsBlock,
    DataQualityBlock,
    DriversBlock,
    GenerationPathBlock,
    InterpretationBlock,
    MetaBlock,
    RiskItemBlock,
    RisksBlock,
    SignalItem,
    SignalsBlock,
    StabilityBlock,
    StockBlock,
    SummaryBlock,
    TechnicalReportCreateRequest,
    TechnicalReportReadModel,
    TraceFlagsBlock,
    TraceSummaryBlock,
    VerificationBlock,
    VerificationSummaryBlock,
)


def _parse_dt(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None


def _d(node: object) -> dict:
    """dict 이면 그대로, 아니면 빈 dict(방어적 projection — 구버전/부분 payload 안정)."""
    return node if isinstance(node, dict) else {}


def _list(node: object) -> list:
    return node if isinstance(node, list) else []


def build_read_model(
    *, report_id: UUID, raw: dict, stock: Stock | None, model_name: str | None = None
) -> TechnicalReportReadModel:
    """저장된 raw output_payload + canonical stock → 프론트 친화 read model(projection, 재해석 없음).

    모든 접근은 방어적(.get)이라 구버전/부분 payload(구조화 섹션 없음)에서도 shape 가 안정적이다.
    `stock` 블록은 **canonical stocks 우선**(없으면 payload/ticker fallback)."""
    interp = _d(raw.get("interpretation"))
    regime = _d(raw.get("regime"))
    signal = _d(raw.get("signal"))
    verification = _d(raw.get("verification"))
    ticker = str(raw.get("ticker") or (stock.stock_code if stock else "") or "")

    charts = _list(raw.get("charts"))
    chart_items: list[ChartItem] = []
    periods: list[str] = []
    candle_units: set[str] = set()
    for i, c in enumerate(charts):
        cd = _d(_d(c).get("chart_data"))
        period = str(_d(c).get("period") or "")
        unit = cd.get("candle_unit")
        if period:
            periods.append(period)
        if isinstance(unit, str):
            candle_units.add(unit)
        chart_items.append(ChartItem(
            period=period,
            candle_unit=unit,
            display_order=i,
            has_chart_data=bool(cd),
            annotation_count=len(_list(cd.get("annotations"))),
        ))

    # ── trace summary(생성/검증/품질 요약) — 모두 저장값 파생, 재해석 없음 ──
    interp_source = interp.get("source")
    template_fallback_used = interp_source == "template_fallback"
    regen = verification.get("regen_count")
    had_regeneration = bool(regen) if isinstance(regen, int) else False
    if had_regeneration and regen:
        had_regeneration = regen > 0
    if template_fallback_used:
        path_label = "template_fallback"
    elif had_regeneration or interp_source == "llm_regenerated":
        path_label = "regenerated"
    else:
        path_label = "normal"

    data_status = raw.get("data_status")
    limited = data_status in ("data_limited", "regime_unavailable")
    has_intraday = raw.get("intraday_context") is not None or "1d" in periods

    calc, rgm, lbl = (
        verification.get("calc_passed"),
        verification.get("regime_passed"),
        verification.get("label_matched"),
    )
    outcome = verification.get("outcome")
    v_consistent = bool(calc) and bool(rgm) and bool(lbl) if verification else None
    v_warning = bool(outcome and outcome != "passed") or (v_consistent is False)
    failed_count = len(_list(verification.get("failed_indicators")))

    trace_summary = TraceSummaryBlock(
        trace_id=raw.get("trace_id"),
        generation_path=GenerationPathBlock(
            source=raw.get("source"),
            interpretation_source=interp_source,
            template_fallback_used=template_fallback_used,
            regen_count=regen if isinstance(regen, int) else None,
            path_label=path_label,
        ),
        data_quality=DataQualityBlock(
            data_status=data_status,
            available_periods=periods,
            intraday_available=has_intraday,
            chart_count=len(chart_items),
            limited=limited,
        ),
        verification_summary=VerificationSummaryBlock(
            outcome=outcome,
            calc_passed=calc,
            regime_passed=rgm,
            label_matched=lbl,
            failed_indicators_count=failed_count,
        ),
        stability=StabilityBlock(
            confidence=signal.get("confidence"),
            confidence_basis=signal.get("confidence_basis"),
            verification_consistent=v_consistent,
        ),
        flags=TraceFlagsBlock(
            used_fallback=template_fallback_used,
            had_regeneration=had_regeneration,
            limited_data=limited,
            verification_warning=v_warning,
            has_intraday_context=has_intraday,
            has_daily_chart="D" in candle_units,
            has_weekly_chart="W" in candle_units,
            has_monthly_chart="M" in candle_units,
        ),
    )

    return TechnicalReportReadModel(
        report_id=report_id,
        stock=StockBlock(
            stock_code=(stock.stock_code if stock else ticker),
            stock_name=(stock.stock_name if stock else raw.get("stock_name")),
            market=(stock.market if stock else None),
        ),
        meta=MetaBlock(
            request_id=raw.get("request_id"),
            trace_id=raw.get("trace_id"),
            as_of=_parse_dt(raw.get("as_of")),
            source=raw.get("source"),
            data_status=raw.get("data_status"),
            model_name=model_name,
        ),
        summary=SummaryBlock(
            one_line_summary=interp.get("one_line_summary"),
            directional_bias=interp.get("directional_bias"),
            final_regime=regime.get("final_regime"),
            daily_regime=regime.get("daily_regime"),
            weekly_trend=regime.get("weekly_trend"),
            monthly_trend=regime.get("monthly_trend"),
            alignment_flag=regime.get("alignment_flag"),
            timeframe_alignment=interp.get("timeframe_alignment"),
        ),
        interpretation=InterpretationBlock(
            text=interp.get("text"),
            source=interp.get("source"),
            trend_interpretation=interp.get("trend_interpretation"),
            signal_interpretation=interp.get("signal_interpretation"),
            risk_interpretation=interp.get("risk_interpretation"),
            what_to_watch_next=interp.get("what_to_watch_next"),
            invalidation_or_caution=interp.get("invalidation_or_caution"),
        ),
        drivers=DriversBlock(
            key_drivers=[str(x) for x in _list(interp.get("key_drivers"))],
            warning_points=[str(x) for x in _list(interp.get("warning_points"))],
        ),
        signals=SignalsBlock(
            signal_score=signal.get("signal_score"),
            consensus=signal.get("consensus"),
            confidence=signal.get("confidence"),
            confidence_basis=signal.get("confidence_basis"),
            items=[
                SignalItem(
                    indicator=str(_d(s).get("indicator") or ""),
                    signal=_d(s).get("signal"),
                    value=_d(s).get("value"),
                    metrics=[str(m) for m in _list(_d(s).get("metrics"))],
                    detail=_d(s).get("detail"),
                    detail_source=_d(s).get("detail_source"),
                )
                for s in _list(raw.get("technical_signals"))
            ],
        ),
        risks=RisksBlock(
            items=[
                RiskItemBlock(
                    flag=str(_d(r).get("flag") or ""),
                    note=_d(r).get("note"),
                    ref_price=_d(r).get("ref_price"),
                )
                for r in _list(_d(raw.get("risk")).get("items"))
            ],
        ),
        charts=ChartsBlock(available_periods=periods, items=chart_items),
        verification=VerificationBlock(
            outcome=verification.get("outcome"),
            calc_passed=verification.get("calc_passed"),
            regime_passed=verification.get("regime_passed"),
            label_matched=verification.get("label_matched"),
            regen_count=verification.get("regen_count"),
            failed_indicators=[str(x) for x in _list(verification.get("failed_indicators"))],
            summary=None,
        ),
        trace_summary=trace_summary,
    )


class TechnicalReportService:
    def __init__(self, session: AsyncSession, ai_client: AIClient) -> None:
        self._session = session
        self._ai = ai_client

    # ── 저장 ──────────────────────────────────────────────────────────────────
    async def create_report(
        self, req: TechnicalReportCreateRequest
    ) -> TechnicalReportReadModel:
        request_id = f"req-{uuid4().hex}"
        as_of = req.as_of or datetime.now(UTC)
        ai_input = {
            "ticker": req.ticker,
            "query": req.query,
            "request_id": request_id,
            "as_of": as_of.isoformat(),
        }

        raw = await self._ai.analyze_technical(ai_input)  # 전송 예외는 route 가 매핑

        # 1) 계약 검증(구조/범위/indicator 중복) — 위반 시 저장 안 함.
        try:
            output = TechnicalAgentOutputMirror.model_validate(raw)
        except ValidationError as exc:
            raise AIContractError(f"AI 응답 계약 위반: {exc.error_count()} error(s)") from exc

        # 2) 요청 ↔ 응답 정합(ticker/request_id 불일치 = upstream 오류).
        if output.ticker != req.ticker:
            raise AIContractError("AI 응답 ticker 가 요청과 불일치")
        if output.request_id != request_id:
            raise AIContractError("AI 응답 request_id 가 요청과 불일치")

        report_id = uuid4()
        now = datetime.now(UTC)
        report_as_of = _parse_dt(raw.get("as_of")) or as_of

        stock_name = await self._resolve_stock_name(req.ticker, req.stock_name)

        report = TechnicalReport(
            id=report_id,
            request_id=request_id,
            client_session_id=req.client_session_id,
            ticker=req.ticker,  # 신뢰값(요청) 사용 — 검증에서 응답과 일치 확인됨
            stock_code=req.ticker,
            stock_name=stock_name,
            original_query=req.query,
            normalized_query=None,
            analysis_focus=None,
            final_regime=output.regime.final_regime,
            daily_regime=output.regime.daily_regime,
            weekly_trend=output.regime.weekly_trend,
            monthly_trend=output.regime.monthly_trend,
            alignment_flag=output.regime.alignment_flag,
            regime_context=output.regime.regime_context,
            consensus=(output.signal.consensus if output.signal else None),
            signal_score=(output.signal.signal_score if output.signal else None),
            confidence=(output.signal.confidence if output.signal else None),
            confidence_basis=(output.signal.confidence_basis if output.signal else None),
            data_status=output.data_status,
            source=output.source,
            trace_id=output.trace_id,
            model_name=None,
            as_of=report_as_of,
            created_at=now,
            input_payload=ai_input,
            output_payload=raw,  # AI 원본 그대로 보존(= API 가 반환할 report)
        )

        # indicator 는 검증에서 유일성 보장됨 → 그대로 저장(임의 dedup 없음).
        signals = [
            TechnicalReportSignal(
                id=uuid4(),
                report_id=report_id,
                indicator=s.indicator,
                timeframe=None,
                signal=s.signal,
                value=s.value,
                value_unit=None,
                metrics=s.metrics,
                detail=s.detail,
                detail_source=s.detail_source,
                weight=s.weight,
                display_order=i,
            )
            for i, s in enumerate(output.technical_signals)
        ]

        charts = [
            TechnicalReportChart(
                id=uuid4(),
                report_id=report_id,
                period=c.period,
                candle_unit=(c.chart_data.get("candle_unit") if isinstance(c.chart_data, dict) else None),
                chart_data=c.chart_data,
                annotations=None,
                chart_payload=None,
                display_order=i,
            )
            for i, c in enumerate(output.charts)
        ]

        risk_items = output.risk.items if output.risk else []
        risk_notes = [
            TechnicalReportRiskNote(
                id=uuid4(),
                report_id=report_id,
                flag=r.flag,
                severity=None,
                note=r.note,
                ref_price=r.ref_price,
                note_metadata=None,
                display_order=i,
            )
            for i, r in enumerate(risk_items)
        ]

        interpretation = TechnicalReportInterpretation(
            id=uuid4(),
            report_id=report_id,
            interpretation=output.interpretation.text,
            interpretation_source=output.interpretation.source,
            model_name=None,
            template_fallback_used=(output.interpretation.source == "template_fallback"),
            detail_source_count=None,
            # AI 구조화 섹션(additive)을 JSONB 로 보존 — 구버전 output 이면 None.
            sections=output.interpretation.sections_dict(),
        )
        verification = TechnicalReportVerification(
            id=uuid4(),
            report_id=report_id,
            calc_passed=output.verification.calc_passed,
            regime_passed=output.verification.regime_passed,
            label_matched=output.verification.label_matched,
            outcome=output.verification.outcome,
            regen_count=output.verification.regen_count,
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
            stock_code=req.ticker,
            stock_name=stock_name,
            question=req.query,
            answer_text=output.interpretation.text,
            data_status=output.data_status,
            trace_id=output.trace_id,
            as_of=report_as_of,
            created_at=now,
            summary={
                "final_regime": output.regime.final_regime,
                "daily_regime": output.regime.daily_regime,
                "alignment_flag": output.regime.alignment_flag,
                "signal_score": (output.signal.signal_score if output.signal else None),
                "confidence": (output.signal.confidence if output.signal else None),
            },
        )

        # 트랜잭션: stocks 먼저(agent_reports FK) → report+자식 → agent index → commit.
        await tr_repo.ensure_stock(
            self._session, stock_code=req.ticker, stock_name=stock_name
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

        # 저장 직후 응답 == GET 단건 응답이 되도록 **동일 경로**로 조립한다(canonical stock·model_name 소스 일치).
        stock = await tr_repo.get_stock(self._session, req.ticker)
        return build_read_model(
            report_id=report_id, raw=raw, stock=stock, model_name=interpretation.model_name
        )

    async def _resolve_stock_name(self, ticker: str, requested: str | None) -> str:
        """마스터 우선: 기존 stocks > allowlist > 요청값(미지 종목) > ticker."""
        existing = await self._session.get(Stock, ticker)
        if existing is not None:
            return existing.stock_name
        req_name = requested.strip() if requested and requested.strip() else None
        return allowlist_name(ticker) or req_name or ticker

    # ── 조회 ──────────────────────────────────────────────────────────────────
    async def get_report(self, report_id: UUID) -> TechnicalReportReadModel | None:
        report = await tr_repo.get_report(self._session, report_id)
        if report is None:
            return None
        stock = await tr_repo.get_stock(self._session, report.stock_code)
        interp = await tr_repo.get_interpretation(self._session, report_id)
        return build_read_model(
            report_id=report.id,
            raw=report.output_payload,
            stock=stock,
            model_name=(interp.model_name if interp else None),
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
