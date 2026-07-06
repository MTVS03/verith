# services/report_renderer.py — ReportModel 조립 + HTML 렌더(목업 데이터 주입 템플릿)
"""④ 답변을 목업의 '뉴스 흐름 요약' 자리에 넣어 HTML 리포트 하나를 만든다(별도 텍스트 출력 없음).

- build_report_model: SubjectQueryResponse → ReportModel. top_events 는 REPORT_RANKING(잠정 importance)순
  TOP N, 이벤트별 대표 기사 소수(article_count(총 건수)와 구분). overall_gauge 는 backend 집계값을 그대로
  쓴다 — 에이전트가 기사 감성을 다시 세지 않는다(절대규칙 4). subject_found·0건·answer.data_limited →
  data_limited/note('데이터 제한', 절대규칙 5).
- render_html: 템플릿에 데이터를 주입해 HTML 문자열 반환(Jinja2 autoescape 로 XSS·깨짐 방지). answer.text
  가 '뉴스 흐름 요약' 본문, cited_event_ids 가 근거 이슈 칩. 없는 수집메타·반응도는 지어내지 않는다.
- 감성·importance 를 재계산하지 않는다(소비만). DB·LLM 을 직접 부르지 않는다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import (
    REPORT_MAX_ARTICLES_PER_EVENT,
    REPORT_TEMPLATE_PATH,
    REPORT_TOP_N,
)
from schemas.query import Answer, QueryUnderstanding
from schemas.report import ReportEvent, ReportModel, SentimentGauge
from schemas.response import SubjectQueryResponse

logger = logging.getLogger(__name__)

# 리포트 생성 시각은 KST 로 통일(파이프라인 시간 기준과 일관, llm.py KST 와 동일).
KST = timezone(timedelta(hours=9))

# news 패키지 루트(= 이 파일의 두 단계 상위: services/ → news/). 상대 템플릿 경로 해소 기준.
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# ReportModel 조립
# ---------------------------------------------------------------------------
def build_report_model(understanding: QueryUnderstanding,
                       response: SubjectQueryResponse, answer: Answer) -> ReportModel:
    """SubjectQueryResponse → ReportModel(importance순 TOP N·대표 기사 소수·backend 집계 게이지)."""
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
            articles=list(ewa.articles)[:REPORT_MAX_ARTICLES_PER_EVENT],  # 화면 노출 대표 소수
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
        data_limited=data_limited,
        note=note,
    )


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
# HTML 렌더
# ---------------------------------------------------------------------------
def render_html(report_model: ReportModel, answer: Answer) -> str:
    """목업 템플릿에 데이터를 주입해 HTML 문자열을 반환한다. 감성 비율만 계산(재집계 없음)."""
    overall = _gauge_view(report_model.overall_gauge)

    events_view = []
    for idx, ev in enumerate(report_model.top_events):
        g = _gauge_view(ev.gauge)
        events_view.append({
            "rank": idx + 1,
            "canonical_id": ev.canonical_id,
            "title": ev.canonical_title,
            "importance": ev.importance,
            "article_count": ev.article_count,
            "gauge": g,
            "articles": [{"news_id": a.news_id, "summary": a.summary, "url": a.url}
                         for a in ev.articles],
        })

    # 근거 이슈 칩: answer.cited_event_ids 를 TOP 이벤트에 링크(칩→이벤트, §0.2). TOP 밖 id 는 칩으로 안 냄.
    id_to_rank = {ev["canonical_id"]: ev["rank"] for ev in events_view if ev["canonical_id"]}
    id_to_title = {ev["canonical_id"]: ev["title"] for ev in events_view if ev["canonical_id"]}
    chips = [{"rank": id_to_rank[cid], "title": id_to_title[cid]}
             for cid in answer.cited_event_ids if cid in id_to_rank]

    context = {
        "subject": report_model.subject,
        "period_days": report_model.period_days,
        "generated_at": report_model.generated_at.strftime("%Y.%m.%d %H:%M"),
        "overall": overall,
        "analyzed_count": overall["total"],   # 분석 기사 수 = 감성 집계 대상 건수(수집메타 아님)
        "answer_text": answer.text,
        "chips": chips,
        "events": events_view,
        "data_limited": report_model.data_limited,
        "note": report_model.note,
    }
    return _environment().get_template(_template_name()).render(**context)


def _gauge_view(gauge: SentimentGauge) -> dict:
    """게이지(긍/중/부 count) → 비율(%)·순점수. 비율만 계산할 뿐 감성을 재판정하지 않는다(절대규칙 4)."""
    pos, neu, neg = gauge.positive, gauge.neutral, gauge.negative
    total = pos + neu + neg
    if total <= 0:
        return {"pos": pos, "neu": neu, "neg": neg, "total": 0,
                "pos_pct": 0, "neu_pct": 0, "neg_pct": 0, "score": 0.0, "label": "데이터 제한"}
    pos_pct = round(pos / total * 100)
    neg_pct = round(neg / total * 100)
    neu_pct = 100 - pos_pct - neg_pct
    score = round((pos - neg) / total, 2)
    if pos / total >= 0.6:
        label = "대체로 긍정"
    elif neg / total >= 0.6:
        label = "대체로 부정"
    else:
        label = "의견 갈림"
    return {"pos": pos, "neu": neu, "neg": neg, "total": total,
            "pos_pct": pos_pct, "neu_pct": neu_pct, "neg_pct": neg_pct,
            "score": score, "label": label}


# ---------------------------------------------------------------------------
# Jinja2 환경 — 템플릿 경로 해소(상대 경로는 news 패키지 루트 기준). autoescape 로 XSS 방지.
# ---------------------------------------------------------------------------
def _template_path() -> Path:
    p = Path(REPORT_TEMPLATE_PATH)
    return p if p.is_absolute() else (_PACKAGE_ROOT / p)


def _template_name() -> str:
    return _template_path().name


@lru_cache(maxsize=1)
def _environment() -> Environment:
    template_dir = _template_path().parent
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
