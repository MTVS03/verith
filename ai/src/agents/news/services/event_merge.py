# services/event_merge.py
"""이벤트 병합 판정 서비스 — 기사 1건을 기존 이벤트에 편입하거나 신규 이벤트를 만든다(TASK 05).

news 에이전트에서 가장 까다로운 부분(event_merge.md). 병합 신호는 **summary 임베딩·회사·시간**뿐이고,
가중 점수로 결합한다: `score = 0.6·summary + 0.3·company + 0.1·time`(event_merge.md §3). 최고 점수가
임계값 미만이면 억지로 편입하지 않고 신규 이벤트를 만든다(§4, 환각/억지 금지 CLAUDE.md §2-5).
canonical_title은 LLM이 아니라 규칙(최상위 confidence EventCandidate.title)으로 만든다(§2-4/§6).

⚠️ **조회 경계(절대규칙 1)**: 기존 이벤트를 가져오는 유일한 경로는 주입된 `RecentEventProvider`다.
   이 서비스는 DB 드라이버·Cypher·backend HTTP 를 직접 부르지 않는다. provider 실제 구현은 TASK 08.
⚠️ 감성·importance 를 계산하지 않는다 — 배정·이름만. 감성=TASK 04, importance=TASK 06(단일 책임).
⚠️ centroid(이벤트 대표 벡터)를 만들거나 갱신하지 않는다 — provider가 준 값을 읽어 유사도만 낸다(집계는 backend).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from config import (
    MERGE_CANDIDATE_WINDOW_DAYS,
    MERGE_THRESHOLD,
    MERGE_W_COMPANY,
    MERGE_W_SUMMARY,
    MERGE_W_TIME,
)
from schemas.article import Article, ExtractResult
from schemas.event import CandidateEvent, Event, MergeCandidate, MergeDecision
from utils.entity import normalize_entity_name
from utils.similarity import company_overlap, cosine_similarity, time_proximity

logger = logging.getLogger(__name__)

# canonical_title 폴백 시 요약에서 잘라 쓸 최대 길이. 대표명이 문장 전체가 되지 않게만 막는 표시용 상한
# (가중치·임계값 같은 튜닝 대상이 아니라 렌더 편의 상수).
_FALLBACK_TITLE_MAX_CHARS = 40


class RecentEventProvider(Protocol):
    """후보 이벤트 조회 계약(후보 축소). 실제 구현은 TASK 08(backend 클라이언트)."""

    def get_recent_events(self, companies: list[str], within_days: int) -> list[CandidateEvent]:
        """동일 회사·최근 within_days 이벤트만 반환(후보 축소, event_merge.md §5).
        미주입 기본 구현은 []를 반환(backend 미연결에서도 파이프라인이 죽지 않고, 모든 기사가 신규가 됨)."""
        ...


class DefaultRecentEventProvider:
    """미주입 시 기본 provider. backend 없이도 파이프라인이 돌게 항상 빈 후보를 반환한다.

    → 후보가 없으니 모든 기사가 신규 이벤트가 된다(과병합보다 과분할이 안전, 억지 편입 금지 정신).
    TASK 08의 backend 클라이언트가 이 자리에 실제 조회 provider를 주입한다.
    """

    def get_recent_events(self, companies: list[str], within_days: int) -> list[CandidateEvent]:
        return []


class BatchAugmentedProvider:
    """주입 provider(backend) + 이번 배치에서 방금 만든 신규 이벤트를 함께 후보로 내주는 래퍼(증분편입).

    같은 배치의 동일 사건 둘째 기사가 첫째가 만든 신규 이벤트에 편입되게 한다(그렇지 않으면 각각 새
    이벤트가 됨, event_merge.md §7). 전체 재군집화가 아니라 순차 편입이다. batch 후보 리스트는 노드가
    쥔 mutable 리스트를 참조하므로, 이후 기사 처리 때 앞서 추가된 신규 이벤트가 자동으로 후보에 포함된다.
    """

    def __init__(self, base: RecentEventProvider, batch_candidates: list[CandidateEvent]):
        self._base = base
        self._batch = batch_candidates

    def get_recent_events(self, companies: list[str], within_days: int) -> list[CandidateEvent]:
        base_events = self._base.get_recent_events(companies, within_days)
        # 배치 후보는 회사가 하나라도 겹치는 것만(다른 회사 사건과 섞이지 않게 — 후보 축소 계약과 동일).
        query_set = {n for n in (normalize_entity_name(c) for c in companies) if n}
        batch_hits = [
            c
            for c in self._batch
            if query_set & {n for n in (normalize_entity_name(x) for x in c.companies) if n}
        ]
        return list(base_events) + batch_hits


def _article_time(article: Article, extract: ExtractResult) -> datetime | None:
    """점수·후보 생성에 쓸 기사 시각. event_date(발생 시점) 우선, 없으면 published_at(발행 시점).

    event_date 를 우선하는 이유는 '발생 시점 ≠ 발행 시점'이기 때문(TASK 03 §2). 둘 다 없으면 None(시간 신호 없음).
    """
    if extract.event_date is not None:
        return extract.event_date
    return article.published_at


def score_candidate(
    article_vec: list[float],
    article_companies: list[str],
    article_time: datetime | None,
    cand: CandidateEvent,
) -> MergeCandidate:
    """가중 점수 = 0.6·summary + 0.3·company + 0.1·time. 세부 점수도 함께 담아 반환(디버깅).

    - summary_similarity = cosine_similarity(기사 벡터, 후보 대표 벡터(centroid))
    - company_overlap    = 회사 리스트 Jaccard(한쪽 비면 0)
    - time_similarity    = 이벤트 발생 시점 근접도(None 이면 0)
    """
    summary_sim = cosine_similarity(article_vec, cand.embedding)
    company_ov = company_overlap(article_companies, cand.companies)
    time_sim = time_proximity(article_time, cand.event_time)
    score = (
        MERGE_W_SUMMARY * summary_sim
        + MERGE_W_COMPANY * company_ov
        + MERGE_W_TIME * time_sim
    )
    return MergeCandidate(
        event_id=cand.canonical_id,
        score=score,
        summary_similarity=summary_sim,
        company_overlap=company_ov,
        time_similarity=time_sim,
    )


def decide_merge(
    article: Article,
    extract: ExtractResult,
    provider: RecentEventProvider,
) -> MergeDecision | None:
    """기사 1건 → 편입 or 신규 판정. embedding 없으면 None(skip 신호).

    - article.embedding 이 없으면(요약/임베딩 실패) 병합하지 않고 None 을 반환(파이프라인 계속, §4.1).
    - provider.get_recent_events(회사, MERGE_CANDIDATE_WINDOW_DAYS) 로 후보를 받아 각각 score_candidate.
    - article_time = event_date(우선) or published_at.
    - 최고 점수 >= MERGE_THRESHOLD 면 편입(is_new_event=False), 미만/후보없음이면 신규(is_new_event=True).
      "제일 가까운 것"이라도 임계값 미만이면 억지로 받지 않는다(과병합 방지, event_merge.md §4).
    """
    if not article.embedding:
        return None  # 임베딩 없음 → 병합 skip 신호(노드가 event_id/analysis_completed 미설정)

    article_time = _article_time(article, extract)
    candidates_events = provider.get_recent_events(extract.companies, MERGE_CANDIDATE_WINDOW_DAYS)

    scored = [
        score_candidate(article.embedding, extract.companies, article_time, ce)
        for ce in candidates_events
    ]
    best = max(scored, key=lambda m: m.score) if scored else None

    if best is not None and best.score >= MERGE_THRESHOLD:
        return MergeDecision(
            assigned_event_id=best.event_id,
            is_new_event=False,
            best_score=best.score,
            candidates=scored,
        )
    return MergeDecision(
        assigned_event_id=None,
        is_new_event=True,
        best_score=(best.score if best is not None else None),
        candidates=scored,
    )


def make_canonical_title(extract: ExtractResult) -> str:
    """신규 이벤트 대표명 = extract.events 중 최상위 confidence 의 title.

    - EventCandidate.title 은 이미 회사명·감성 평가어가 배제된 '사건명'이다(TASK 03 §3.2.2).
    - events 가 비면 요약 앞부분으로 폴백한다(감성 평가어를 새로 지어내지 않음, event_merge.md §6).
      요약도 비면 최후 폴백으로 '이벤트'(빈 canonical_title 방지). LLM 을 호출하지 않는다(§2-4).
    """
    valid = [e for e in extract.events if e.title and e.title.strip()]
    if valid:
        top = max(valid, key=lambda e: e.confidence)
        return top.title.strip()

    summary = (extract.summary or "").strip()
    if summary:
        first_line = summary.splitlines()[0].strip()
        return first_line[:_FALLBACK_TITLE_MAX_CHARS]
    return "이벤트"


def new_event(extract: ExtractResult) -> Event:
    """신규 Event 생성. canonical_id=UUID4, canonical_title=규칙 기반, companies=extract.companies.

    importance 는 None(TASK 06 에서 계산), created_at=now(관리·정렬용 메타). LLM 미사용.
    """
    return Event(
        canonical_id=str(uuid4()),
        canonical_title=make_canonical_title(extract),
        companies=list(extract.companies),
        importance=None,
        created_at=datetime.now(timezone.utc),
    )


def candidate_from_new_event(
    event: Event,
    article: Article,
    extract: ExtractResult,
) -> CandidateEvent:
    """방금 만든 신규 Event 를 이후 기사의 후보로 쓰기 위한 CandidateEvent 로 변환(배치 내 증분편입).

    이번 배치에서 만든 이벤트라 대표 벡터(centroid)는 이 기사 summary 임베딩 하나뿐이다(backend 저장 시
    centroid 를 재계산·유지, TASK 08). event_time 은 기사 시각(event_date 우선). 실제 centroid 계산은
    하지 않는다 — 단건이라 그 벡터가 곧 대표다.
    """
    return CandidateEvent(
        canonical_id=str(event.canonical_id),
        companies=list(event.companies),
        embedding=list(article.embedding or []),
        event_time=_article_time(article, extract),
    )
