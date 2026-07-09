# nodes/embedding.py
"""임베딩 노드(얇게) — summary 있는 기사만 arctic 임베딩해 Article.embedding 에 반영한다(TASK 05).

노드는 순회·분기·반영만 하는 얇은 껍데기다(CLAUDE.md §2-2). 모델 로드·인코딩은 services/embedder.py
가 한다. sentence-transformers 를 이 노드에 두지 않는다. 임베딩 대상은 Article.summary(요약)이며,
요약이 없는 기사는 임베딩하지 않는다(embedding=None → 병합 단계가 skip, §4.1).
"""
from __future__ import annotations

import logging

import src.agents.news.services.embedder as embedder

logger = logging.getLogger(__name__)


def embedding_node(state: dict) -> dict:
    """state["articles"] 를 순회하며 summary 있는 기사만 임베딩 → Article.embedding 반영(순서 일치).

    - summary 가 없거나 빈 기사는 대상에서 제외(embedding=None 유지). 노드는 순서만 담당.
    - 대상 요약들을 embedder.embed_batch 로 한 번에 처리하고, 원 기사와 순서로 짝지어 반영한다(처리량, 계약: 순서 일치).
    - 한 기사 임베딩이 실패(None)해도 로깅 후 skip(embedding=None), 나머지는 계속한다(실패 격리, §7).
    - 배치 자체가 실패해도 파이프라인을 죽이지 않는다(서비스가 내부 fallback 하지만 노드도 방어).
    - 대상 0건이면 예외 없이 그대로 통과한다(환각 금지, §2-5).
    """
    articles = state.get("articles") or []

    # summary 있는 기사만 배치 대상으로 고른다. 원 기사와 순서로 짝지으려 함께 보관.
    targets = [a for a in articles if a.summary and a.summary.strip()]
    if not targets:
        logger.info("embedding_node: summary 있는 기사 0건 — 임베딩 없이 통과")
        return state

    texts = [a.summary for a in targets]
    try:
        vectors = embedder.embed_batch(texts)
    except Exception as exc:  # 서비스가 배치를 내부 격리하지만, 노드도 파이프라인을 죽이지 않게 방어(§7)
        logger.warning("임베딩 배치 실패, 전체 skip(파이프라인 계속): %s", exc)
        return state

    embedded = 0
    for article, vector in zip(targets, vectors):
        if vector is None:  # 빈 입력·인코딩 실패 = 임베딩 없음(None 유지 → 병합 skip)
            logger.info("임베딩 skip(결과 없음): url=%s", article.url)
            continue
        article.embedding = vector
        embedded += 1

    logger.info("embedding_node: %d/%d건 임베딩 완료", embedded, len(targets))
    return state
