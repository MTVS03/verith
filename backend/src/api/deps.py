"""FastAPI 의존성 주입.

세션은 요청 스코프, AIClient/서비스는 요청마다 구성한다. 테스트는 이 provider 들을
dependency_overrides 로 교체한다(AIClient mock, 테스트 세션 등).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session
from src.api.clients.ai_client import AIClient
from src.api.config import settings
from src.api.services.stock_resolver_service import StockResolverService
from src.api.services.technical_report_service import TechnicalReportService


def get_ai_client() -> AIClient:
    return AIClient(
        base_url=settings.AI_SERVICE_URL,
        timeout_seconds=settings.AI_REQUEST_TIMEOUT_SECONDS,
    )


async def get_technical_report_service(
    session: AsyncSession = Depends(get_session),
    ai_client: AIClient = Depends(get_ai_client),
) -> AsyncGenerator[TechnicalReportService, None]:
    yield TechnicalReportService(session=session, ai_client=ai_client)


async def get_stock_resolver_service(
    session: AsyncSession = Depends(get_session),
) -> AsyncGenerator[StockResolverService, None]:
    yield StockResolverService(session=session)
