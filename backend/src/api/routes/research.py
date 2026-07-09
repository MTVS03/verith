"""research 라우트 — POST /api/research (supervisor 통합 분석 관문).

프론트는 **오직 백엔드(:8000)** 만 호출한다. 이 라우트가 자연어 query 를 받아 AI supervisor
(`/internal/supervisor/analyze`)로 전달하고, 그 통합 응답(resolution/tasks/results)을 그대로
반환한다. AI 계약/타임아웃 오류는 backend HTTP status 로 매핑한다(technical 라우트와 동일 규약).

NOTE(후속 작업): 통합 리포트의 DB 저장(report_id 발급)은 아직 없다. 서브에이전트(news/technical
등)는 각자 라우트에서 저장한다. 이 관문은 우선 "프론트 → 백엔드 단일 접속점" 을 확립하는 passthrough
이며, DB 저장 배선은 별도 브랜치에서 붙인다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from src.api.clients.ai_client import (
    AIClient,
    AITimeoutError,
    AIUnavailableError,
    AIValidationError,
)
from src.api.config import settings
from src.api.deps import get_ai_client

router = APIRouter(prefix="/api/research", tags=["research"])


class ResearchRequest(BaseModel):
    """자연어 질의 한 건. 길이 제약은 AI supervisor 계약(SupervisorAnalyzeRequest)과 맞춘다."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=300)


@router.post("")
async def analyze_research(
    req: ResearchRequest,
    ai_client: AIClient = Depends(get_ai_client),
) -> dict:
    """query → AI supervisor 전달 → 통합 응답(tasks/results) 그대로 반환.

    supervisor 는 서브에이전트 여러 개를 돌려 오래 걸리므로 전용 긴 timeout 을 준다.
    """
    try:
        return await ai_client.analyze_supervisor(
            {"query": req.query},
            timeout_seconds=settings.AI_SUPERVISOR_TIMEOUT_SECONDS,
        )
    except AIValidationError as exc:
        # AI 가 query 를 거부(422) → 클라이언트 입력 문제
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except AIUnavailableError as exc:
        # AI 사용 불가/연결 실패 = upstream 오류 → 502
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    except AITimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)
        ) from exc
