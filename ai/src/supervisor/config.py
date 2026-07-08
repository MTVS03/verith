"""Supervisor 설정값 — backend resolver 접속 파라미터.

`BACKEND_BASE_URL` 은 종목 정본 경계(`/api/stocks/resolve`)를 가진 backend(:8000) 주소.
env 로 override 가능하며, resolver 호출 시에만 필요하다(supervisor 판단 로직 자체는 네트워크 없이 동작).
하드코딩 금지 — 상수는 여기서만 읽는다.
"""

from __future__ import annotations

import os

# 종목 정본 경계 backend. news 에이전트와 동일 관례(기본 localhost:8000).
BACKEND_BASE_URL: str = (os.getenv("BACKEND_BASE_URL") or "").strip() or "http://localhost:8000"
# resolver POST /api/stocks/resolve timeout(초). 종목 식별은 짧게 끊는다.
RESOLVER_TIMEOUT: float = float(os.getenv("SUPERVISOR_RESOLVER_TIMEOUT") or 5.0)
RESOLVER_PATH: str = "/api/stocks/resolve"

USER_AGENT: str = "verith-supervisor/0.1"
