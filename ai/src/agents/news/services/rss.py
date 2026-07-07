# services/rss.py
"""RSS 수집 + URL 정규화 + 중복 제거 → Article 메타데이터 리스트.

- 본문은 가져오지 않는다. 이 단계가 채우는 필드는 title/url/publisher/published_at 뿐이며
  content=None, crawl_status="pending", content_available=False 로 둔다(TASK 02 §3.4).
- 한 피드가 실패해도 나머지 피드는 계속 수집한다(피드 단위 격리, 예외 로깅. CLAUDE.md §7).
- 본문 크롤링은 이후 extract 노드의 fetch_article Tool이 services/crawler.py로 수행한다.
- DB 접근 없음: 외부 RSS만 읽고 저장하지 않는다(절대규칙 1).
"""
from __future__ import annotations

import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from pydantic import ValidationError

from config import MAX_RETRIES, RETRY_BACKOFF, RSS_CANDIDATES, RSS_TIMEOUT, USER_AGENT
from schemas.article import Article
from utils.rss_parser import parse_rss

logger = logging.getLogger(__name__)

# 정규화 시 제거하는 추적 파라미터. 같은 기사가 추적 파라미터만 달리해 중복 유입되는 것을 접는다.
_TRACKING_PARAMS = {
    "fbclid", "gclid", "gclsrc", "dclid", "igshid", "mc_cid", "mc_eid",
    "spm", "cmpid", "ncid", "yclid", "_ga",
}
_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_url(url: str) -> str:
    """중복 제거 키. 추적 파라미터(utm_*·fbclid 등)·fragment 제거, scheme/host 소문자화,
    기본 포트 제거, 쿼리 정렬. 표시용이 아니라 '같은 기사'를 같은 키로 접기 위한 정규형이다.
    """
    parts = urllib.parse.urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()

    netloc = host
    if parts.port is not None and parts.port != _DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{parts.port}"

    query_pairs = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_param(k)
    ]
    query_pairs.sort()
    query = urllib.parse.urlencode(query_pairs)

    path = parts.path or "/"
    # fragment은 항상 제거(마지막 인자 "").
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def _is_tracking_param(key: str) -> bool:
    k = key.lower()
    return k.startswith("utm_") or k in _TRACKING_PARAMS


def collect_articles() -> list[Article]:
    """RSS_CANDIDATES 전체 수집 → 파싱 → URL 정규화·중복 제거 → Article 메타데이터 리스트.

    반환 Article은 메타데이터만 채운다:
      title, url, publisher, published_at 세팅
      content=None, crawl_status="pending", content_available=False (분석 결과 필드 전부 None)
    피드 단위로 실패를 격리한다(한 피드 실패해도 나머지 계속, 예외 로깅).
    수집 0건이면 예외 없이 빈 리스트를 반환한다(환각 금지, CLAUDE.md §2-5).
    """
    articles: list[Article] = []
    seen: set[str] = set()

    for publisher, feed_url in RSS_CANDIDATES:
        try:
            xml = _fetch_feed(feed_url)
        except Exception as exc:  # 피드 요청 실패 격리
            logger.warning("RSS 피드 수집 실패, skip: %s (%s)", feed_url, exc)
            continue

        try:
            items = parse_rss(xml, publisher)
        except Exception as exc:  # 파싱 실패 격리(parse_rss는 자체적으로도 방어)
            logger.warning("RSS 피드 파싱 실패, skip: %s (%s)", feed_url, exc)
            continue

        for item in items:
            link = item.get("link")
            title = item.get("title")
            if not link or not title:
                continue
            key = normalize_url(link)
            if key in seen:
                continue
            seen.add(key)
            try:
                # 저장 URL도 정규형을 쓴다: url은 DB unique(1차 중복 차단) 키라,
                # 배치 간에도 추적 파라미터만 다른 같은 기사가 겹치지 않게 한다.
                article = Article(
                    title=title,
                    url=key,
                    publisher=publisher,
                    published_at=item.get("published_at"),
                    content=None,
                    crawl_status="pending",
                    content_available=False,
                )
            except ValidationError as exc:  # url이 유효하지 않은 항목 skip
                logger.warning("Article 생성 실패, skip: url=%s (%s)", link, exc)
                continue
            articles.append(article)

    logger.info("RSS 수집 완료: %d건(중복 제거 후)", len(articles))
    return articles


def _fetch_feed(feed_url: str) -> bytes:
    """피드 1건 요청(타임아웃·재시도). 실패 시 마지막 예외를 올린다(호출측이 피드 단위로 격리)."""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(feed_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=RSS_TIMEOUT) as resp:
                return resp.read()
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF)
                continue
    assert last_exc is not None
    raise last_exc
