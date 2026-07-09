# nodes/crawl.py
"""수집 노드(얇게) — RSS 수집·중복 제거만. 본문 크롤링은 하지 않는다.

본문 조회 책임은 다음 단계 extract의 Tool Calling(fetch_article → services/crawler.py)으로
이동했다. 이 노드는 "무엇을 분석 대상 목록에 올릴지"(수집·중복 제거)만 결정한다(CLAUDE.md §2-2).

⚠️ services/crawler.py를 import 하지 않는다(본문 크롤링 금지). services/rss.py만 호출한다.
"""
from __future__ import annotations

import logging
from datetime import datetime

import src.agents.news.services.backend.dedup_client as dedup_client
import src.agents.news.services.rss as rss
from src.agents.news.config import CRAWL_MAX_ARTICLES, DEDUP_SKIP_EXISTING

logger = logging.getLogger(__name__)


def crawl_node(state: dict) -> dict:
    """RSS 수집·중복 제거만. 본문 조회는 extract의 Tool Calling에서 수행.

    state["articles"]에 메타데이터 Article 리스트를 실어 넘긴다. 수집 0건이어도
    예외 없이 빈 리스트를 넘긴다(환각 금지, CLAUDE.md §2-5).

    cap(CRAWL_MAX_ARTICLES) 전에 **이미 저장된 url을 걸러낸다**(DEDUP_SKIP_EXISTING): 매시간
    피드 전체를 재처리하지 않고 신규만 처리해, cap이 '유실 방지선'이 아니라 '회차당 처리량 상한'이
    되게 한다(밀린 신규는 다음 회차에 이어 처리). backend 미연결 시엔 걸러내지 않고 전부 처리(degrade).
    """
    articles = rss.collect_articles()

    if DEDUP_SKIP_EXISTING and articles:
        articles = _drop_existing(articles)

    if CRAWL_MAX_ARTICLES:
        # 발행시각 최신순(published_at desc)으로 상한 적용. 미상(None)은 뒤로 민다.
        articles.sort(key=_published_sort_key, reverse=True)
        articles = articles[:CRAWL_MAX_ARTICLES]
        logger.info("CRAWL_MAX_ARTICLES=%d 적용 → %d건", CRAWL_MAX_ARTICLES, len(articles))

    logger.info("crawl_node: 분석 대상 %d건 확정", len(articles))
    state["articles"] = articles
    return state


def _drop_existing(articles: list) -> list:
    """이미 backend 에 저장된 url 기사를 제외(신규만 남김). backend 실패 시 원본 그대로(degrade).

    dedup_client 가 None(=조회 실패)이면 걸러내지 않는다 — 새 기사를 놓치느니 중복 재처리(멱등)를 택한다.
    """
    urls = [str(a.url) for a in articles]
    existing = dedup_client.get_existing_urls(urls)
    if existing is None:  # 조회 실패 → 필터 미적용
        return articles
    filtered = [a for a in articles if str(a.url) not in existing]
    logger.info(
        "crawl_node: dedup — 수집 %d건 중 신규 %d건(이미 저장 %d건 제외)",
        len(articles), len(filtered), len(articles) - len(filtered),
    )
    return filtered


def _published_sort_key(article) -> tuple[int, float]:
    """정렬 키. published_at 없는 기사는 (0, 0.0)으로 뒤로. None 비교 오류를 피한다."""
    dt: datetime | None = article.published_at
    if dt is None:
        return (0, 0.0)
    return (1, dt.timestamp())
