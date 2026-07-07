"""news 저장 API 스키마 (ai 계약 미러).

ai(news 에이전트) `schemas/article.py`·`schemas/graph.py`·`schemas/response.py` 의 계약을
backend Pydantic 으로 미러한다(가이드 §8.1: 외부 입력은 Pydantic 검증). backend 는 이 값을
검증만 하고 임의로 바꾸지 않는다(가이드 §3.2).

- `NewsBatchSaveRequest` = POST /news/batch/save 요청 `{articles, graph_batch}` (SCHEMA_SPEC §7.2).
- NewsRef 노드는 `key=url` 로 오고, backend 가 저장 시 news_id 로 해소한다(SCHEMA_SPEC §3).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# ── 기사 원본 (ai Article 의 저장 대상 필드) ─────────────────────────────────
# 한글 감성 계약값(ai Sentiment). None = 감성 미판정(집계에서 제외).
SentimentLabel = Literal["긍정", "중립", "부정"]


class ArticleIn(BaseModel):
    """저장할 기사 1건(ai `Article` 의 저장 대상 필드). id/created_at 은 backend 가 채운다."""

    title: str = Field(min_length=1)
    url: str = Field(min_length=1)  # 중복 차단·upsert 키
    publisher: str | None = None
    content: str | None = None
    summary: str | None = None
    sentiment: SentimentLabel | None = None
    sentiment_score: float | None = None
    embedding: list[float] | None = None
    published_at: datetime | None = None
    # 소속 이벤트 = Neo4j Event.canonical_id(UUID 문자열). 병합 전이면 None.
    event_id: str | None = None


# ── 그래프 델타 (ai GraphBatch 미러) ────────────────────────────────────────
class NodeLabel(str, Enum):
    EVENT = "Event"
    COMPANY = "Company"
    KEYWORD = "Keyword"
    PERSON = "Person"
    COUNTRY = "Country"
    SECTOR = "Sector"
    NEWS_REF = "NewsRef"


class RelType(str, Enum):
    PARTICIPATES_IN = "PARTICIPATES_IN"
    HAS_NEWS = "HAS_NEWS"
    HAS_KEYWORD = "HAS_KEYWORD"
    MENTIONS = "MENTIONS"
    ABOUT = "ABOUT"
    BELONGS_TO = "BELONGS_TO"
    RELATED_TO = "RELATED_TO"


class GraphNode(BaseModel):
    """MERGE 대상 노드. (label, key) 가 정체성. NewsRef 는 key=url(→ backend 가 news_id 로 해소)."""

    label: NodeLabel
    key: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphRelationship(BaseModel):
    """MERGE 대상 관계. (type, start, end) 로 유일. start/end 는 GraphNode 의 (label,key)."""

    type: RelType
    start_label: NodeLabel
    start_key: str
    end_label: NodeLabel
    end_key: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphBatch(BaseModel):
    """이번 배치가 추가/갱신할 노드·관계 델타(key 기준 MERGE)."""

    nodes: list[GraphNode] = Field(default_factory=list)
    relationships: list[GraphRelationship] = Field(default_factory=list)


# ── 요청/응답 ───────────────────────────────────────────────────────────────
class NewsBatchSaveRequest(BaseModel):
    """POST /news/batch/save 요청. articles 와 graph_batch 는 같은 배치의 짝(SCHEMA_SPEC §3.3)."""

    articles: list[ArticleIn] = Field(default_factory=list)
    graph_batch: GraphBatch = Field(default_factory=GraphBatch)


class SaveResponse(BaseModel):
    """배치 저장 응답(ai `SaveResponse` 미러). 저장 실패는 degrade 없이 정확 보고(SCHEMA_SPEC §7.1)."""

    ok: bool
    saved: int = 0
    message: str | None = None


# ── 조회 응답 (ai schemas/report.py·event.py 미러) ───────────────────────────
class ArticleRef(BaseModel):
    """근거 기사 한 건(ai `ArticleRef`). news_id+summary+url 를 묶어 근거 추적 사슬의 원천."""

    news_id: int
    summary: str
    url: str


class EventArticleStats(BaseModel):
    """이벤트의 누적 기사 통계(ai `EventArticleStats`). publishers 는 원자료(distinct) — 가중치는 ai 가 적용.

    sentiment_magnitude_sum/sentiment_count 는 감성이 있는(None 아님) 기사만 집계한다(중요도 입력).
    """

    article_count: int = 0
    publishers: list[str] = Field(default_factory=list)
    sentiment_magnitude_sum: float = 0.0
    sentiment_count: int = 0
    updated_at: datetime | None = None
