from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

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
