# nodes/extract.py
"""추출 노드(얇게) — 분석 대상 기사를 순회하며 llm.extract 를 호출한다.

노드는 순서만 담당하는 얇은 껍데기다(CLAUDE.md §2-2). 모델 호출·Tool Calling·파싱은
services/llm.py 가 한다. 본문 크롤링도 llm.extract 내부의 fetch_article Tool 이 수행하므로,
이 노드는 services/crawler.py 를 import 하지 않는다(TASK 02 §4.2, TASK 03 §3.3-4).
"""
from __future__ import annotations

import logging

import src.agents.news.services.llm as llm

logger = logging.getLogger(__name__)


def extract_node(state: dict) -> dict:
    """state["articles"] 를 순회하며 각 기사에 llm.extract 를 호출한다.

    - Article: summary·crawl_status·content_available·(확보 시)content 를 갱신한다.
      (crawl 관련 필드는 extract 가 이미 기록하므로 여기서는 summary 만 반영한다.)
    - ExtractResult(개체·events·event_date·source_type)는 state["extracts_by_url"] 에 url 기준으로 싣는다.
    - 한 기사의 추출이 실패(None)하거나 예외를 던져도 로깅 후 skip, 파이프라인은 계속한다(CLAUDE.md §7).
    - 분석 대상 0건이면 예외 없이 그대로 통과한다(환각 금지, CLAUDE.md §2-5).
    """
    articles = state.get("articles") or []
    extracts_by_url: dict = state.setdefault("extracts_by_url", {})

    extracted = 0
    for article in articles:
        try:
            result = llm.extract(article)
        except Exception as exc:  # 한 기사 실패가 파이프라인을 죽이지 않도록 격리
            logger.warning("추출 실패, skip: url=%s (%s)", article.url, exc)
            continue

        if result is None:  # llm.extract 의 폴백(본문 직접 확보 재시도)까지 실패한 skip 신호
            logger.info("추출 skip(결과 없음): url=%s status=%s", article.url, article.crawl_status)
            continue

        article.summary = result.summary
        extracts_by_url[str(article.url)] = result
        extracted += 1

    logger.info("extract_node: %d/%d건 추출 완료", extracted, len(articles))
    return state
