# tests/test_rss.py
"""utils/rss_parser.py + services/rss.py 테스트 (mock 기반, 실제 네트워크 없음).

RSS XML은 픽스처 문자열로 대체하고, 피드 요청(services.rss._fetch_feed)은 mock한다.
"""
from __future__ import annotations

from datetime import datetime

import pytest

import src.agents.news.services.rss as rss
from src.agents.news.utils.html_parser import extract_text
from src.agents.news.utils.rss_parser import parse_rss

# --- 픽스처 XML ------------------------------------------------------------
RSS_2 = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>샘플경제</title>
    <item>
      <title>삼성전자 HBM 공급 계약</title>
      <link>https://news.example.com/a/1?utm_source=rss&amp;utm_medium=feed</link>
      <pubDate>Mon, 06 Jul 2026 09:00:00 +0900</pubDate>
      <description>요약 텍스트(사용 안 함)</description>
    </item>
    <item>
      <title>원달러 환율 급등</title>
      <link>https://news.example.com/a/2</link>
      <pubDate>bad-date-string</pubDate>
    </item>
    <item>
      <title>본문 링크 없는 기사</title>
      <pubDate>Mon, 06 Jul 2026 10:00:00 +0900</pubDate>
    </item>
    <item>
      <link>https://news.example.com/a/3</link>
      <pubDate>Mon, 06 Jul 2026 11:00:00 +0900</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>샘플아톰</title>
  <entry>
    <title>한국경제 이벤트</title>
    <link rel="alternate" href="https://atom.example.com/b/1"/>
    <link rel="self" href="https://atom.example.com/self"/>
    <published>2026-07-06T09:30:00+09:00</published>
    <summary>요약</summary>
  </entry>
</feed>
"""


# --- parse_rss -------------------------------------------------------------
def test_parse_rss2_basic():
    items = parse_rss(RSS_2, "샘플경제")
    # link 없는 항목, title 없는 항목은 skip → 유효 2건.
    assert len(items) == 2
    first = items[0]
    assert first["title"] == "삼성전자 HBM 공급 계약"
    assert first["link"].startswith("https://news.example.com/a/1")
    assert first["publisher"] == "샘플경제"
    assert isinstance(first["published_at"], datetime)
    assert first["published_at"].tzinfo is not None  # aware


def test_parse_rss_bad_date_is_none():
    items = parse_rss(RSS_2, "샘플경제")
    # title/link는 있지만 pubDate가 파싱 불가("bad-date-string")한 항목 → published_at None(예외 없이).
    no_date = [it for it in items if it["published_at"] is None]
    assert no_date and no_date[0]["link"].endswith("/a/2")


def test_parse_atom_uses_alternate_href():
    items = parse_rss(ATOM, "샘플아톰")
    assert len(items) == 1
    assert items[0]["link"] == "https://atom.example.com/b/1"  # rel=self가 아니라 alternate


def test_parse_rss_broken_xml_returns_empty():
    assert parse_rss("<rss><channel><item>", "깨진피드") == []


# --- normalize_url ---------------------------------------------------------
def test_normalize_url_strips_tracking_and_fragment():
    a = rss.normalize_url("https://News.Example.com/a/1?utm_source=x&id=5#frag")
    b = rss.normalize_url("https://news.example.com/a/1?id=5")
    assert a == b
    assert "utm_source" not in a
    assert "#frag" not in a


def test_normalize_url_default_port_and_query_order():
    a = rss.normalize_url("https://news.example.com:443/a?b=2&a=1")
    b = rss.normalize_url("https://news.example.com/a?a=1&b=2")
    assert a == b


# --- collect_articles (피드 단위 실패 격리 + 중복 제거) ---------------------
def test_collect_articles_feed_isolation_and_dedupe(monkeypatch):
    feeds = {
        "https://feed-ok.example/rss": RSS_2,
        "https://feed-dup.example/rss": RSS_2,   # 동일 기사 → 중복 제거되어야
        "https://feed-bad.example/rss": None,     # 요청 실패 시뮬레이션
    }
    monkeypatch.setattr(rss, "RSS_CANDIDATES", [
        ("언론사A", "https://feed-ok.example/rss"),
        ("언론사B", "https://feed-dup.example/rss"),
        ("언론사C", "https://feed-bad.example/rss"),
    ])

    def fake_fetch(url):
        xml = feeds[url]
        if xml is None:
            raise OSError("connection refused")
        return xml.encode("utf-8")

    monkeypatch.setattr(rss, "_fetch_feed", fake_fetch)

    articles = rss.collect_articles()

    # RSS_2의 유효 링크 2건이 두 피드에서 와도 URL 정규화로 2건만 남는다.
    assert len(articles) == 2
    for art in articles:
        assert art.crawl_status == "pending"
        assert art.content is None
        assert art.content_available is False
        assert art.publisher in ("언론사A", "언론사B")


def test_collect_articles_empty_when_all_feeds_fail(monkeypatch):
    monkeypatch.setattr(rss, "RSS_CANDIDATES", [("X", "https://x.example/rss")])
    monkeypatch.setattr(rss, "_fetch_feed", lambda url: (_ for _ in ()).throw(OSError("boom")))

    assert rss.collect_articles() == []  # 예외 없이 빈 리스트


# --- extract_text ----------------------------------------------------------
def test_extract_text_strips_tags_and_script():
    html = """
    <html><head><style>.x{color:red}</style></head>
    <body>
      <script>alert('x')</script>
      <nav>메뉴 링크</nav>
      <p>본문 첫 문단.</p>
      <div>본문 둘째 문단.</div>
    </body></html>
    """
    text = extract_text(html)
    assert "본문 첫 문단." in text
    assert "본문 둘째 문단." in text
    assert "alert" not in text          # script 내용 제거
    assert "color:red" not in text      # style 내용 제거
    assert "<" not in text and ">" not in text  # 원시 태그 없음
