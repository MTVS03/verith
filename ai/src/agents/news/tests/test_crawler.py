# tests/test_crawler.py
"""services/crawler.py 본문 크롤러 테스트 (mock 기반, 실제 네트워크 호출 없음).

전송 계층(crawler._open)을 대체해 상태 매핑(success/no_content/failed)과
SSRF·자원 고갈 방어(§3.5-6)를 검증한다. 리터럴 공인 IP 호스트를 써서 DNS 없이 돈다.
"""
from __future__ import annotations

import io

import pytest

import src.agents.news.services.crawler as crawler

# 리터럴 공인 IP → DNS 없이 _validate_url 통과(사설 아님).
PUBLIC = "http://93.184.216.34/article"


def _resp(status, headers, body=b""):
    return crawler._Response(status, headers, io.BytesIO(body))


@pytest.fixture(autouse=True)
def _fast_no_retry(monkeypatch):
    # 재시도 sleep 제거로 테스트를 빠르게. (실패 케이스가 backoff로 지연되지 않게)
    monkeypatch.setattr(crawler, "MAX_RETRIES", 0)
    monkeypatch.setattr(crawler.time, "sleep", lambda _s: None)


def _set_open(monkeypatch, fn):
    monkeypatch.setattr(crawler, "_open", fn)


# ---- 상태 매핑 -------------------------------------------------------------
def test_success_long_body(monkeypatch):
    body = ("<html><body><p>" + "가" * 500 + "</p></body></html>").encode()
    _set_open(monkeypatch, lambda url: _resp(200, {"Content-Type": "text/html"}, body))

    result = crawler.fetch_content(PUBLIC)

    assert result.crawl_status == "success"
    assert result.content_available is True
    assert result.content is not None and "가" in result.content


def test_short_body_is_no_content(monkeypatch):
    body = b"<html><body><p>%s</p></body></html>" % ("가" * 10).encode()
    _set_open(monkeypatch, lambda url: _resp(200, {"Content-Type": "text/html"}, body))

    result = crawler.fetch_content(PUBLIC)

    assert result.crawl_status == "no_content"
    assert result.content is None
    assert result.content_available is False


def test_boundary_min_content_len(monkeypatch):
    # 정확히 MIN_CONTENT_LEN 길이의 순수 텍스트 → success(경계 포함).
    n = crawler.MIN_CONTENT_LEN
    body = ("<html><body><p>" + "가" * n + "</p></body></html>").encode()
    _set_open(monkeypatch, lambda url: _resp(200, {"Content-Type": "text/html"}, body))

    result = crawler.fetch_content(PUBLIC)

    assert result.crawl_status == "success"
    assert len(result.content) == n


def test_http_5xx_is_failed(monkeypatch):
    _set_open(monkeypatch, lambda url: _resp(500, {"Content-Type": "text/html"}, b"err"))

    result = crawler.fetch_content(PUBLIC)

    assert result.crawl_status == "failed"
    assert result.content is None


def test_network_error_is_failed(monkeypatch):
    import urllib.error

    def boom(url):
        raise urllib.error.URLError("timed out")

    _set_open(monkeypatch, boom)

    result = crawler.fetch_content(PUBLIC)

    assert result.crawl_status == "failed"


# ---- SSRF·자원 고갈 방어 (§3.5-6) -----------------------------------------
def test_disallowed_scheme_no_request(monkeypatch):
    called = {"n": 0}

    def spy(url):
        called["n"] += 1
        return _resp(200, {"Content-Type": "text/html"}, b"x")

    _set_open(monkeypatch, spy)

    result = crawler.fetch_content("file:///etc/passwd")

    assert result.crawl_status == "failed"
    assert called["n"] == 0  # 요청 자체가 나가지 않아야 한다


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x",
    "http://10.0.0.5/x",
    "http://169.254.169.254/latest/meta-data/",  # 클라우드 메타데이터
    "http://[::1]/x",
])
def test_private_ip_blocked(monkeypatch, url):
    called = {"n": 0}

    def spy(u):
        called["n"] += 1
        return _resp(200, {"Content-Type": "text/html"}, b"x")

    _set_open(monkeypatch, spy)

    result = crawler.fetch_content(url)

    assert result.crawl_status == "failed"
    assert called["n"] == 0


def test_redirect_to_private_ip_blocked(monkeypatch):
    # 외부(공인 IP) → 302 → 사설 IP. 최종지 검사에서 거부되어야 한다(우회 차단).
    def one_hop(url):
        return _resp(302, {"Location": "http://127.0.0.1:8000/news/cleanup"})

    _set_open(monkeypatch, one_hop)

    result = crawler.fetch_content(PUBLIC)

    assert result.crawl_status == "failed"


def test_content_length_over_limit(monkeypatch):
    big = str(crawler.CRAWL_MAX_RESPONSE_BYTES + 1)
    _set_open(monkeypatch, lambda url: _resp(
        200, {"Content-Type": "text/html", "Content-Length": big}, b"<html>x</html>"))

    result = crawler.fetch_content(PUBLIC)

    assert result.crawl_status == "failed"


def test_streamed_body_over_limit(monkeypatch):
    # Content-Length 없이 스트림이 상한을 넘으면 누적 중 중단.
    monkeypatch.setattr(crawler, "CRAWL_MAX_RESPONSE_BYTES", 1000)
    body = b"<html><body>" + b"a" * 5000 + b"</body></html>"
    _set_open(monkeypatch, lambda url: _resp(200, {"Content-Type": "text/html"}, body))

    result = crawler.fetch_content(PUBLIC)

    assert result.crawl_status == "failed"


def test_disallowed_content_type_blocked(monkeypatch):
    _set_open(monkeypatch, lambda url: _resp(200, {"Content-Type": "image/png"}, b"\x89PNG"))

    result = crawler.fetch_content(PUBLIC)

    assert result.crawl_status == "failed"


def test_content_truncated_to_max_chars(monkeypatch):
    monkeypatch.setattr(crawler, "ARTICLE_CONTENT_MAX_CHARS", 300)
    body = ("<html><body><p>" + "가" * 5000 + "</p></body></html>").encode()
    _set_open(monkeypatch, lambda url: _resp(200, {"Content-Type": "text/html"}, body))

    result = crawler.fetch_content(PUBLIC)

    assert result.crawl_status == "success"
    assert len(result.content) == 300


def test_header_lookup_case_insensitive(monkeypatch):
    # 헤더 키 대소문자가 달라도 인식되어야 한다.
    body = ("<html><body><p>" + "나" * 400 + "</p></body></html>").encode()
    _set_open(monkeypatch, lambda url: _resp(200, {"content-type": "text/html"}, body))

    result = crawler.fetch_content(PUBLIC)

    assert result.crawl_status == "success"
