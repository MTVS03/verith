# services/backend/ — backend(:8000) HTTP 클라이언트 (절대규칙 1: DB 에 닿는 유일 경로)
"""이 에이전트가 PostgreSQL·Neo4j 에 닿는 **유일 경로**이자, 그마저도 backend HTTP 다.

- client.py     : 공용 HTTP 계층(BackendClient·BackendError). httpx 는 오직 여기에만.
- save_client.py: 배치 저장(save_batch) + 7일 롤링 삭제 트리거(request_cleanup).
- providers.py  : TASK 05/06 조회 Provider 의 backend 구현(배치 흐름 주입).
- query_client.py: 질의(리포트) 흐름 조회(종목/공유이벤트/이벤트별 기사).

노드·다른 서비스는 이 패키지만 통해 저장·조회한다(SQL·Cypher·드라이버는 어디에도 없다).
"""
from __future__ import annotations

from src.agents.news.services.backend.client import BackendClient, BackendError
from src.agents.news.services.backend.providers import (
    BackendEventArticleStatsProvider,
    BackendRecentEventProvider,
)
from src.agents.news.services.backend.query_client import (
    get_articles_by_event,
    get_events_by_subject,
    get_shared_events,
)
from src.agents.news.services.backend.save_client import request_cleanup, save_batch

__all__ = [
    "BackendClient",
    "BackendError",
    "BackendRecentEventProvider",
    "BackendEventArticleStatsProvider",
    "save_batch",
    "request_cleanup",
    "get_events_by_subject",
    "get_shared_events",
    "get_articles_by_event",
]
