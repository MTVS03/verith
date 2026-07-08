from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from src.agents.fundamental.core.contract import FundamentalAgentInput, FundamentalResponse
from src.agents.fundamental.graph import analyze_fundamental_public
from src.api.errors import AppError, ai_timeout, internal_error


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/fundamental", tags=["fundamental-internal"])

_SERVICE_VERSION = "0.1.0"
_FUNDAMENTAL_AGENT_TIMEOUT_SECONDS = 60.0


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "fundamental-agent", "version": _SERVICE_VERSION}


@router.post("/analyze", response_model=FundamentalResponse)
async def analyze(body: FundamentalAgentInput) -> FundamentalResponse:
    try:
        return await asyncio.wait_for(
            analyze_fundamental_public(body),
            timeout=_FUNDAMENTAL_AGENT_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        raise ai_timeout(body.request_id) from None
    except AppError:
        raise
    except Exception:
        logger.warning("fundamental_analyze_failed", extra={"request_id": body.request_id})
        raise internal_error(body.request_id) from None
