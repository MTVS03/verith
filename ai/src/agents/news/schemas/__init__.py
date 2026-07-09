# schemas/__init__.py
"""파이프라인 계약 모델 재노출(re-export).

`from schemas import Article, ExtractResult, Event, ReportModel, SubjectQueryResponse ...` 형태로 사용.
schemas/graph.py(Neo4j 노드/관계 상세)는 TASK 07에서 정의·추가한다(여기선 미노출).
"""
from src.agents.news.schemas.article import (
    Article,
    CrawlStatus,
    EventCandidate,
    ExtractResult,
    Sentiment,
    SentimentResult,
    SourceType,
)
from src.agents.news.schemas.event import (
    CandidateEvent,
    Event,
    EventArticleStats,
    MergeCandidate,
    MergeDecision,
)
from src.agents.news.schemas.report import (
    ArticleRef,
    ReportEvent,
    ReportModel,
    SentimentGauge,
)
from src.agents.news.schemas.response import (
    CleanupResponse,
    EventWithArticles,
    SaveResponse,
    SubjectQueryResponse,
)

__all__ = [
    # article
    "Article",
    "CrawlStatus",
    "EventCandidate",
    "ExtractResult",
    "Sentiment",
    "SentimentResult",
    "SourceType",
    # event
    "CandidateEvent",
    "Event",
    "EventArticleStats",
    "MergeCandidate",
    "MergeDecision",
    # report
    "ArticleRef",
    "ReportEvent",
    "ReportModel",
    "SentimentGauge",
    # response
    "CleanupResponse",
    "EventWithArticles",
    "SaveResponse",
    "SubjectQueryResponse",
]
