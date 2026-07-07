# tests/test_llm.py
"""services/llm.py 추출 테스트 (mock 기반, 실제 모델·네트워크 호출 없음).

Qwen3 호출(_chat_completion)과 본문 크롤(crawler.fetch_content)을 monkeypatch 해
Tool Calling 분기·Pydantic 강제·source_type 결정·URL 화이트리스트·event_date 정규화를 검증한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import services.crawler as crawler
import services.llm as llm
from config import EXTRACT_SYSTEM_PROMPT
from schemas.article import Article, EventCandidate, ExtractResult, SourceType

URL = "https://news.example.com/a/1"


def _article(**kw) -> Article:
    base = dict(title="삼성전자 HBM 공급 계약", url=URL, publisher="샘플경제")
    base.update(kw)
    return Article(**base)


# ---- OpenAI 형태 응답 빌더 -------------------------------------------------
def _final_msg(payload: dict | str) -> dict:
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _tool_msg(url: str, call_id: str = "c1") -> dict:
    return {"choices": [{"message": {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": "fetch_article", "arguments": json.dumps({"url": url})},
        }],
    }}]}


def _script(monkeypatch, responses: list[dict]):
    """_chat_completion 이 responses 를 순서대로 돌려주도록 교체."""
    it = iter(responses)

    def fake(messages, tools=None, tool_choice="auto"):
        return next(it)

    monkeypatch.setattr(llm, "_chat_completion", fake)


def _crawl(monkeypatch, content, status, available):
    called = {"n": 0, "urls": []}

    def fake(url):
        called["n"] += 1
        called["urls"].append(url)
        return crawler.CrawlResult(content=content, crawl_status=status, content_available=available)

    monkeypatch.setattr(crawler, "fetch_content", fake)
    return called


_GOOD = {
    "summary": "삼성전자가 HBM 공급 계약을 체결했다.",
    "companies": ["삼성전자"],
    "people": [],
    "industries": ["반도체"],
    "events": [{"title": "HBM 공급 계약", "confidence": 0.9}],
    "countries": ["대한민국"],
    "keywords": ["HBM"],
    "event_date": None,
}


# ---- Tool 0회(제목만) 경로 -------------------------------------------------
def test_extract_title_only_no_tool(monkeypatch):
    _script(monkeypatch, [_final_msg(_GOOD)])
    spy = _crawl(monkeypatch, "x", "success", True)  # 호출되면 안 됨

    result = llm.extract(_article())

    assert result is not None
    assert result.source_type is SourceType.TITLE_ONLY
    assert spy["n"] == 0                       # Tool 미호출 → 크롤러 안 불림
    assert isinstance(result.events[0], EventCandidate)
    assert result.events[0].title == "HBM 공급 계약"
    assert 0.0 <= result.events[0].confidence <= 1.0


# ---- 본문 확보(success) 경로 -----------------------------------------------
def test_extract_with_body_success(monkeypatch):
    _script(monkeypatch, [_tool_msg(URL), _final_msg(_GOOD)])
    spy = _crawl(monkeypatch, "본문 " * 100, "success", True)

    article = _article()
    result = llm.extract(article)

    assert result is not None
    assert result.source_type is SourceType.ARTICLE
    assert spy["n"] == 1 and spy["urls"] == [URL]
    assert article.crawl_status == "success"
    assert article.content is not None
    assert article.content_available is True


def test_fetch_article_returns_final_url(monkeypatch):
    _crawl(monkeypatch, "본문", "success", True)
    out = llm.fetch_article(URL, URL)
    assert out["final_url"] == URL
    assert out["crawl_status"] == "success"


# ---- no_content(속보) 경로 -------------------------------------------------
def test_extract_no_content_is_title_only(monkeypatch):
    _script(monkeypatch, [_tool_msg(URL), _final_msg(_GOOD)])
    _crawl(monkeypatch, None, "no_content", False)

    article = _article()
    result = llm.extract(article)

    assert result is not None
    assert result.source_type is SourceType.TITLE_ONLY
    assert result.summary == "삼성전자 HBM 공급 계약 (본문 없음)"
    assert article.crawl_status == "no_content"
    assert article.content_available is False


# ---- failed 경로 -----------------------------------------------------------
def test_extract_failed_returns_none(monkeypatch):
    _script(monkeypatch, [_tool_msg(URL), _final_msg(_GOOD)])
    _crawl(monkeypatch, None, "failed", False)

    article = _article()
    result = llm.extract(article)

    assert result is None                      # 추출 시도하지 않고 skip
    assert article.crawl_status == "failed"


# ---- URL 화이트리스트(§3.2-2) ---------------------------------------------
def test_fetch_article_rejects_foreign_url(monkeypatch):
    spy = _crawl(monkeypatch, "본문", "success", True)

    out = llm.fetch_article("http://127.0.0.1:8000/news/cleanup", URL)

    assert spy["n"] == 0                        # 크롤러가 아예 안 불림
    assert out["crawl_status"] == "failed"
    assert out["content"] is None


def test_extract_foreign_url_not_crawled(monkeypatch):
    # LLM 이 오염된 본문에 속아 다른 URL 을 부르면 그 URL 은 절대 크롤링되지 않는다(화이트리스트 거부).
    # 1차 경로는 None 이 되지만, 폴백이 '이 기사 URL'로만 본문을 직접 확보해 회복한다.
    _script(monkeypatch, [_tool_msg("http://backend:8000/news/cleanup"),
                          _final_msg(_GOOD), _final_msg(_GOOD)])
    spy = _crawl(monkeypatch, "본문 " * 100, "success", True)

    article = _article()
    result = llm.extract(article)

    # 크롤러는 오직 이 기사 URL 로만 불린다. 오염된 외부 URL 은 결코 크롤되지 않는다(화이트리스트 유지).
    assert "http://backend:8000/news/cleanup" not in spy["urls"]
    assert spy["urls"] == [URL]
    # 폴백이 본문을 직접 확보해 추출을 회복한다.
    assert result is not None
    assert result.source_type is SourceType.ARTICLE
    assert article.content_available is True


# ---- 폴백: 1차 None(파싱·크롤 실패) → 본문 직접 확보로 회복 ------------------
def test_fallback_recovers_after_parse_failure(monkeypatch):
    # 제목만 경로에서 파싱이 2회 실패(1차 None) → 폴백이 본문을 직접 확보해 재추출에 성공한다.
    _script(monkeypatch, [_final_msg("깨진1"), _final_msg("깨진2"), _final_msg(_GOOD)])
    spy = _crawl(monkeypatch, "본문 " * 100, "success", True)

    article = _article()
    result = llm.extract(article)

    assert result is not None
    assert result.source_type is SourceType.ARTICLE   # 본문 기반으로 회복
    assert spy["urls"] == [URL]                        # 폴백은 이 기사 URL 로만 크롤
    assert article.content_available is True


def test_fallback_no_content_stays_skip(monkeypatch):
    # 폴백이 본문을 확보하지 못하면(no_content) 지어내지 않고 skip(None) 유지(환각 금지, §2-5).
    _script(monkeypatch, [_final_msg("깨진1"), _final_msg("깨진2")])
    _crawl(monkeypatch, None, "no_content", False)

    assert llm.extract(_article()) is None


# ---- Tool 루프 상한(§3.2-4) ------------------------------------------------
def test_tool_loop_capped(monkeypatch):
    from config import EXTRACT_MAX_TOOL_CALLS

    def fake(messages, tools=None, tool_choice="auto"):
        # tools 가 제거되면(상한 도달) 최종 답을 낸다. 그 전에는 계속 tool 을 부른다.
        if tools is None:
            return _final_msg(_GOOD)
        return _tool_msg(URL)

    monkeypatch.setattr(llm, "_chat_completion", fake)
    spy = _crawl(monkeypatch, "본문 " * 100, "success", True)

    result = llm.extract(_article())

    assert result is not None
    assert spy["n"] == EXTRACT_MAX_TOOL_CALLS   # 상한을 넘겨 부르지 않는다


# ---- 파싱 실패 → 1회 재시도 → skip ----------------------------------------
def test_validation_error_retry_then_skip(monkeypatch):
    # 제목만 경로에서 파싱이 2회 실패한다. 폴백이 본문을 직접 확보하려 해도 크롤이 실패하면
    # 지어내지 않고 skip(None) 한다(환각 금지 — 폴백은 회복 시도일 뿐 없는 본문을 만들지 않는다).
    _script(monkeypatch, [_final_msg("그냥 텍스트, JSON 아님"), _final_msg("여전히 JSON 아님")])
    _crawl(monkeypatch, None, "failed", False)

    assert llm.extract(_article()) is None


def test_validation_error_retry_succeeds(monkeypatch):
    # 최초 깨짐 → 재시도에서 유효 JSON → 결과 반환.
    _script(monkeypatch, [_final_msg("깨진 출력"), _final_msg(_GOOD)])
    _crawl(monkeypatch, "x", "success", True)

    result = llm.extract(_article())
    assert result is not None
    assert result.summary.startswith("삼성전자")


# ---- 감성/영향도 부재 ------------------------------------------------------
def test_no_sentiment_or_importance_fields(monkeypatch):
    _script(monkeypatch, [_final_msg(_GOOD)])
    assert llm.extract(_article()) is not None

    fields = set(ExtractResult.model_fields)
    assert "sentiment" not in fields
    assert "importance" not in fields
    assert "score" not in fields


# ---- event_date 정규화(§3.2.1) --------------------------------------------
def test_event_date_naive_becomes_kst(monkeypatch):
    payload = dict(_GOOD, event_date="2026-07-05T00:00:00")   # naive
    _script(monkeypatch, [_final_msg(payload)])

    result = llm.extract(_article())

    assert result.event_date is not None
    assert result.event_date.tzinfo is not None
    assert result.event_date.utcoffset() == timedelta(hours=9)


def test_event_date_none_when_absent(monkeypatch):
    _script(monkeypatch, [_final_msg(_GOOD)])   # event_date=None
    result = llm.extract(_article())
    assert result.event_date is None


def test_to_kst_converts_other_tz():
    utc = datetime(2026, 7, 5, 0, 0, tzinfo=timezone.utc)
    kst = llm._to_kst(utc)
    assert kst.utcoffset() == timedelta(hours=9)
    assert kst.hour == 9   # 00:00 UTC == 09:00 KST


def test_to_kst_none():
    assert llm._to_kst(None) is None


# ---- 프롬프트 인젝션 방어(§3.1-6) 샘플 검증 --------------------------------
def test_system_prompt_has_injection_guards():
    p = EXTRACT_SYSTEM_PROMPT
    assert "<<<ARTICLE_DATA>>>" in p and "<<<END_ARTICLE_DATA>>>" in p   # 구획
    assert "무시" in p                                                    # 지시 무시 규칙
    # 감성/영향도를 요청하지 않는다.
    assert "감성" in p and "출력하지 않는다" in p


def test_user_prompt_wraps_title_as_data():
    prompt = llm._build_user_prompt(_article())
    assert "<<<ARTICLE_DATA>>>" in prompt
    assert "삼성전자 HBM 공급 계약" in prompt
    assert URL in prompt
