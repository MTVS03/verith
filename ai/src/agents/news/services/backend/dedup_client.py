# services/backend/dedup_client.py — 이미 저장된 url 걸러내기 (신규 기사만 처리, TASK 08 확장)
"""배치 수집(crawl) 후 **이미 backend 에 저장된 기사 url 을 비싼 LLM 처리 전에 제외**하기 위한 조회.

왜 필요한가: RSS 피드는 최신 스냅샷(수백~수천 건)을 매번 주고, 저장은 url upsert 라 멱등이지만
extract(LLM)·sentiment·embedding 은 매 회차 전부 다시 돈다. 이미 저장된 기사를 걸러내면 매시간
**진짜 새 기사만** 처리해 (1) 처리 시간을 실제 신규 유입량에 비례시키고, (2) cap 이 '유실 방지선'이
아니라 '회차당 처리량 상한'이 되게 한다(밀린 기사는 다음 회차에 이어 처리 — 유실 방지).

⚠️ 경계(절대규칙 1): DB 에 직접 닿지 않는다. backend HTTP(BackendClient)로만. url 존재 판정은 backend 소관.
⚠️ degrade(조회 정책): backend 미연결/실패 시 **걸러내지 않는다**(None 반환) — 새 기사를 놓치느니
   중복 재처리(멱등)를 택한다. 즉 실패는 파이프라인을 죽이지 않고 "필터 미적용"으로 안전하게 물러난다.
"""
from __future__ import annotations

import logging

from config import BACKEND_EXISTS_PATH
from services.backend.client import BackendClient, BackendError

logger = logging.getLogger(__name__)

_client: BackendClient | None = None


def _get_client() -> BackendClient:
    global _client
    if _client is None:
        _client = BackendClient()
    return _client


def get_existing_urls(urls: list[str]) -> set[str] | None:
    """입력 url 중 이미 저장된 것들의 집합을 돌려준다. 실패 시 None(=필터 미적용 degrade).

    - 빈 입력은 backend 를 부르지 않고 빈 집합.
    - 응답 형태 불일치·오류는 None 으로 degrade(호출측 crawl_node 가 전부 처리로 물러남).
    """
    if not urls:
        return set()
    try:
        data = _get_client()._request("POST", BACKEND_EXISTS_PATH, json={"urls": urls})
    except BackendError as exc:
        logger.warning("get_existing_urls 실패 — 필터 미적용(전부 처리)로 degrade: %s", exc)
        return None

    existing = (data or {}).get("existing")
    if not isinstance(existing, list):
        logger.warning("get_existing_urls 응답 형태 불일치 — 필터 미적용으로 degrade")
        return None
    return {u for u in existing if isinstance(u, str)}
