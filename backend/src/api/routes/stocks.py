"""Stock Resolver 라우트 — POST /api/stocks/resolve.

원문 query 는 로그/응답에 남기지 않는다(§7). resolved/ambiguous/not_found 는 모두 200,
입력 검증 실패는 422, DB 장애는 500/503.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from src.api.deps import get_stock_resolver_service
from src.api.schemas.stock_resolve import StockResolveRequest, StockResolveResponse
from src.api.services.stock_resolver_service import EmptyQueryError, StockResolverService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.post("/resolve", response_model=StockResolveResponse)
async def resolve_stock(
    req: StockResolveRequest,
    service: StockResolverService = Depends(get_stock_resolver_service),
) -> StockResolveResponse:
    try:
        return await service.resolve(req.query)
    except EmptyQueryError as exc:
        # 원문 query 는 메시지에 싣지 않는다.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="query normalizes to empty",
        ) from exc
    except SQLAlchemyError as exc:
        # 원문 query·상세는 로그에 남기지 않는다(길이만).
        logger.warning("stock_resolve_db_error", extra={"query_len": len(req.query)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="stock resolve temporarily unavailable",
        ) from exc
