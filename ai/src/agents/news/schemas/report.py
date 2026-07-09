# schemas/report.py
"""리포트(pipeline_spec §1: 감성 게이지 + TOP 이벤트) 모델.

출력은 HTML 이 아니라 **JSON** 이다(팀 계약: ai·backend·frontend 모두 JSON 통일 —
리포트는 backend 가 저장하고 frontend 가 JSON 을 받아 렌더). 그래서 이 파일의 `ReportModel` 이
리포트의 **단일 JSON 계약**이며, ④ 답변 본문·근거 칩까지 담아 자기완결로 직렬화된다
(`model_dump(mode="json")`). 프론트가 렌더에 필요한 감성 비율·순점수·라벨은 `SentimentGauge` 의
computed 필드로 함께 실어 프론트가 재계산할 필요가 없게 한다(감성 판정 아님 — 비율 계산일 뿐, 절대규칙 4).
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, computed_field


class SentimentGauge(BaseModel):
    """긍/중/부 분포(집계 결과) + 표시용 파생값(비율·순점수·라벨).

    positive/neutral/negative 는 backend 실시간 집계값(절대규칙 4·5). 비율·순점수·라벨은
    그 값에서 **계산만** 한 파생 필드로, JSON 직렬화 시 함께 실려 프론트가 그대로 표시한다
    (감성을 재판정하지 않는다 — 비율 계산일 뿐). backend JSON 에는 count 만 있어도 파싱되며
    (파생 필드는 입력이 아니라 계산 결과), dump 시에만 나타난다.
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
        # 긍·부를 먼저 반올림하고 나머지로 중립을 채워 합이 100% 가 되게 한다(반올림 오차 흡수).
        return 100 - self.positive_pct - self.negative_pct if self.total else 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def score(self) -> float:
        # 순점수 = (긍 - 부) / 전체. -1.0 ~ 1.0.
        return round((self.positive - self.negative) / self.total, 2) if self.total else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def label(self) -> str:
        # 표시용 요약 라벨(감성 판정이 아니라 이미 집계된 분포의 요약 문구).
        if self.total <= 0:
            return "데이터 제한"
        if self.positive / self.total >= 0.6:
            return "대체로 긍정"
        if self.negative / self.total >= 0.6:
            return "대체로 부정"
        if self.neutral / self.total >= 0.6:
            return "중립"
        return "의견 갈림"


class ArticleRef(BaseModel):
    """근거 기사 한 건. news_id·summary·url + 표시용 제목·언론사·발행일을 한 객체로 묶어 근거 추적 붕괴를 원천 차단."""
    news_id: int            # 근거 추적 키(= Article.id). evidence news_id 사슬(TASK 09 §0.2)의 원천
    summary: str
    url: str
    # 리포트가 근거 기사를 사람이 읽을 수 있게 표시하는 원자료(backend News 행). backend가 안 주면 기본값으로 파싱됨.
    title: str = ""
    publisher: str | None = None
    published_at: datetime | None = None


class DailyCount(BaseModel):
    """발행일(KST)별 기사 건수 1건. 리포트의 '날짜별 뉴스량' 막대그래프용(backend 집계값을 받기만 함).

    date 는 backend 가 published_at(timestamptz)을 KST 로 변환해 자른 캘린더 날짜(리포트 표기 기준과 일치).
    ai 는 재집계하지 않는다(절대규칙 4·소비만) — backend daily_counts 를 그대로 실어 프론트가 그린다.
    """
    date: date
    count: int = 0


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
    """리포트의 단일 JSON 계약(종목 + 생성 시각 + 전체 게이지 + TOP 이벤트 + ④ 답변).

    frontend 가 이 JSON 을 받아 렌더한다. ④ 답변(`뉴스 흐름 요약` 본문)은 별도 채널이 아니라
    여기 answer_text·cited_event_ids·evidence_news_ids 로 내장된다(CLAUDE.md §1, 출력은 리포트 하나).
    """
    subject: str                       # 입력 종목/섹터
    generated_at: datetime
    period_days: int | None = None     # 집계 기간(헤더 표시용). 없으면 표기 생략(지어내지 않음)
    overall_gauge: SentimentGauge
    top_events: list[ReportEvent] = Field(default_factory=list)
    # 날짜별 뉴스량(발행일 KST 기준 오름차순). backend 집계값을 그대로 실어 프론트가 막대그래프로 렌더.
    daily_counts: list[DailyCount] = Field(default_factory=list)
    # ④ 답변(뉴스 흐름 요약 섹션) 내장 — HTML 대신 JSON 으로 프론트에 전달.
    answer_text: str = ""              # 뉴스 흐름 요약 본문(= Answer.text)
    cited_event_ids: list[str] = Field(default_factory=list)   # 근거 이슈 칩→이벤트(canonical_id). 프론트가 top_events와 링크
    evidence_news_ids: list[int] = Field(default_factory=list)  # 근거 news_id(Article.id, §0.2)
    data_limited: bool = False         # 데이터 부족 시 True("데이터 제한" 표기, 절대규칙 5)
    note: str | None = None            # 제한 사유 등
    html: str = ""                     # 렌더링된 HTML 리포트(보관함/프론트엔드 호환용)

