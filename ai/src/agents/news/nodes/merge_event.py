# nodes/merge_event.py
"""병합 노드(얇게) — 기사별로 편입/신규를 판정해 Article.event_id 를 배정한다(TASK 05).

노드는 순회·반영·이번 배치 이벤트 누적만 담당하는 얇은 껍데기다(CLAUDE.md §2-2). 점수·판정·canonical
생성은 services/event_merge.py 가 한다. 병합 단위는 기사 1건 → 이벤트 1개(Article.event_id 는 단일 필드).

⚠️ backend 를 직접 호출하지 않는다 — 기존 이벤트 조회는 주입된 RecentEventProvider 로만(절대규칙 1).
   미주입 시 기본 provider(빈 후보)로 동작해 모든 기사가 신규가 된다(파이프라인 안 죽음). 실제 조회
   provider 는 TASK 08 이 주입한다.
⚠️ 감성은 병합에 쓰지 않는다 — 병합 신호는 summary·회사·시간뿐(event_merge.md §3).
"""
from __future__ import annotations

import logging

import services.event_merge as event_merge

logger = logging.getLogger(__name__)


def merge_event_node(state: dict, provider=None) -> dict:
    """articles × extracts_by_url 를 짝지어 순회하며 decide_merge 로 편입/신규를 판정·반영한다.

    - provider 미주입 시 기본(빈 후보) → 모든 기사 신규. TASK 08 이 backend provider 를 주입.
    - 이번 배치에서 만든 신규 Event 를 누적해 이후 기사의 후보에 포함한다(배치 내 중복 신규 방지, §7).
    - embedding 없는 기사는 병합 skip: event_id=None, analysis_completed=False 유지(§4.1).
    - 결과 반영: Article.event_id 배정, 신규 Event 를 state["events_by_id"] 에 등록(canonical_id 키),
      analysis_completed=True(요약·감성·임베딩·병합까지 완료 플래그).
    - 한 기사 병합이 실패해도 로깅 후 skip, 나머지는 계속한다(실패 격리, §7). 대상 0건이면 통과(§2-5).
    """
    articles = state.get("articles") or []
    extracts_by_url: dict = state.get("extracts_by_url") or {}
    events_by_id: dict = state.setdefault("events_by_id", {})

    base_provider = provider if provider is not None else event_merge.DefaultRecentEventProvider()
    # 이번 배치 신규 이벤트 누적 리스트(mutable). augmented provider 가 이 리스트를 참조하므로
    # 앞 기사에서 append 된 신규 이벤트가 뒤 기사의 후보로 자동 포함된다(증분편입).
    batch_candidates: list = []
    augmented = event_merge.BatchAugmentedProvider(base_provider, batch_candidates)

    merged = 0
    new_events = 0
    for article in articles:
        extract = extracts_by_url.get(str(article.url))
        if extract is None:
            continue  # 추출 결과 없는 기사는 병합 대상 아님(embedding 도 요약에서 나오므로 정상적으로 없음)
        if not article.embedding:
            continue  # 임베딩 없음 → 병합 skip(event_id/analysis_completed 미설정, §4.1)

        try:
            decision = event_merge.decide_merge(article, extract, augmented)
        except Exception as exc:  # 한 기사 병합 실패가 파이프라인을 죽이지 않도록 격리(§7)
            logger.warning("병합 실패, skip: url=%s (%s)", article.url, exc)
            continue

        if decision is None:  # 방어적: embedding 없음 신호(위에서 이미 걸렀지만 계약 준수)
            continue

        if decision.is_new_event:
            event = event_merge.new_event(extract)
            article.event_id = event.canonical_id
            events_by_id[event.canonical_id] = event
            # 이후 기사가 이 신규 이벤트에 편입될 수 있게 배치 후보에 추가(배치 내 중복 신규 방지).
            batch_candidates.append(
                event_merge.candidate_from_new_event(event, article, extract)
            )
            new_events += 1
        else:
            article.event_id = decision.assigned_event_id

        article.analysis_completed = True
        merged += 1

    logger.info(
        "merge_event_node: %d건 배정(신규 이벤트 %d개), 후보 provider=%s",
        merged, new_events, type(base_provider).__name__,
    )
    return state
