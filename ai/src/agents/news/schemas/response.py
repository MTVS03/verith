# schemas/response.py
"""backend 조회/저장/삭제 응답 래퍼. sequence.md §2(리포트 흐름)에서 query_client가 받는 형태.

세부 엔드포인트 계약은 TASK 08(및 SCHEMA_SPEC §7)에서 확정하되, 모델 골격은 여기 둔다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from src.agents.news.schemas.report import ArticleRef, DailyCount, SentimentGauge
from src.agents.news.schemas.event import Event


class EventWithArticles(BaseModel):
    """조회된 이벤트 1건 + 대표 근거 기사 소수 + 실시간 감성 집계."""
    event: Event
    article_count: int = 0   # 관련 기사 총 건수(실시간 집계). articles는 그 일부(대표 소수)
    # 화면 노출용 대표 소수(요약+링크 묶음, 순서 어긋남 방지). news_id를 이미 포함하므로
    # 일반 리포트는 이 대표 소수만으로 근거를 단다(재조회 불필요).
    # 더 깊은 근거는 get_articles_by_event로 on-demand(TASK 09 §3.5).
    articles: list[ArticleRef] = Field(default_factory=list)
    gauge: SentimentGauge = Field(default_factory=SentimentGauge)  # 조회 시 backend 실시간 집계 결과


class SubjectQueryResponse(BaseModel):
    """종목 조회 응답. importance 내림차순 정렬 가정."""
    subject: str
    # "없는 종목"과 "종목은 있으나 뉴스 0건"을 구분하기 위한 플래그.
    # 둘 다 events=[]가 되므로 리포트의 '데이터 제한' 문구를 다르게 쓰려면 필요.
    # 당장 backend가 구분값을 못 주면 기본 True로 두고 TASK 08에서 확정.
    subject_found: bool = True
    events: list[EventWithArticles] = Field(default_factory=list)
    # 전체 감성 집계(sentiment=None 제외). backend가 채운다 — ai는 재집계 안 함(절대규칙 4, SCHEMA_SPEC §7.3).
    overall_gauge: SentimentGauge = Field(default_factory=SentimentGauge)
    # 포함된 이벤트 기사들의 발행일(KST)별 건수(오름차순). backend 집계값을 받기만 함(리포트 막대그래프용).
    daily_counts: list[DailyCount] = Field(default_factory=list)


class SaveResponse(BaseModel):
    """배치 저장 응답. 쓰기 실패 시 정확 보고(degrade 금지, SCHEMA_SPEC §7.1)."""
    ok: bool
    saved: int = 0
    message: str | None = None


class CleanupResponse(BaseModel):
    """7일 롤링 삭제 응답."""
    ok: bool
    deleted_articles: int = 0
    deleted_events: int = 0
    message: str | None = None


class ReportSaveResponse(BaseModel):
    """질의 리포트 저장 응답 wrapper — { report_id, report }(SCHEMA_SPEC §7.2).

    backend 가 생성한 report_id 를 부착해 돌려준다(에이전트는 id 를 만들지 않는다, CLAUDE.md §2-5).
    report 는 방금 저장한 ai ReportModel JSON 원본(backend 는 재해석하지 않음). frontend 는 이 report_id 로
    GET /news/reports/{id} 를 호출해 리포트를 다시 연다(technical 과 동형: 저장 → id → 프론트 조회).
    """
    report_id: str
    report: dict = Field(default_factory=dict)
