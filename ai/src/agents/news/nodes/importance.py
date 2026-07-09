# nodes/importance.py
"""중요도 노드(얇게) — event_id 가 배정된 기사를 이벤트별로 묶어 importance 를 계산·반영한다(TASK 06).

노드는 묶기·순회·반영만 담당하는 얇은 껍데기다(CLAUDE.md §2-2). 가중치·감쇠·합산 계산은
services/importance.py 가 한다. 이 노드에 공식·테이블을 두지 않는다.

⚠️ backend 를 직접 호출하지 않는다 — 기존 이벤트 통계는 주입된 EventArticleStatsProvider 로만
   얻는다(절대규칙 1). 미주입 시 기본 provider(None 반환)로 동작해 배치 기사만으로 계산한다(신규
   이벤트는 정확, 편입 이벤트는 근사). 실제 조회 provider 는 TASK 08 이 주입한다.
⚠️ importance 는 LLM 이 아니라 객관 신호의 결정적 계산이다 — 이 경로 어디에도 LLM 호출이 없다.
   감성 분포(긍/중/부 건수)는 여기서 집계·저장하지 않는다(정렬용 스칼라 하나만, CLAUDE.md §5).
"""
from __future__ import annotations

import logging

import src.agents.news.services.importance as importance

logger = logging.getLogger(__name__)


def importance_node(state: dict, provider=None) -> dict:
    """event_id 가 배정된 기사를 이벤트별로 묶어 importance 를 계산하고 반영한다.

    - 영향 이벤트 = 이번 배치 기사들의 event_id 집합(신규 + 편입된 기존 이벤트 모두 포함 — 편입 기사도
      event_id 를 가지므로 자연히 포함). event_id 없는 기사(병합 skip)는 대상 아님.
    - 각 이벤트: provider.get_event_article_stats(event_id)(미주입 시 None) → compute_importance.
    - 모든 영향 이벤트: state["importance_by_event_id"][event_id]=score 로 실어 TASK 08 이 신규뿐
      아니라 편입(기존) 이벤트에도 importance 를 반영하게 한다(키=canonical_id, 값=점수).
    - 신규 이벤트(state["events_by_id"] 에 있는 것): 그 Event.importance 에 직접 반영.
    - 한 이벤트 계산이 실패해도 로깅 후 그 이벤트만 skip, 나머지는 계속한다(실패 격리, §7).
    - 대상(event_id 배정 기사) 0건이면 예외 없이 그대로 통과한다(환각 금지, §2-5).
    """
    articles = state.get("articles") or []
    events_by_id: dict = state.get("events_by_id") or {}
    importance_by_event_id: dict = state.setdefault("importance_by_event_id", {})

    # 이벤트별로 이번 배치 기사를 묶는다(event_id 없는 기사 = 병합 skip → 대상 아님).
    grouped: dict[str, list] = {}
    for article in articles:
        if article.event_id:
            grouped.setdefault(article.event_id, []).append(article)

    if not grouped:
        logger.info("importance_node: event_id 배정 기사 0건 — 계산 없이 통과")
        return state

    base_provider = (
        provider if provider is not None else importance.DefaultEventArticleStatsProvider()
    )

    computed = 0
    for event_id, event_articles in grouped.items():
        try:
            existing = base_provider.get_event_article_stats(event_id)
            score = importance.compute_importance(event_articles, existing)
        except Exception as exc:  # 한 이벤트 실패가 파이프라인을 죽이지 않도록 격리(§7)
            logger.warning("importance 계산 실패, skip: event_id=%s (%s)", event_id, exc)
            continue

        # 모든 영향 이벤트(신규+편입)에 실어 TASK 08 이 편입 이벤트에도 반영하게 한다.
        importance_by_event_id[event_id] = score
        # 신규 이벤트는 이번 배치가 만든 Event 객체에 직접 채운다(편입 이벤트는 Event 객체가 없음).
        event = events_by_id.get(event_id)
        if event is not None:
            event.importance = score
        computed += 1

    logger.info(
        "importance_node: %d/%d개 이벤트 importance 계산(provider=%s)",
        computed, len(grouped), type(base_provider).__name__,
    )
    return state
