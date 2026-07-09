# services/report_renderer.py — SubjectQueryResponse → ReportModel(JSON) 조립
"""④ 답변을 리포트의 '뉴스 흐름 요약' 자리에 넣어 **JSON 리포트 하나**를 만든다(별도 텍스트 출력 없음).

출력은 HTML 이 아니라 JSON 이다(팀 계약: ai·backend·frontend JSON 통일 — 리포트는 backend 가
저장하고 frontend 가 JSON 을 받아 렌더). 이 서비스는 조회 결과를 렌더 가능한 데이터로 **조립**만 하고,
직렬화(`model_dump`)는 노드가 한다.

- build_report_model: SubjectQueryResponse → ReportModel. top_events 는 REPORT_RANKING(잠정 importance)순
  TOP N, 이벤트별 대표 기사 소수(article_count(총 건수)와 구분). overall_gauge 는 backend 집계값을 그대로
  쓴다 — 에이전트가 기사 감성을 다시 세지 않는다(절대규칙 4). ④ 답변(text·근거 칩·근거 news_id)을 모델에
  내장. subject_found·0건·answer.data_limited → data_limited/note('데이터 제한', 절대규칙 5).
- fallback_report_json: 렌더 자체가 실패했을 때 스키마에 맞는 최소 JSON(정직한 '데이터 제한').
- 감성·importance 를 재계산하지 않는다(소비만). DB·LLM 을 직접 부르지 않는다. 게이지 비율·라벨은
  SentimentGauge 의 computed 필드가 계산한다(감성 판정 아님).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from src.agents.news.config import (
    REPORT_MAX_ARTICLES_PER_EVENT,
    REPORT_TOP_N,
)
from src.agents.news.schemas.query import Answer, QueryUnderstanding
from src.agents.news.schemas.report import ReportEvent, ReportModel, SentimentGauge
from src.agents.news.schemas.response import SubjectQueryResponse

logger = logging.getLogger(__name__)

# 리포트 생성 시각은 KST 로 통일(파이프라인 시간 기준과 일관, llm.py KST 와 동일).
KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# ReportModel 조립
# ---------------------------------------------------------------------------
def build_report_model(understanding: QueryUnderstanding,
                       response: SubjectQueryResponse, answer: Answer) -> ReportModel:
    """SubjectQueryResponse → ReportModel(importance순 TOP N·대표 기사 소수·backend 집계 게이지·④ 답변 내장)."""
    ranked = sorted(response.events, key=lambda e: (e.event.importance or 0.0), reverse=True)
    top_events: list[ReportEvent] = []
    for ewa in ranked[:REPORT_TOP_N]:
        event = ewa.event
        top_events.append(ReportEvent(
            canonical_id=event.canonical_id,
            canonical_title=event.canonical_title,
            importance=event.importance or 0.0,
            gauge=ewa.gauge,
            article_count=ewa.article_count,                       # 총 건수(실시간 집계)
            # 화면 노출 대표 소수. 완전 동일 기사(같은 url 또는 같은 본문)는 하나만 남긴다(팀 결정: 중복 기사 제거).
            articles=_dedup_articles(ewa.articles)[:REPORT_MAX_ARTICLES_PER_EVENT],
        ))

    subject = response.subject or (" · ".join(understanding.companies) if understanding.companies
                                   else (understanding.original_question or "요청 종목"))
    data_limited = (not response.subject_found) or (not top_events) or answer.data_limited
    note = _limit_note(response, top_events, answer)

    return ReportModel(
        subject=subject,
        generated_at=datetime.now(KST),
        period_days=understanding.period_days,
        overall_gauge=response.overall_gauge,
        top_events=top_events,
        # 날짜별 뉴스량 — backend 집계값을 그대로 실어 프론트 막대그래프로(ai 재집계 안 함, 절대규칙 4).
        daily_counts=list(response.daily_counts),
        # ④ 답변(뉴스 흐름 요약 섹션) 내장 — 근거 칩·근거 news_id 포함(§0.2). 프론트가 칩↔TOP 이벤트를 링크.
        answer_text=answer.text,
        cited_event_ids=list(answer.cited_event_ids),
        evidence_news_ids=list(answer.evidence_news_ids),
        data_limited=data_limited,
        note=note,
    )


def _dedup_articles(articles: list) -> list:
    """완전 동일 기사(같은 url 또는 공백 정규화 후 같은 summary)를 하나만 남긴다(팀 결정: 중복 기사 제거).

    같은 사건의 서로 다른 기사(수치·표현이 조금 다른)는 중복이 아니므로 남긴다 — 억지 병합 금지(절대규칙 5).
    최초 등장 순서를 보존한다(정렬은 backend importance/published_at 규칙을 이미 반영).
    """
    seen_urls: set[str] = set()
    seen_summaries: set[str] = set()
    out: list = []
    for a in articles:
        url_key = (a.url or "").strip()
        sum_key = " ".join((a.summary or "").split())  # 공백·개행 정규화 후 완전 일치만 중복으로 본다
        if (url_key and url_key in seen_urls) or (sum_key and sum_key in seen_summaries):
            continue
        if url_key:
            seen_urls.add(url_key)
        if sum_key:
            seen_summaries.add(sum_key)
        out.append(a)
    return out


def _limit_note(response: SubjectQueryResponse, top_events: list[ReportEvent],
                answer: Answer) -> str | None:
    """'데이터 제한' 사유 문구. 없는 종목 vs 뉴스 0건을 subject_found 로 구분(§0.2, TASK 01 §3.4)."""
    if not response.subject_found:
        return "요청 종목을 찾지 못했습니다 (데이터 제한)."
    if not top_events:
        return "최근 기간 내 관련 뉴스가 없습니다 (데이터 제한)."
    if answer.data_limited:
        return "근거가 부족한 부분은 추정 없이 표기했습니다 (데이터 제한)."
    return None


# ---------------------------------------------------------------------------
# 렌더 실패 시 최소 JSON — 성공 위장 금지('데이터 제한'을 정직히 표기, 절대규칙 5·§7)
# ---------------------------------------------------------------------------
def fallback_report_json(understanding: QueryUnderstanding) -> dict:
    """조립이 실패했을 때의 최소 리포트 JSON. 스키마(ReportModel)에 맞춰 프론트 계약을 깨지 않는다."""
    subject = " · ".join(understanding.companies) if understanding.companies else "요청 종목"
    model = ReportModel(
        subject=subject,
        generated_at=datetime.now(KST),
        period_days=understanding.period_days,
        overall_gauge=SentimentGauge(),
        data_limited=True,
        note="리포트를 생성하지 못했습니다 (데이터 제한).",
    )
    return model.model_dump(mode="json")
