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

# agent 별 지시(rewritten_query)를 LLM 으로 성형할지 여부. off 면 결정론 템플릿(기존 동작).
# LLM 이 실패해도 LlmRewriter 가 템플릿으로 안전 착지하므로 기본 on. 끄려면 env=off.
_LLM_REWRITE_RAW = (os.getenv("SUPERVISOR_LLM_REWRITE_ENABLED") or "true").strip().lower()
LLM_REWRITE_ENABLED: bool = _LLM_REWRITE_RAW in {"1", "true", "yes", "on"}
