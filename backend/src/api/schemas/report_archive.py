"""공통 리포트 보관함(archive) 목록 스키마 — agent 공통 카드 view model.

프론트 "리포트 보관함" 화면이 여러 agent 리포트를 **하나의 공통 카드 리스트**로 렌더하기 위한 얇은 계약.
agent_reports(공통 인덱스)에서 projection 하며, agent 별 상세 read model 과 분리된다(raw payload 미노출).
category/tag(산업/테마 분류)는 이 계약 범위 밖 — 상단 필터는 **agent_type** 기준.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ArchiveCardStock(BaseModel):
    stock_code: str | None = None
    stock_name: str | None = None
    market: str | None = None            # canonical stocks 조인(없으면 None)


class ArchiveCard(BaseModel):
    """공통 카드 표시 필드 — 느슨/확장 가능(agent 별로 다른 값이 와도 shape 유지)."""

    title: str
    summary: str | None = None
    badge_label: str | None = None       # 예: "Conf"
    badge_value: str | None = None       # 예: "84%"
    badge_tone: str | None = None        # green | amber | red | neutral
    meta_primary: str | None = None      # 예: final_regime / directional_bias
    meta_secondary: str | None = None    # 예: 날짜 문자열


class ArchiveCardStatus(BaseModel):
    data_status: str | None = None


class ArchiveCardMeta(BaseModel):
    created_at: datetime | None = None
    as_of: datetime | None = None
    detail_url: str | None = None        # agent 상세 endpoint 경로(없으면 None)


class ArchiveItem(BaseModel):
    """보관함 카드 1건 — 공통 shape(agent_type 표시/필터 포함)."""

    report_id: UUID                      # 상세 리포트 id(agent_report_id)
    agent_type: str
    stock: ArchiveCardStock
    card: ArchiveCard
    status: ArchiveCardStatus
    meta: ArchiveCardMeta


class ArchiveListResponse(BaseModel):
    """보관함 목록 — created_at DESC. total 은 필터 기준 전체 수."""

    items: list[ArchiveItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0
