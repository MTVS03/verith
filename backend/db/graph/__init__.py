"""Neo4j(뉴스 지식그래프) 데이터스토어.

PostgreSQL(`db/models`, `db/session.py`)과 별개인 그래프 저장소다. schema.md §8 대로
Neo4j 노드/관계는 Alembic 마이그레이션 대상이 아니라 backend 앱이 소유하는 별도 스토어이며,
스키마 정본은 `backend/db/DATA_MODEL.md` §2 다.

- `driver` : 모듈 레벨 async 드라이버 + 세션 제공자(`get_graph_session`) + 정리(`close_driver`).
- `bootstrap` : 노드 정체성 키 유니크 제약 부트스트랩(`ensure_constraints`).
"""

from __future__ import annotations

from db.graph.bootstrap import ensure_constraints
from db.graph.driver import close_driver, get_driver, get_graph_session

__all__ = [
    "ensure_constraints",
    "close_driver",
    "get_driver",
    "get_graph_session",
]
