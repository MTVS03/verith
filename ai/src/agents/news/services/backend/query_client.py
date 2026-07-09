# services/backend/query_client.py — 질의(리포트) 흐름 조회 (TASK 08, query_spec §4 ②③)
"""리포트(TASK 09)가 소비할 backend 조회만 제공한다: 종목별 이벤트(single-hop)·두 회사 공유 이벤트
(multi-hop)·이벤트별 기사(요약/감성) on-demand. 질문 이해(①)·답변 생성(④)·HTML 렌더는 질의 흐름
소관(범위 밖) — 여기는 그 흐름이 쓰는 **backend 조회 HTTP 계약**만 제공한다.

⚠️ 감성 분포(게이지)는 이 에이전트가 집계하지 않는다 — backend 가 실시간 집계(sentiment=None 제외)해
   SentimentGauge/overall_gauge 로 돌려준 값을 **받기만** 한다(CLAUDE.md §5, SCHEMA_SPEC §7.3, 절대규칙 4).
⚠️ 정렬(랭킹)은 잠정 importance 내림차순 — 관련도 점수 정의는 미확정이라 코드에 박지 않고 backend/
   후속 튜닝에 맡긴다(pipeline_spec §11, query_spec §6).
⚠️ 조회 실패는 BackendError 를 전파한다 — 리포트가 "데이터 제한"으로 처리(TASK 09, 절대규칙 5). 저장·
   삭제(쓰기)의 정확 보고(ok=False)와 달리, 조회는 상위가 분기하도록 예외를 올린다. HTTP 는 BackendClient 로만.
"""
from __future__ import annotations

import logging

from src.agents.news.config import (
    BACKEND_EVENT_ARTICLES_PATH,
    BACKEND_QUERY_SHARED_PATH,
    BACKEND_QUERY_SUBJECT_PATH,
)
from src.agents.news.schemas.report import ArticleRef
from src.agents.news.schemas.response import SubjectQueryResponse
from src.agents.news.services.backend.client import BackendClient

logger = logging.getLogger(__name__)

_client: BackendClient | None = None


def _get_client() -> BackendClient:
    global _client
    if _client is None:
        _client = BackendClient()
    return _client


def get_events_by_subject(companies: list[str], within_days: int) -> SubjectQueryResponse:
    """single-hop 종목 이벤트를 importance 내림차순으로 조회.

    각 이벤트에 대표 근거 기사(ArticleRef=news_id+summary+url) 소수 + 실시간 집계된 SentimentGauge +
    article_count(총 건수)를 담은 EventWithArticles 리스트로 온다. subject_found 로 '없는 종목' vs
    '뉴스 0건'을 구분한다(TASK 01 §3.4). overall_gauge 도 backend 집계값(ai 재집계 안 함).
    실패 시 BackendError 전파(리포트가 데이터 제한 처리).
    """
    params = {"companies": companies, "within_days": within_days}
    data = _get_client()._request("GET", BACKEND_QUERY_SUBJECT_PATH, params=params)
    return SubjectQueryResponse.model_validate(data)


def get_shared_events(company_a: str, company_b: str, within_days: int) -> SubjectQueryResponse:
    """multi-hop — 두 회사가 함께 PARTICIPATES_IN 한 공유 이벤트(관계 질문 핵심, query_spec §2). importance순.

    응답 형태는 get_events_by_subject 와 동일(SubjectQueryResponse). 실패 시 BackendError 전파.
    """
    params = {"company_a": company_a, "company_b": company_b, "within_days": within_days}
    data = _get_client()._request("GET", BACKEND_QUERY_SHARED_PATH, params=params)
    return SubjectQueryResponse.model_validate(data)


def get_articles_by_event(event_id: str, limit: int) -> list[ArticleRef]:
    """이벤트(event_id=canonical_id)에 HAS_NEWS 로 이어진 기사 → ArticleRef(news_id+summary+url) 리스트.

    - `limit` 으로 개수를 제어한다(Top-N 조정은 DTO 재배포 없이 이 인자로). 정렬(예: published_at desc)은
      backend 규칙.
    - 대표 소수(EventWithArticles.articles)를 넘는 **깊은 근거가 필요할 때만 on-demand** 로 쓴다(§3.5-3).
      bare news_id 가 아니라 ArticleRef 를 돌려주므로 id→기사 왕복이 없다. 실패 시 BackendError 전파.
    """
    path = BACKEND_EVENT_ARTICLES_PATH.format(event_id=event_id)
    data = _get_client()._request("GET", path, params={"limit": limit})
    if not data:
        return []
    return [ArticleRef.model_validate(item) for item in data]
