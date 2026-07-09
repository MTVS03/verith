# services/backend/providers.py — 배치 조회 Provider (TASK 05/06 인터페이스의 backend 구현)
"""병합(TASK 05)·중요도(TASK 06)가 주입받는 조회 Provider 의 실제 backend HTTP 구현.

인터페이스(Protocol) 소유는 소비자(services/event_merge.py·services/importance.py)에게 있고, 여기서는
그 **backend HTTP 구현**만 채운다. 의존성 방향이 도메인(안)→인프라(밖)로 흐른다(TASK 08 §2). 두 노드
(merge_event·importance)에 주입되어 fake 자리를 대체한다.

⚠️ degrade 규칙(§4.2): backend 미연결/실패에서도 파이프라인을 죽이지 않는다 — 예외로 배치를 깨지
   않고 로깅 후 빈 결과([] / None)로 degrade 한다. 병합은 모든 기사를 신규로(과분할이 과병합보다 안전),
   importance 는 배치 기사만으로 근사. 가용성을 택하는 조회 전용 정책(쓰기는 정확 보고, save_client 참조).
⚠️ 매핑만 한다 — centroid 계산·가중·판정은 하지 않는다(그건 backend / TASK 05·06 서비스). HTTP 는
   BackendClient 로만(절대규칙 1).
"""
from __future__ import annotations

import logging

from pydantic import ValidationError

from src.agents.news.config import (
    BACKEND_EVENT_STATS_PATH,
    BACKEND_MERGE_CANDIDATES_PATH,
    BACKEND_RECENT_EVENTS_PATH,
    MERGE_VECTOR_TOP_K,
)
from src.agents.news.schemas.event import CandidateEvent, EventArticleStats
from src.agents.news.services.backend.client import BackendClient, BackendError

logger = logging.getLogger(__name__)


class BackendRecentEventProvider:
    """TASK 05 RecentEventProvider 의 backend 구현. merge_event 노드에 주입된다."""

    def __init__(self, client: BackendClient | None = None) -> None:
        self._client = client or BackendClient()

    def get_recent_events(
        self, companies: list[str], within_days: int,
        embedding: list[float] | None = None,
    ) -> list[CandidateEvent]:
        """병합 후보 이벤트를 조회 → CandidateEvent 로 매핑.

        - embedding 이 있으면 POST /events/merge-candidates(회사 ∪ 임베딩 최근접, A2) — 회사 없는 기사도
          내용으로 후보를 얻는다. embedding 이 없으면 기존 GET /events/recent(회사 경로).
        - centroid(embedding)는 backend 가 계산·유지한 값을 **읽어 담기만** 한다(TASK 05 §3.4).
        - HTTP 실패 시 로깅 후 `[]` (degrade). backend 미연결에서도 병합이 안 죽고 모든 기사가 신규가 된다.
        """
        try:
            if embedding:
                body = {
                    "companies": companies,
                    "within_days": within_days,
                    "embedding": list(embedding),
                    "top_k": MERGE_VECTOR_TOP_K,
                }
                data = self._client._request("POST", BACKEND_MERGE_CANDIDATES_PATH, json=body)
            else:
                params = {"companies": companies, "within_days": within_days}
                data = self._client._request("GET", BACKEND_RECENT_EVENTS_PATH, params=params)
        except BackendError as exc:
            logger.warning("get_recent_events 실패 — [] 로 degrade(모든 기사 신규): %s", exc)
            return []

        if not data:
            return []
        try:
            return [CandidateEvent.model_validate(item) for item in data]
        except (ValidationError, TypeError) as exc:
            logger.warning("get_recent_events 응답 매핑 실패 — [] 로 degrade: %s", exc)
            return []


class BackendEventArticleStatsProvider:
    """TASK 06 EventArticleStatsProvider 의 backend 구현. importance 노드에 주입된다."""

    def __init__(self, client: BackendClient | None = None) -> None:
        self._client = client or BackendClient()

    def get_event_article_stats(self, event_id: str) -> EventArticleStats | None:
        """이벤트의 누적 기사 통계(원자료)를 조회 → EventArticleStats 로 매핑.

        - publishers 는 distinct 원자료로 받는다(가중치는 agent 가 적용, TASK 06 §3.3). 여기서 가중·계산 안 함.
        - HTTP 실패/미존재 시 로깅 후 `None` (degrade). 편입 이벤트는 배치 기사만으로 근사, 신규는 영향 없음.
        """
        params = {"event_id": event_id}
        try:
            data = self._client._request("GET", BACKEND_EVENT_STATS_PATH, params=params)
        except BackendError as exc:
            logger.warning("get_event_article_stats 실패 — None 으로 degrade(배치만으로 근사): %s", exc)
            return None

        if data is None:  # 미존재(그 이벤트의 누적 통계 없음)
            return None
        try:
            return EventArticleStats.model_validate(data)
        except (ValidationError, TypeError) as exc:
            logger.warning("get_event_article_stats 응답 매핑 실패 — None 으로 degrade: %s", exc)
            return None
