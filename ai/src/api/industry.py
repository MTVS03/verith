from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Body, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from src.agents.industry.make_report import ReportPayloadError, render_report_html
from src.agents.industry.report_export import export_question
from src.api.errors import AppError, ai_timeout, internal_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/industry", tags=["industry-internal"])

_SERVICE_VERSION = "0.1.0"
_INDUSTRY_AGENT_TIMEOUT_SECONDS = 60.0


class IndustryAnalyzeRequest(BaseModel):
    """Industry GraphRAG internal request."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    request_id: str | None = None
    trace_id: str | None = None


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "industry-agent", "version": _SERVICE_VERSION}


@router.post("/render")
async def render(payload: dict = Body(...)) -> Response:
    """research-report.v1 payload → 완결 HTML 문서(iframe 렌더용).

    payload 검증 실패(ReportPayloadError)는 422로 명확히 반환한다 —
    프론트가 빈 iframe 대신 오류를 표시할 수 있어야 한다(handoff §5).
    """
    try:
        html = await run_in_threadpool(lambda: render_report_html(payload))
    except ReportPayloadError as exc:
        raise HTTPException(status_code=422, detail=f"invalid report payload: {exc}") from None
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.post("/analyze")
async def analyze(body: IndustryAnalyzeRequest) -> dict:
    try:
        return await asyncio.wait_for(
            run_in_threadpool(
                lambda: export_question(body.question, report_id=body.request_id)
            ),
            timeout=_INDUSTRY_AGENT_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        raise ai_timeout(body.request_id) from None
    except AppError:
        raise
    except Exception:
        logger.warning("industry_analyze_failed", extra={"request_id": body.request_id})
        raise internal_error(body.request_id) from None
