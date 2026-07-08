"""fundamental report 저장/조회/삭제 오케스트레이션."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
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
from src.api.clients.ai_client import AIClient, AIContractError
from src.api.repositories import agent_report_repository as agent_repo
from src.api.repositories import fundamental_report_repository as fr_repo
from src.api.schemas.agent_report import AgentReportListItem
from src.api.schemas.ai_fundamental_output import FundamentalAgentOutputMirror
from src.api.schemas.fundamental_report import (
    FundamentalReportCreateRequest,
    FundamentalReportEnvelope,
    FundamentalReportListResponse,
)


def _parse_dt(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None


def _uuid(value: object) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _model_dict(obj: object, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: getattr(obj, field) for field in fields}


_REPORT_FIELDS = (
    "id",
    "request_id",
    "stock_code",
    "corp_code",
    "bsns_year",
    "years",
    "fs_div",
    "report_mode",
    "reprt_code",
    "reprt_name",
    "period_label",
    "verdict_label",
    "verdict",
    "fin_score",
    "confidence",
    "data_status",
    "risk_flags",
    "score_breakdown",
    "report_html",
    "llm_provider",
    "llm_model",
    "llm_latency_ms",
    "dart_calls",
    "trace_id",
    "as_of",
    "created_at",
    "meta",
)
_RATIO_FIELDS = (
    "id",
    "report_id",
    "ratio_name",
    "label",
    "category",
    "fiscal_year",
    "fiscal_period",
    "value",
    "unit",
    "display_value",
    "status",
    "reason",
    "formula",
    "basis",
)
_EVIDENCE_FIELDS = (
    "id",
    "report_id",
    "ratio_id",
    "metric",
    "claim",
    "rcept_no",
    "bsns_year",
    "fiscal_period",
    "sj_div",
    "account_id",
    "account_nm",
    "amount",
    "unit",
    "display_value",
    "source_url",
    "role",
    "raw",
)
_INTERPRETATION_FIELDS = (
    "id",
    "report_id",
    "interpretation",
    "interpretation_source",
    "provider",
    "model",
    "prompt_meta",
)
_VERIFICATION_FIELDS = (
    "id",
    "report_id",
    "binding_passed",
    "consistency_passed",
    "verdict_stable",
    "outcome",
    "regen_count",
    "evidence_count",
    "guard_violations",
    "flags",
)
_INSIGHT_FIELDS = ("id", "report_id", "insight_type", "source_endpoint", "rcept_no", "payload")
_SNIPPET_FIELDS = (
    "id",
    "report_id",
    "rcept_no",
    "section_name",
    "snippet",
    "rank",
    "source_hash",
    "verified",
    "meta",
)


class FundamentalReportService:
    def __init__(self, session: AsyncSession, ai_client: AIClient) -> None:
        self._session = session
        self._ai = ai_client

    async def create_report(
        self,
        req: FundamentalReportCreateRequest,
    ) -> FundamentalReportEnvelope:
        request_id = f"req-{uuid4().hex}"
        trace_id = f"trace-{uuid4().hex}"
        ai_input = {
            "request_id": request_id,
            "trace_id": trace_id,
            "ticker": req.ticker,
            "query": req.query,
        }
        raw = await self._ai.analyze_fundamental(ai_input)

        try:
            output = FundamentalAgentOutputMirror.model_validate(raw)
        except ValidationError as exc:
            raise AIContractError(f"AI 응답 계약 위반: {exc.error_count()} error(s)") from exc

        if output.ticker != req.ticker:
            raise AIContractError("AI 응답 ticker 가 요청과 불일치")
        if output.request_id != request_id:
            raise AIContractError("AI 응답 request_id 가 요청과 불일치")
        if output.meta.trace_id != trace_id:
            raise AIContractError("AI 응답 trace_id 가 요청과 불일치")

        erd_payload = output.meta.erd_payload.model_dump()
        root = erd_payload["fundamental_report"]
        report_id = _uuid(root["id"])
        now = datetime.now(UTC)
        report_as_of = _parse_dt(root.get("as_of")) or now
        stock_name = await self._resolve_stock_name(req.ticker, req.stock_name, output.corp_name)

        report = FundamentalReport(
            id=report_id,
            request_id=root.get("request_id"),
            stock_code=root.get("stock_code"),
            corp_code=root.get("corp_code"),
            bsns_year=root.get("bsns_year"),
            years=root.get("years"),
            fs_div=root.get("fs_div"),
            report_mode=root.get("report_mode"),
            reprt_code=root.get("reprt_code"),
            reprt_name=root.get("reprt_name"),
            period_label=root.get("period_label"),
            verdict_label=root.get("verdict_label"),
            verdict=root.get("verdict"),
            fin_score=root.get("fin_score"),
            confidence=root.get("confidence"),
            data_status=root.get("data_status"),
            risk_flags=root.get("risk_flags"),
            score_breakdown=root.get("score_breakdown"),
            report_html=root.get("report_html"),
            llm_provider=root.get("llm_provider"),
            llm_model=root.get("llm_model"),
            llm_latency_ms=root.get("llm_latency_ms"),
            dart_calls=root.get("dart_calls"),
            trace_id=root.get("trace_id"),
            as_of=report_as_of,
            created_at=now,
            meta=root.get("meta"),
        )
        ratios = [
            ReportRatio(
                id=_uuid(item["id"]),
                report_id=_uuid(item["report_id"]),
                ratio_name=item.get("ratio_name"),
                label=item.get("label"),
                category=item.get("category"),
                fiscal_year=item.get("fiscal_year"),
                fiscal_period=item.get("fiscal_period"),
                value=_decimal(item.get("value")),
                unit=item.get("unit"),
                display_value=item.get("display_value"),
                status=item.get("status"),
                reason=item.get("reason"),
                formula=item.get("formula"),
                basis=item.get("basis"),
            )
            for item in erd_payload["report_ratios"]
        ]
        evidence = [
            ReportEvidence(
                id=_uuid(item["id"]),
                report_id=_uuid(item["report_id"]),
                ratio_id=_uuid(item["ratio_id"]) if item.get("ratio_id") else None,
                metric=item.get("metric"),
                claim=item.get("claim"),
                rcept_no=item.get("rcept_no"),
                bsns_year=item.get("bsns_year"),
                fiscal_period=item.get("fiscal_period"),
                sj_div=item.get("sj_div"),
                account_id=item.get("account_id"),
                account_nm=item.get("account_nm"),
                amount=_decimal(item.get("amount")),
                unit=item.get("unit"),
                display_value=item.get("display_value"),
                source_url=item.get("source_url"),
                role=item.get("role"),
                raw=item.get("raw"),
            )
            for item in erd_payload["report_evidence"]
        ]
        interp_payload = erd_payload["report_interpretation"]
        interpretation = FundamentalReportInterpretation(
            id=_uuid(interp_payload["id"]),
            report_id=_uuid(interp_payload["report_id"]),
            interpretation=interp_payload.get("interpretation"),
            interpretation_source=interp_payload.get("interpretation_source"),
            provider=interp_payload.get("provider"),
            model=interp_payload.get("model"),
            prompt_meta=interp_payload.get("prompt_meta"),
        )
        verification_payload = erd_payload["report_verification"]
        verification = FundamentalReportVerification(
            id=_uuid(verification_payload["id"]),
            report_id=_uuid(verification_payload["report_id"]),
            binding_passed=verification_payload.get("binding_passed"),
            consistency_passed=verification_payload.get("consistency_passed"),
            verdict_stable=verification_payload.get("verdict_stable"),
            outcome=verification_payload.get("outcome"),
            regen_count=verification_payload.get("regen_count"),
            evidence_count=verification_payload.get("evidence_count"),
            guard_violations=verification_payload.get("guard_violations"),
            flags=verification_payload.get("flags"),
        )
        insights = [
            ReportInsight(
                id=_uuid(item["id"]),
                report_id=_uuid(item["report_id"]),
                insight_type=item.get("insight_type"),
                source_endpoint=item.get("source_endpoint"),
                rcept_no=item.get("rcept_no"),
                payload=item.get("payload"),
            )
            for item in erd_payload["report_insights"]
        ]
        snippets = [
            ReportFilingSnippet(
                id=_uuid(item["id"]),
                report_id=_uuid(item["report_id"]),
                rcept_no=item.get("rcept_no"),
                section_name=item.get("section_name"),
                snippet=item.get("snippet"),
                rank=item.get("rank"),
                source_hash=item.get("source_hash"),
                verified=item.get("verified"),
                meta=item.get("meta"),
            )
            for item in erd_payload["report_filing_snippets"]
        ]

        agent_report = AgentReport(
            id=uuid4(),
            agent_type="fundamental",
            agent_report_id=report_id,
            request_id=request_id,
            client_session_id=req.client_session_id,
            owner_user_id=None,
            owner_session_id=None,
            stock_code=req.ticker,
            stock_name=stock_name,
            question=req.query,
            answer_text=output.verdict,
            data_status=root.get("data_status"),
            trace_id=trace_id,
            as_of=report_as_of,
            created_at=now,
            summary={
                "fin_score": output.score,
                "verdict_label": output.verdict_label,
                "period_label": root.get("period_label"),
            },
        )

        await fr_repo.ensure_stock(self._session, stock_code=req.ticker, stock_name=stock_name)
        await fr_repo.add_report(
            self._session,
            report=report,
            ratios=ratios,
            evidence=evidence,
            interpretation=interpretation,
            verification=verification,
            insights=insights,
            filing_snippets=snippets,
        )
        await agent_repo.add(self._session, agent_report)
        await self._session.commit()

        return FundamentalReportEnvelope(report_id=report_id, report=raw)

    async def _resolve_stock_name(self, ticker: str, requested: str | None, ai_name: str) -> str:
        existing = await self._session.get(Stock, ticker)
        if existing is not None:
            return existing.stock_name
        req_name = requested.strip() if requested and requested.strip() else None
        return req_name or ai_name or ticker

    async def get_report(self, report_id: UUID) -> FundamentalReportEnvelope | None:
        report = await fr_repo.get_report(self._session, report_id)
        if report is None:
            return None
        detail = await self._detail_payload(report)
        return FundamentalReportEnvelope(report_id=report.id, report=detail)

    async def list_reports(
        self,
        *,
        stock_code: str,
        limit: int,
        offset: int,
    ) -> FundamentalReportListResponse:
        rows = await agent_repo.list_reports(
            self._session,
            agent_type="fundamental",
            stock_code=stock_code,
            limit=limit,
            offset=offset,
        )
        items = [AgentReportListItem.model_validate(row) for row in rows]
        return FundamentalReportListResponse(
            items=items,
            limit=limit,
            offset=offset,
            count=len(items),
        )

    async def delete_report(self, report_id: UUID) -> bool:
        await fr_repo.delete_agent_index(self._session, report_id)
        deleted = await fr_repo.delete_root(self._session, report_id)
        await self._session.commit()
        return deleted > 0

    async def _detail_payload(self, report: FundamentalReport) -> dict[str, Any]:
        ratios = await fr_repo.list_ratios(self._session, report.id)
        evidence = await fr_repo.list_evidence(self._session, report.id)
        interpretation = await fr_repo.get_interpretation(self._session, report.id)
        verification = await fr_repo.get_verification(self._session, report.id)
        insights = await fr_repo.list_insights(self._session, report.id)
        snippets = await fr_repo.list_filing_snippets(self._session, report.id)
        return {
            "fundamental_report": _model_dict(report, _REPORT_FIELDS),
            "report_ratios": [_model_dict(item, _RATIO_FIELDS) for item in ratios],
            "report_evidence": [_model_dict(item, _EVIDENCE_FIELDS) for item in evidence],
            "report_interpretation": (
                _model_dict(interpretation, _INTERPRETATION_FIELDS)
                if interpretation is not None
                else None
            ),
            "report_verification": (
                _model_dict(verification, _VERIFICATION_FIELDS)
                if verification is not None
                else None
            ),
            "report_insights": [_model_dict(item, _INSIGHT_FIELDS) for item in insights],
            "report_filing_snippets": [_model_dict(item, _SNIPPET_FIELDS) for item in snippets],
        }
