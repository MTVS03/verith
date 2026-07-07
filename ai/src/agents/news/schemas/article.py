# schemas/article.py
"""기사 원본(Article) + LLM 추출 결과(ExtractResult) 계약 모델.

파이프라인 전 구간(크롤링→추출→감성→임베딩→병합→저장)이 공유하는 데이터 계약.
DB ORM 모델이 아니라 backend에 보내고/받는 요청·응답 명세다(절대규칙 1: DB 직접 접근 금지).
TASK 03(EventCandidate)·TASK 04(SentimentResult) 모델도 services dataclass가 아니라
여기 schemas에 두어 서비스·노드·테스트가 같은 계약을 공유한다.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class Sentiment(str, Enum):
    """감성 라벨. LLM 자유입력 금지 → 긍정/중립/부정 3종만 허용(절대규칙 4, CLAUDE.md §4)."""
    POSITIVE = "긍정"
    NEUTRAL = "중립"
    NEGATIVE = "부정"


# 크롤링 진행/결과 상태. content=None만으로는 "미크롤링 / 본문없음(속보) / 실패"를 구분 못 함.
CrawlStatus = Literal["pending", "success", "no_content", "failed"]


class SourceType(str, Enum):
    """추출 근거 출처. 병합·리포트에서 신뢰도 구분에 사용."""
    ARTICLE = "article"          # 본문 기반 추출
    RSS_SUMMARY = "rss_summary"  # (향후) RSS 요약 기반 — 현재 미사용, Enum만 예약
    TITLE_ONLY = "title_only"    # 제목만 사용(본문 없음)


class EventCandidate(BaseModel):
    """LLM이 기사에서 뽑은 원시 후보 이벤트(TASK 03). 대표 Event·canonical_title은 TASK 05가 생성."""
    title: str          # 사건명만(회사명 금지: "HBM 공급 계약" O / "삼성전자 HBM 공급 계약" X). 감성 평가어 금지
    confidence: float   # 0~1 추출 확신도(importance·감성 세기가 아님). 병합(TASK 05)이 가중·필터에 사용


class ExtractResult(BaseModel):
    """LLM(Qwen3)이 기사 1건에서 추출한 결과. 감성·영향도 없음(감성=FinBert, 영향도=importance)."""
    summary: str
    companies: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    events: list[EventCandidate] = Field(default_factory=list)   # 원시 후보 이벤트(title+confidence, TASK 03)
    countries: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    # 이벤트 발생 시점(KST aware). Article.published_at(발행)과 별개. 상대표현은 published_at 기준 환산,
    # 날짜만 있으면 00:00(KST), 불명확/판단불가면 None(지어내지 않음). 정규화 규칙 TASK 03 §3.2.1.
    event_date: datetime | None = None
    # 본문 기반/RSS요약/제목만. 병합·리포트 신뢰도 판단에 활용(rss_summary는 현재 미생성).
    source_type: SourceType = SourceType.ARTICLE


class Article(BaseModel):
    """기사 원본 + 분석 결과. 파이프라인을 따라 점진적으로 채워짐(분석 결과 필드는 모두 Optional)."""
    # 크롤링 단계
    title: str
    url: HttpUrl                    # 중복 차단 키(필수)
    publisher: str | None = None    # importance 가중치에 사용
    content: str | None = None      # HTML 태그 제거 후 순수 텍스트 본문(크롤링 실패 시 None → skip)
    published_at: datetime | None = None
    crawl_status: CrawlStatus = "pending"   # 크롤링 상태. 디버깅·Tool Calling 분기용
    content_available: bool = False         # 편의 플래그(= crawl_status == "success"와 정합 유지)
    # 분석 단계 (초기 None)
    summary: str | None = None      # LLM 통일 요약. 임베딩·병합 기준
    sentiment: Sentiment | None = None
    sentiment_score: float | None = None   # KR-FinBert confidence(0~1). importance·리포트에 활용
    # arctic-embed-l-v2.0-ko에서 생성한 summary 임베딩 (services/embedder.py).
    # 대칭 유사도 비교라 query/document 프리픽스 없이 임베딩(event_merge.md §2). 차원은 모델 스펙 따름.
    embedding: list[float] | None = None
    event_id: str | None = None            # 소속 이벤트의 canonical_id(UUID). 병합 전 None
    # 분석 파이프라인(요약·감성·임베딩·병합) 정상 완료 여부.
    # summary/event_id가 None인 게 "아직 안 함"인지 "하다 실패"인지 구분하는 최종 플래그.
    analysis_completed: bool = False
    # backend가 채우는 식별자
    id: int | None = None
    created_at: datetime | None = None


class SentimentResult(BaseModel):
    """감성 판정 결과(TASK 04). services dataclass가 아니라 schemas에 두어 서비스·노드·테스트가 공유."""
    sentiment: Sentiment   # 긍정|중립|부정 (모델 라벨 → FINBERT_LABEL_MAP 매핑)
    score: float           # = Article.sentiment_score. 예측 라벨 confidence(softmax 최댓값, 0~1)
