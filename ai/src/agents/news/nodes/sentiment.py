# nodes/sentiment.py
"""감성 노드(얇게) — 본문 있는 기사만 KR-FinBert 로 감성 판정하고 Article 에 반영한다.

TASK 04. 노드는 순회·분기·반영만 하는 얇은 껍데기다(CLAUDE.md §2-2). 모델 로드·추론·라벨 매핑은
services/finbert.py 가 한다. transformers·토크나이저를 이 노드에 두지 않는다(§3.3-6).

감성은 전용 모델만 판정한다 — 이 경로 어디에도 LLM(services/llm.py) 호출이 없다(CLAUDE.md §2-4).
본문 없는 기사(no_content/failed)는 제목만으로 추론하지 않고 sentiment=None 으로 skip(환각 금지, §2-5).
"""
from __future__ import annotations

import logging

import services.finbert as finbert

logger = logging.getLogger(__name__)


def sentiment_node(state: dict) -> dict:
    """state["articles"] 를 순회하며 본문 있는 기사만 감성 판정 → Article.sentiment/sentiment_score 반영.

    - crawl_status == "success"(본문 있음) 기사만 대상. Article.content(summary 아님)로 판정한다.
    - no_content/failed 는 skip: sentiment=None, sentiment_score=None 유지(제목 추론 금지, §4.1).
    - 본문 있는 기사들을 모아 finbert.classify_batch 로 한 번에 처리하고 순서로 짝지어 반영한다(처리량).
    - 한 기사 판정이 실패(None)해도 로깅 후 sentiment=None 으로 두고 나머지는 계속한다(실패 격리, §7).
    - crawl_status/content_available 는 여기서 바꾸지 않는다(감성은 상태를 소비만 함).
    - 분석 대상 0건·본문 있는 기사 0건이면 예외 없이 그대로 통과한다(환각 금지, §2-5).
    """
    articles = state.get("articles") or []

    # 본문 있는 기사만 배치 대상으로 고른다(§4.1 표: success 만). 원 기사와 순서로 짝지으려 함께 보관.
    targets = [a for a in articles if a.crawl_status == "success" and a.content]
    if not targets:
        logger.info("sentiment_node: 본문 있는 기사 0건 — 감성 판정 없이 통과")
        return state

    texts = [a.content for a in targets]
    try:
        results = finbert.classify_batch(texts)
    except Exception as exc:  # 서비스가 배치를 내부 격리하지만, 노드도 파이프라인을 죽이지 않게 방어(§7)
        logger.warning("감성 배치 실패, 전체 skip(파이프라인 계속): %s", exc)
        return state

    scored = 0
    for article, result in zip(targets, results):
        if result is None:  # 빈 입력·매핑 밖 라벨·추론 실패 = 감성 없음(None 유지)
            logger.info("감성 판정 skip(결과 없음): url=%s", article.url)
            continue
        article.sentiment = result.sentiment
        article.sentiment_score = result.score
        scored += 1

    logger.info("sentiment_node: %d/%d건 감성 판정 완료", scored, len(targets))
    return state
