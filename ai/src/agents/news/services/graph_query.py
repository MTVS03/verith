# services/graph_query.py — ② 그래프 탐색 설계 (single/multi-hop)
"""회사 수·intent 로 어떤 조회를 부를지 '설계'만 한다. 실제 Neo4j 순회는 backend(query_client, TASK 08).

이 에이전트는 DB 에 직접 붙지 않는다(절대규칙 1): SQL·Cypher·드라이버·직접 HTTP-to-DB 가 없다.
  - 회사 1개 → get_events_by_subject(single-hop, importance순).
  - 회사 2개(또는 intent=관계) → get_shared_events(multi-hop 공유 이벤트, 관계 질문 핵심, query_spec §2-②).
  - 회사 0개 → backend 미호출, 빈 응답 + subject_found=False(리포트가 '데이터 제한').
BackendError 는 로깅 후 빈/subject_found=False 로 degrade 해 흐름을 이어 간다(예외 전파 안 함, 절대규칙 5).
정렬(랭킹)은 backend 가 준 importance순을 그대로 소비한다 — 기준을 여기 박지 않는다(잠정 importance, §6).
"""
from __future__ import annotations

import logging

import services.backend.query_client as query_client
from schemas.query import QueryUnderstanding
from schemas.response import SubjectQueryResponse
from services.backend.client import BackendError

logger = logging.getLogger(__name__)


def fetch_events(understanding: QueryUnderstanding) -> SubjectQueryResponse:
    """QueryUnderstanding → SubjectQueryResponse. 회사 수·intent 로 single/multi-hop 을 분기한다."""
    companies = [c for c in (understanding.companies or []) if c]
    within_days = understanding.period_days

    # 회사 0개: backend 를 부를 게 없다 — '없는 종목/미해석'으로 데이터 제한 처리.
    if not companies:
        subject = understanding.original_question or ""
        return SubjectQueryResponse(subject=subject, subject_found=False)

    try:
        # 공유 이벤트(multi-hop)는 회사가 둘 이상일 때만 가능하다. 회사 1개는 관계 질문이어도 single-hop.
        if len(companies) >= 2:
            return query_client.get_shared_events(companies[0], companies[1], within_days)
        return query_client.get_events_by_subject(companies, within_days)
    except BackendError as exc:
        # 조회 실패는 예외로 흐름을 죽이지 않고 degrade(리포트가 '데이터 제한', 절대규칙 5·TASK 08 §4.2).
        logger.warning("fetch_events: backend 조회 실패 → 데이터 제한 degrade: %s", exc)
        subject = companies[0] if len(companies) == 1 else " · ".join(companies[:2])
        return SubjectQueryResponse(subject=subject, subject_found=False)
