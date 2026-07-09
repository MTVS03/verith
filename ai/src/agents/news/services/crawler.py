# services/crawler.py
"""본문 크롤러 — 기사 URL 1건 → 본문 텍스트 + 상태. 재사용 함수(부수효과 없음).

⚠️ 다른 노드에서 직접 import·호출 금지. extract 단계의 fetch_article(url) Tool만
   내부에서 이 모듈을 호출한다(TASK 02 §3.5, TASK 03에서 배선).

⚠️ SSRF·자원 고갈 방어(하위 방어선): 넘겨받은 URL을 신뢰하지 않는다. 요청 전·리다이렉트
   매 홉마다 scheme·사설 IP(리다이렉트 최종지 포함)·응답 크기·Content-Type을 검사하고,
   하나라도 위반하면 요청하지 않고 failed로 반환한다(사유 로깅). Tool 인자 화이트리스트는
   TASK 03의 상위 방어이고, 이 검사는 그와 독립적으로 항상 도는 하위 방어다(다층 방어).

표준 라이브러리(urllib/http.client)만 사용한다. 리다이렉트는 자동 추적하지 않고 홉마다
직접 검사하며 따라간다(외부→내부 우회 차단).
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.agents.news.config import (
    ARTICLE_CONTENT_MAX_CHARS,
    CRAWL_ALLOWED_CONTENT_TYPES,
    CRAWL_ALLOWED_SCHEMES,
    CRAWL_BLOCK_PRIVATE_IPS,
    CRAWL_MAX_REDIRECTS,
    CRAWL_MAX_RESPONSE_BYTES,
    CRAWL_TIMEOUT,
    MAX_RETRIES,
    MIN_CONTENT_LEN,
    RETRY_BACKOFF,
    USER_AGENT,
)
from src.agents.news.utils.html_parser import extract_text

if TYPE_CHECKING:  # 런타임 결합 최소화. crawl_status는 런타임엔 평범한 str.
    from src.agents.news.schemas.article import CrawlStatus

logger = logging.getLogger(__name__)

_REDIRECT_CODES = {301, 302, 303, 307, 308}
_CHUNK = 65536


@dataclass
class CrawlResult:
    """fetch_content 반환. TASK 01 CrawlStatus / Article 필드와 정합.

    - 본문 정상(길이 >= MIN_CONTENT_LEN): content=텍스트, "success", content_available=True
    - 속보/본문 없음(길이 < MIN_CONTENT_LEN): content=None, "no_content", False
    - 요청 실패(타임아웃·4xx/5xx·차단·파싱불가): content=None, "failed", False
    """
    content: str | None
    crawl_status: "CrawlStatus"
    content_available: bool


class CrawlBlocked(Exception):
    """보안·정책 위반(scheme·사설 IP·크기·Content-Type). 재시도하지 않는다."""


class CrawlError(Exception):
    """일시/기타 실패(네트워크·HTTP 오류·파싱). 재시도 대상."""


def fetch_content(url: str) -> CrawlResult:
    """기사 URL 1건 → 본문 텍스트 + 상태.

    - HTML은 utils.html_parser.extract_text로 순수 텍스트화(원시 HTML 반환 안 함).
    - 텍스트는 ARTICLE_CONTENT_MAX_CHARS로 잘라 반환(저장 길이 상한).
    - 길이 >= MIN_CONTENT_LEN → success / < → no_content / 요청·파싱·차단 실패 → failed.
    - config의 타임아웃·재시도·USER_AGENT 적용. 예외는 삼키지 않고 로깅 후 failed 반환.
    - 부수효과 없음(저장 안 함).
    """
    try:
        html = _download_with_retry(url)
    except CrawlBlocked as exc:
        logger.warning("크롤 차단(SSRF/자원 방어): url=%s (%s)", url, exc)
        return CrawlResult(content=None, crawl_status="failed", content_available=False)
    except CrawlError as exc:
        logger.warning("크롤 실패: url=%s (%s)", url, exc)
        return CrawlResult(content=None, crawl_status="failed", content_available=False)

    text = extract_text(html)[:ARTICLE_CONTENT_MAX_CHARS]
    if len(text) >= MIN_CONTENT_LEN:
        return CrawlResult(content=text, crawl_status="success", content_available=True)
    # 짧으면 속보/본문 없음. 지어내지 않는다(환각 금지).
    return CrawlResult(content=None, crawl_status="no_content", content_available=False)


# ---------------------------------------------------------------------------
# 다운로드 (리다이렉트 직접 추적 + 홉마다 방어 검사)
# ---------------------------------------------------------------------------
def _download_with_retry(url: str) -> str:
    """네트워크·HTTP 오류는 재시도, 보안 차단(CrawlBlocked)은 즉시 전파(재시도 안 함)."""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return _download(url)
        except CrawlBlocked:
            raise  # 보안 결정은 재시도하지 않는다
        except (CrawlError, urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF)
                continue
            raise CrawlError(str(exc)) from exc
    raise CrawlError(str(last_exc))  # 도달 불가(방어)


def _download(url: str) -> str:
    """URL → HTML 텍스트. 리다이렉트를 홉마다 검사하며 최대 CRAWL_MAX_REDIRECTS까지 따라간다."""
    current = url
    for _ in range(CRAWL_MAX_REDIRECTS + 1):
        _validate_url(current)  # scheme + 사설 IP 검사. 위반 시 CrawlBlocked (요청 안 함).
        resp = _open(current)
        try:
            status = resp.status_code
            if status in _REDIRECT_CODES:
                location = resp.header("Location")
                if not location:
                    raise CrawlError(f"redirect without Location: {current}")
                current = urllib.parse.urljoin(current, location)
                continue
            if status != 200:
                raise CrawlError(f"HTTP {status}: {current}")

            ctype = (resp.header("Content-Type") or "").split(";")[0].strip().lower()
            if ctype and ctype not in CRAWL_ALLOWED_CONTENT_TYPES:
                raise CrawlBlocked(f"disallowed content-type: {ctype!r}")

            clen = resp.header("Content-Length")
            if clen is not None:
                try:
                    if int(clen) > CRAWL_MAX_RESPONSE_BYTES:
                        raise CrawlBlocked(f"content-length {clen} exceeds limit")
                except ValueError:
                    pass  # 잘못된 헤더는 스트리밍 상한으로 잡는다

            body = resp.read_limited(CRAWL_MAX_RESPONSE_BYTES)
            return body.decode(_charset(resp), errors="replace")
        finally:
            resp.close()
    raise CrawlError(f"too many redirects: {url}")


# ---------------------------------------------------------------------------
# URL 방어 검사
# ---------------------------------------------------------------------------
def _validate_url(url: str) -> None:
    """scheme·사설 IP 검사. 위반 시 CrawlBlocked. (호출 전/리다이렉트 최종지 모두 여기로.)"""
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in CRAWL_ALLOWED_SCHEMES:
        raise CrawlBlocked(f"scheme not allowed: {scheme!r}")

    if not CRAWL_BLOCK_PRIVATE_IPS:
        return

    host = parts.hostname
    if not host:
        raise CrawlBlocked("missing host")
    for ip in _resolve_ips(host):
        if _is_blocked_ip(ip):
            raise CrawlBlocked(f"blocked address {ip} for host {host!r}")


def _resolve_ips(host: str) -> list[str]:
    """호스트 → IP 문자열 목록. 리터럴 IP는 DNS 없이 그대로, 도메인은 getaddrinfo로 해소."""
    try:
        ipaddress.ip_address(host)
        return [host]  # 이미 리터럴 IP
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise CrawlError(f"DNS resolution failed for {host!r}: {exc}") from exc
    return list({info[4][0] for info in infos})


def _is_blocked_ip(ip: str) -> bool:
    """사설/루프백/링크로컬(169.254.169.254 메타데이터 포함)/예약/멀티캐스트/미지정 대역 차단."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # 해석 불가 주소는 안전하게 차단
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _charset(resp: "_Response") -> str:
    ctype = resp.header("Content-Type") or ""
    for part in ctype.split(";")[1:]:
        part = part.strip()
        if part.lower().startswith("charset="):
            return part.split("=", 1)[1].strip().strip('"') or "utf-8"
    return "utf-8"


# ---------------------------------------------------------------------------
# HTTP 전송 (테스트 시임: _open / _Response 를 mock)
# ---------------------------------------------------------------------------
class _Response:
    """단일 응답 래퍼. 리다이렉트를 자동 추적하지 않으므로 3xx도 그대로 노출한다.

    테스트는 _open을 대체해 이 객체(status_code/headers/reader)를 반환한다.
    """

    def __init__(self, status_code: int, headers=None, reader=None) -> None:
        self.status_code = int(status_code)
        self.headers = headers if headers is not None else {}
        self._reader = reader

    def header(self, name: str, default=None):
        """대소문자 무시 헤더 조회. http.client.HTTPMessage/dict 모두 지원."""
        get = getattr(self.headers, "get", None)
        if get is not None:
            val = get(name)  # HTTPMessage는 CI, dict는 CS
            if val is not None:
                return val
        try:
            items = self.headers.items()
        except AttributeError:
            return default
        for key, val in items:
            if key.lower() == name.lower():
                return val
        return default

    def read_limited(self, max_bytes: int) -> bytes:
        """스트리밍 누적이 상한을 넘으면 즉시 중단하고 CrawlBlocked(자원 고갈 방어)."""
        if self._reader is None:
            return b""
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = self._reader.read(_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise CrawlBlocked(f"response exceeds {max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)

    def close(self) -> None:
        reader = self._reader
        if reader is not None:
            try:
                reader.close()
            except Exception:
                pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """리다이렉트를 자동으로 따라가지 않는다. 3xx는 HTTPError로 올라와 _open이 잡는다."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _open(url: str) -> _Response:
    """단일 HTTP 요청(리다이렉트 미추적). 3xx/4xx/5xx도 _Response로 반환한다."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        resp = _OPENER.open(req, timeout=CRAWL_TIMEOUT)
        status = getattr(resp, "status", None) or resp.getcode()
        return _Response(status, resp.headers, resp)
    except urllib.error.HTTPError as exc:
        # 3xx(NoRedirect) 또는 4xx/5xx. HTTPError도 file-like(.code/.headers/.read).
        return _Response(exc.code, exc.headers, exc)
