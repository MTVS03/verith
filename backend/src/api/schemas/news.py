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

from pydantic import BaseModel, Field, computed_field

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


class ExistingUrlsRequest(BaseModel):
    """POST /news/exists 요청. 수집한 후보 url 목록을 넣어 이미 저장된 것을 가려낸다."""

    urls: list[str] = Field(default_factory=list)


class ExistingUrlsResponse(BaseModel):
    """POST /news/exists 응답. `existing` = 요청 url 중 이미 news 에 있는 것(ai 는 나머지를 신규로 처리)."""

    existing: list[str] = Field(default_factory=list)


class CleanupResponse(BaseModel):
    """7일 롤링 삭제 응답(ai `CleanupResponse` 미러)."""

    ok: bool
    deleted_articles: int = 0
    deleted_events: int = 0
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


class CandidateEvent(BaseModel):
    """병합 후보 이벤트(ai `CandidateEvent`). ai 병합(TASK 05)이 유사도 채점에 쓴다.

    embedding = 소속 기사 임베딩의 centroid(평균) — backend 가 계산해 제공(ai 는 읽기만).
    event_time = 소속 기사 published_at 최댓값(없으면 None).
    """

    canonical_id: str
    companies: list[str] = Field(default_factory=list)
    embedding: list[float]
    event_time: datetime | None = None


# ── 질의(subject/shared) 응답 (ai schemas/report.py·event.py·response.py 미러) ──
class SentimentGauge(BaseModel):
    """긍/중/부 분포(backend 실시간 집계) + 표시용 파생값(비율·순점수·라벨). ai `SentimentGauge` 동일.

    positive/neutral/negative 는 집계값(감성 None 제외). 파생 필드는 그 값에서 계산만 한다
    (감성 재판정 아님 — 절대규칙 4). dump 시 함께 실려 프론트가 재계산할 필요가 없다.
    """

    positive: int = 0
    neutral: int = 0
    negative: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> int:
        return self.positive + self.neutral + self.negative

    @computed_field  # type: ignore[prop-decorator]
    @property
    def positive_pct(self) -> int:
        return round(self.positive / self.total * 100) if self.total else 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def negative_pct(self) -> int:
        return round(self.negative / self.total * 100) if self.total else 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def neutral_pct(self) -> int:
        return 100 - self.positive_pct - self.negative_pct if self.total else 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def score(self) -> float:
        return round((self.positive - self.negative) / self.total, 2) if self.total else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def label(self) -> str:
        if self.total <= 0:
            return "데이터 제한"
        if self.positive / self.total >= 0.6:
            return "대체로 긍정"
        if self.negative / self.total >= 0.6:
            return "대체로 부정"
        return "의견 갈림"


class Event(BaseModel):
    """Neo4j 중심 노드(ai `Event`). 감성 count 는 노드에 없음(조회 시 집계)."""

    canonical_id: str | None = None
    canonical_title: str
    importance: float | None = None
    companies: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class EventWithArticles(BaseModel):
    """조회된 이벤트 1건 + 대표 근거 기사 소수 + 실시간 감성 게이지(ai `EventWithArticles`)."""

    event: Event
    article_count: int = 0
    articles: list[ArticleRef] = Field(default_factory=list)
    gauge: SentimentGauge = Field(default_factory=SentimentGauge)


class SubjectQueryResponse(BaseModel):
    """종목/공유 이벤트 조회 응답(ai `SubjectQueryResponse`). importance 내림차순 가정.

    subject_found: '없는 종목'과 '종목은 있으나 뉴스 0건'을 구분(둘 다 events=[]).
    overall_gauge: 전체 감성 집계(sentiment=None 제외) — backend 가 채운다(ai 재집계 안 함).
    """

    subject: str
    subject_found: bool = True
    events: list[EventWithArticles] = Field(default_factory=list)
    overall_gauge: SentimentGauge = Field(default_factory=SentimentGauge)
