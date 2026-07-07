# tests/test_answer_generator.py — ④ 답변생성(TASK 09) 테스트 (mock 기반)
"""근거 news_id 부착·환각 필터·데이터 제한·intent 초점·감성 미판정을 검증한다.

실제 LLM·backend 는 부르지 않는다 — services.llm.complete 와 query_client 를 monkeypatch 한다.
"""
from __future__ import annotations

import json

import services.answer_generator as ag
import services.backend.query_client as query_client
import services.llm as llm
from schemas.event import Event
from schemas.query import QueryIntent, QueryUnderstanding
from schemas.report import ArticleRef, SentimentGauge
from schemas.response import EventWithArticles, SubjectQueryResponse


def _event(cid, title, importance):
    return Event(canonical_id=cid, canonical_title=title, importance=importance)


def _ewa(cid, title, importance, arts, count=None):
    articles = [ArticleRef(news_id=n, summary=s, url=f"https://x/{n}") for n, s in arts]
    return EventWithArticles(event=_event(cid, title, importance),
                             article_count=count if count is not None else len(articles),
                             articles=articles,
                             gauge=SentimentGauge(positive=3, neutral=1, negative=1))


def _response(events, found=True):
    return SubjectQueryResponse(subject="삼성전자", subject_found=found, events=events)


def _understanding(intent=QueryIntent.SUMMARY):
    return QueryUnderstanding(companies=["삼성전자"], period_days=7, intent=intent,
                              original_question="삼성전자 요약")


def _mock_llm(monkeypatch, payload, capture=None):
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)

    def fake(messages, **kwargs):
        if capture is not None:
            capture["messages"] = messages
            capture["kwargs"] = kwargs
        return text

    monkeypatch.setattr(llm, "complete", fake)


def _no_ondemand(monkeypatch):
    monkeypatch.setattr(query_client, "get_articles_by_event",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("대표 소수로 근거가 닫혔어야 함")))


def test_answer_attaches_only_real_evidence(monkeypatch):
    _no_ondemand(monkeypatch)
    resp = _response([
        _ewa("e1", "4분기 실적 발표", 9.0, [(101, "영업이익 상회"), (102, "목표가 상향")]),
        _ewa("e2", "HBM 공급 계약", 7.0, [(103, "품질승인 통과")]),
    ])
    # LLM 이 근거 밖 news_id(999)·event(zzz)를 섞어 내밀어도 걸러져야 한다(환각 방지).
    _mock_llm(monkeypatch, {"text": "실적과 HBM 이 흐름을 주도했습니다.",
                            "evidence_news_ids": [101, 103, 999],
                            "cited_event_ids": ["e1", "e2", "zzz"],
                            "data_limited": False})
    ans = ag.generate_answer(_understanding(), resp)
    assert ans.text
    assert set(ans.evidence_news_ids) == {101, 103}      # 999 제거
    assert set(ans.cited_event_ids) == {"e1", "e2"}      # zzz 제거
    assert ans.data_limited is False


def test_no_events_is_data_limited(monkeypatch):
    monkeypatch.setattr(llm, "complete",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("데이터 없으면 LLM 안 부름")))
    ans = ag.generate_answer(_understanding(), _response([], found=True))
    assert ans.data_limited is True
    assert "데이터 제한" in ans.text


def test_missing_subject_message_differs(monkeypatch):
    ans = ag.generate_answer(_understanding(), _response([], found=False))
    assert ans.data_limited is True
    assert "종목" in ans.text            # '없는 종목' 문구(뉴스 0건과 구분)


def test_intent_guidance_in_prompt(monkeypatch):
    _no_ondemand(monkeypatch)
    cap = {}
    resp = _response([_ewa("e1", "공유 사건", 9.0, [(1, "요약")])])
    _mock_llm(monkeypatch, {"text": "t", "evidence_news_ids": [1], "cited_event_ids": ["e1"]}, capture=cap)
    ag.generate_answer(_understanding(QueryIntent.RELATION), resp)
    system = cap["messages"][0]["content"]
    assert "서사" in system               # 관계 intent → 상세 서사 초점
    # 답변 생성 토큰/온도가 전달됨
    assert cap["kwargs"].get("max_tokens")


def test_llm_parse_failure_degrades(monkeypatch):
    _no_ondemand(monkeypatch)
    resp = _response([_ewa("e1", "실적", 9.0, [(1, "요약")])])
    _mock_llm(monkeypatch, "not-json")
    ans = ag.generate_answer(_understanding(), resp)
    assert ans.data_limited is True       # 근거는 있으나 서술 실패 → 정직한 데이터 제한
    assert "데이터 제한" in ans.text


def test_ondemand_fetch_when_representative_empty(monkeypatch):
    # 대표 소수가 비었지만 총 건수>0 → on-demand 로 근거 보강.
    called = {}

    def fake_by_event(event_id, limit):
        called["event_id"] = event_id
        return [ArticleRef(news_id=201, summary="온디맨드 근거", url="https://x/201")]

    monkeypatch.setattr(query_client, "get_articles_by_event", fake_by_event)
    resp = _response([_ewa("e9", "깊은 근거 필요", 9.0, [], count=5)])
    _mock_llm(monkeypatch, {"text": "t", "evidence_news_ids": [201], "cited_event_ids": ["e9"]})
    ans = ag.generate_answer(_understanding(), resp)
    assert called["event_id"] == "e9"
    assert ans.evidence_news_ids == [201]
