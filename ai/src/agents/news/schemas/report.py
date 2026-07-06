# schemas/report.py
"""HTML 리포트(pipeline_spec §1: 감성 게이지 + TOP 이벤트) 입력 모델."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SentimentGauge(BaseModel):
    """긍/중/부 분포(집계 결과). 비율은 렌더러에서 계산하거나 property로 제공."""
    positive: int = 0
    neutral: int = 0
    negative: int = 0


class ArticleRef(BaseModel):
    """근거 기사 한 건. news_id·summary·url을 한 객체로 묶어 순서 어긋남/근거 추적 붕괴를 원천 차단."""
    news_id: int            # 근거 추적 키(= Article.id). evidence news_id 사슬(TASK 09 §0.2)의 원천
    summary: str
    url: str


class ReportEvent(BaseModel):
    """리포트에 노출되는 이벤트 한 건."""
    # 근거 이슈 칩(Answer.cited_event_ids)→이벤트 링크의 키(= Event.canonical_id, §0.2). 없으면 None.
    canonical_id: str | None = None
    canonical_title: str
    importance: float
    gauge: SentimentGauge
    article_count: int = 0   # 관련 기사 총 건수(실시간 집계). "관련 기사 42건" 표시용
    articles: list[ArticleRef] = Field(default_factory=list)  # 근거로 노출할 대표 소수(전체 아님)


class ReportModel(BaseModel):
    """종목(입력) + 생성 시각 + 전체 게이지 + TOP 이벤트 리스트."""
    subject: str                       # 입력 종목/섹터
    generated_at: datetime
    period_days: int | None = None     # 집계 기간(헤더 표시용). 없으면 표기 생략(지어내지 않음)
    overall_gauge: SentimentGauge
    top_events: list[ReportEvent] = Field(default_factory=list)
    data_limited: bool = False         # 데이터 부족 시 True("데이터 제한" 표기, 절대규칙 5)
    note: str | None = None            # 제한 사유 등
