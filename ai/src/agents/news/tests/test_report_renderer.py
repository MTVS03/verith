# tests/test_report_renderer.py — 리포트 조립(TASK 09) 테스트
"""build_report_model(importance순 TOP N·대표 소수·backend 게이지·④ 답변 내장) → JSON 계약.

출력은 HTML 이 아니라 JSON 이다(팀 계약: ai·backend·frontend JSON 통일). 렌더러는 이미 조회·생성된
데이터를 소비만 한다(감성·importance 재계산 없음). DB·LLM 은 부르지 않는다.
"""
from __future__ import annotations

import src.agents.news.services.report_renderer as rr
from src.agents.news.config import REPORT_MAX_ARTICLES_PER_EVENT, REPORT_TOP_N
from src.agents.news.schemas.event import Event
from src.agents.news.schemas.query import Answer, QueryUnderstanding
from src.agents.news.schemas.report import ArticleRef, SentimentGauge
from src.agents.news.schemas.response import EventWithArticles, SubjectQueryResponse


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
    # 이벤트별 관련 기사 '전부' 노출(중복만 제거). article_count(총 건수)와 값은 같다(모두 distinct).
    top = model.top_events[0]
    assert top.article_count == 5
    assert len(top.articles) == 5  # 5건 전부(상한 REPORT_MAX_ARTICLES_PER_EVENT=100 이내)
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


def test_report_json_embeds_answer_and_evidence():
    overall = SentimentGauge(positive=41, neutral=31, negative=28)
    events = [
        _ewa("e1", "4분기 실적 발표", 9.0, 4, SentimentGauge(positive=20, neutral=2, negative=4)),
        _ewa("e2", "HBM 공급 계약", 7.0, 3, SentimentGauge(positive=13, neutral=2, negative=1)),
    ]
    resp = SubjectQueryResponse(subject="삼성전자", subject_found=True, events=events, overall_gauge=overall)
    answer = Answer(text="실적 발표가 흐름을 주도했습니다.", evidence_news_ids=[0, 1],
                    cited_event_ids=["e1"], data_limited=False)
    model = rr.build_report_model(_understanding(), resp, answer)
    payload = model.model_dump(mode="json")   # 프론트/백엔드로 나가는 JSON 계약

    # ④ 답변 본문·근거가 JSON 에 내장됨(별도 텍스트 채널 없음)
    assert payload["answer_text"] == "실적 발표가 흐름을 주도했습니다."
    assert payload["evidence_news_ids"] == [0, 1]
    assert payload["cited_event_ids"] == ["e1"]
    # TOP 순서: 실적(9.0)이 HBM(7.0)보다 앞
    titles = [e["canonical_title"] for e in payload["top_events"]]
    assert titles == ["4분기 실적 발표", "HBM 공급 계약"]
    # 없는 수집메타·반응도는 지어내지 않음(그런 키가 애초에 없음)
    for fabricated in ("collected_count", "dedup_count", "reactivity"):
        assert fabricated not in payload


def test_report_json_gauge_ratios_are_computed():
    """게이지 비율·순점수·라벨을 AI 가 계산해 JSON 에 담는다(프론트 재계산 불필요). 감성 판정 아님."""
    overall = SentimentGauge(positive=60, neutral=10, negative=30)
    resp = SubjectQueryResponse(subject="삼성전자", subject_found=True,
                                events=[_ewa("e1", "이슈", 1.0, 1, SentimentGauge(positive=1))],
                                overall_gauge=overall)
    payload = rr.build_report_model(_understanding(), resp, Answer(text="t")).model_dump(mode="json")

    g = payload["overall_gauge"]
    assert g["total"] == 100
    assert g["positive_pct"] == 60
    assert g["negative_pct"] == 30
    assert g["neutral_pct"] == 10          # 100 - 60 - 30, 합이 100
    assert g["score"] == 0.3               # (60 - 30) / 100
    assert g["label"] == "대체로 긍정"      # 긍정 비율 >= 0.6


def test_report_json_data_limited_flag_and_note():
    resp = SubjectQueryResponse(subject="없는종목", subject_found=False, events=[])
    answer = Answer(text="데이터 제한으로 표기합니다.", data_limited=True)
    payload = rr.build_report_model(_understanding(), resp, answer).model_dump(mode="json")
    assert payload["data_limited"] is True
    assert "데이터 제한" in (payload["note"] or "")
    # 빈 게이지의 라벨은 '데이터 제한'
    assert payload["overall_gauge"]["label"] == "데이터 제한"


def test_report_json_preserves_special_chars_verbatim():
    """JSON 은 값을 그대로 실어 보낸다(이스케이프는 렌더하는 프론트 책임). 데이터 유실·변형이 없어야 함."""
    events = [_ewa("e1", "<b>실적</b> & \"발표\"", 9.0, 1, SentimentGauge(positive=1))]
    resp = SubjectQueryResponse(subject="삼성전자", subject_found=True, events=events,
                                overall_gauge=SentimentGauge(positive=1))
    answer = Answer(text="정상 <b>텍스트</b>", cited_event_ids=["e1"])
    payload = rr.build_report_model(_understanding(), resp, answer).model_dump(mode="json")
    # 원문이 손실·변형 없이 그대로 담김
    assert payload["top_events"][0]["canonical_title"] == "<b>실적</b> & \"발표\""
    assert payload["answer_text"] == "정상 <b>텍스트</b>"


def test_fallback_report_json_conforms_to_schema():
    payload = rr.fallback_report_json(_understanding())
    assert payload["data_limited"] is True
    assert "데이터 제한" in (payload["note"] or "")
    assert payload["top_events"] == []
    assert payload["answer_text"] == ""
    assert "overall_gauge" in payload and "total" in payload["overall_gauge"]
