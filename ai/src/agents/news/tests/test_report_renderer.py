# tests/test_report_renderer.py — 리포트 조립·렌더(TASK 09) 테스트
"""build_report_model(importance순 TOP N·대표 소수·backend 게이지) + render_html(요약·칩·이스케이프·데이터 제한).

DB·LLM 은 부르지 않는다 — 렌더러는 이미 조회·생성된 데이터를 소비만 한다(감성·importance 재계산 없음).
"""
from __future__ import annotations

import services.report_renderer as rr
from config import REPORT_MAX_ARTICLES_PER_EVENT, REPORT_TOP_N
from schemas.event import Event
from schemas.query import Answer, QueryUnderstanding
from schemas.report import ArticleRef, SentimentGauge
from schemas.response import EventWithArticles, SubjectQueryResponse


def _ewa(cid, title, importance, n_articles, gauge):
    arts = [ArticleRef(news_id=cid_n, summary=f"요약 {cid_n}", url=f"https://x/{cid_n}")
            for cid_n in range(n_articles)]
    return EventWithArticles(event=Event(canonical_id=cid, canonical_title=title, importance=importance),
                             article_count=n_articles, articles=arts, gauge=gauge)


def _understanding():
    return QueryUnderstanding(companies=["삼성전자"], period_days=7, original_question="삼성전자 요약")


def test_build_model_sorts_by_importance_and_limits(monkeypatch):
    overall = SentimentGauge(positive=40, neutral=30, negative=30)
    events = [
        _ewa("low", "낮은 중요도", 1.0, 5, SentimentGauge(positive=1, neutral=1, negative=1)),
        _ewa("high", "높은 중요도", 9.0, 5, SentimentGauge(positive=5, neutral=0, negative=0)),
        _ewa("mid", "중간 중요도", 5.0, 5, SentimentGauge(positive=2, neutral=2, negative=1)),
    ]
    resp = SubjectQueryResponse(subject="삼성전자", subject_found=True, events=events, overall_gauge=overall)
    answer = Answer(text="요약")
    model = rr.build_report_model(_understanding(), resp, answer)

    # importance 내림차순
    assert [e.canonical_title for e in model.top_events][:3] == ["높은 중요도", "중간 중요도", "낮은 중요도"]
    # 이벤트별 대표 소수만(총 건수와 구분)
    top = model.top_events[0]
    assert top.article_count == 5
    assert len(top.articles) == REPORT_MAX_ARTICLES_PER_EVENT
    # overall_gauge 는 backend 집계값 그대로(재집계 없음)
    assert model.overall_gauge is overall
    assert model.data_limited is False


def test_top_n_cap():
    events = [_ewa(f"e{i}", f"이슈{i}", float(i), 1, SentimentGauge(positive=1))
              for i in range(REPORT_TOP_N + 3)]
    resp = SubjectQueryResponse(subject="삼성전자", subject_found=True, events=events)
    model = rr.build_report_model(_understanding(), resp, Answer(text="t"))
    assert len(model.top_events) == REPORT_TOP_N


def test_subject_not_found_is_data_limited():
    resp = SubjectQueryResponse(subject="없는종목", subject_found=False)
    model = rr.build_report_model(_understanding(), resp, Answer(text="t", data_limited=True))
    assert model.data_limited is True
    assert "데이터 제한" in (model.note or "")


def test_render_html_injects_answer_and_chips():
    overall = SentimentGauge(positive=41, neutral=31, negative=28)
    events = [
        _ewa("e1", "4분기 실적 발표", 9.0, 4, SentimentGauge(positive=20, neutral=2, negative=4)),
        _ewa("e2", "HBM 공급 계약", 7.0, 3, SentimentGauge(positive=13, neutral=2, negative=1)),
    ]
    resp = SubjectQueryResponse(subject="삼성전자", subject_found=True, events=events, overall_gauge=overall)
    answer = Answer(text="실적 발표가 흐름을 주도했습니다.", evidence_news_ids=[0, 1],
                    cited_event_ids=["e1"], data_limited=False)
    model = rr.build_report_model(_understanding(), resp, answer)
    html = rr.render_html(model, answer)

    # 핵심 목업 섹션 존재
    for section in ("뉴스 흐름 요약", "주요 이슈", "전체 감성", "분석 기사 수"):
        assert section in html
    # ④ 답변 텍스트가 요약 자리에 들어감
    assert "실적 발표가 흐름을 주도했습니다." in html
    # 근거 칩(cited_event_ids → 이벤트 제목)
    assert "4분기 실적 발표" in html
    # TOP 순서: 실적(9.0)이 HBM(7.0)보다 앞
    assert html.index("4분기 실적 발표") < html.index("HBM 공급 계약")
    # 없는 수집메타·반응도는 지어내지 않음
    for fabricated in ("318", "1.8배", "평소比"):
        assert fabricated not in html


def test_render_html_data_limited_badge():
    resp = SubjectQueryResponse(subject="없는종목", subject_found=False, events=[])
    answer = Answer(text="데이터 제한으로 표기합니다.", data_limited=True)
    model = rr.build_report_model(_understanding(), resp, answer)
    html = rr.render_html(model, answer)
    assert "데이터 제한" in html
    assert "추정으로 채우지 않습니다" in html


def test_render_html_escapes_special_chars():
    overall = SentimentGauge(positive=1, neutral=0, negative=0)
    events = [_ewa("e1", "<script>alert(1)</script>", 9.0, 1, SentimentGauge(positive=1))]
    resp = SubjectQueryResponse(subject="삼성전자", subject_found=True, events=events, overall_gauge=overall)
    answer = Answer(text="정상 <b>텍스트</b>", cited_event_ids=["e1"])
    model = rr.build_report_model(_understanding(), resp, answer)
    html = rr.render_html(model, answer)
    # 원시 <script> 가 그대로 들어가지 않고 이스케이프됨(XSS 방지)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
