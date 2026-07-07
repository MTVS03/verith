# services/backend/save_client.py — 배치 저장 + 7일 롤링 삭제 트리거 (TASK 08)
"""배치 흐름의 마지막 단계(저장)와 삭제 트리거의 backend HTTP 구현.

★ 원자성 계약(§3.3): `save_batch()` 는 **하나의 배치를 원자 단위로 backend 에 넘기는 계약**이다.
  `articles`(PostgreSQL news 원본)와 `graph_batch`(Neo4j MERGE 델타)는 **같은 실행에서 나온 짝**이어야
  한다(같은 state["articles"]·state["graph_batch"]). NewsRef 가 news_id 로 이어지려면 news 가 먼저
  저장돼 news_id 가 생겨야 하는데, 서로 다른 배치를 섞으면 url→news_id 해소가 어긋나 그래프가 존재하지
  않는 기사를 가리킨다. 그래서 둘을 **함께** 보내고, url→news_id 해소·두 저장소 반영 순서는 backend 책임.
  에이전트는 news_id 를 만들지 않는다(환각 금지, CLAUDE.md §2-5).

⚠️ 경계(절대규칙 1): DB 에 직접 닿지 않는다. SQL·Cypher·드라이버 없음. HTTP 는 BackendClient 로만.
⚠️ 저장(쓰기) 실패는 **degrade 하지 않는다** — 데이터가 안 남는 진짜 실패이므로 SaveResponse(ok=False)
   로 정확히 보고 + 로깅한다(성공 위장 금지, §2-5). degrade(빈 결과 반환)는 조회 provider 에만 허용된다.
"""
from __future__ import annotations

import logging

from pydantic import ValidationError

from config import (
    BACKEND_CLEANUP_PATH,
    BACKEND_SAVE_BATCH_SIZE,
    BACKEND_SAVE_PATH,
)
from schemas.article import Article
from schemas.graph import GraphBatch
from schemas.response import CleanupResponse, SaveResponse
from services.backend.client import BackendClient, BackendError

logger = logging.getLogger(__name__)

# 모듈 공용 클라이언트(커넥션 재사용). 테스트는 BackendClient._request 를 mock 하거나 _get_client 를 교체.
_client: BackendClient | None = None


def _get_client() -> BackendClient:
    global _client
    if _client is None:
        _client = BackendClient()
    return _client


def save_batch(articles: list[Article], graph_batch: GraphBatch) -> SaveResponse:
    """분석된 news 원본(PostgreSQL) + GraphBatch(Neo4j MERGE)를 backend 에 **원자적**으로 저장 요청한다.

    - `articles`·`graph_batch` 는 같은 배치의 짝(원자성 계약). backend 가 하나의 저장 작업으로 처리한다.
    - idempotent: news 는 url UNIQUE upsert, 그래프는 정체성 키 MERGE 로 재실행에도 중복이 안 생긴다
      (계약을 backend 에 요구). NewsRef 는 url 키 → backend 가 저장 시 news_id 로 해소(TASK 07/SCHEMA_SPEC §3).
    - importance 는 graph_batch 의 Event property 로 반영(재계산 없음, 이중 소스 방지 §2).
    - 실패는 degrade 하지 않고 SaveResponse(ok=False) + 로깅(성공 위장 금지). 다음 배치 주기에 재시도.
    """
    # 대상 0건: backend 를 부르지 않고 통과(환각 금지 — 없으면 없는 대로, §3.6-4).
    graph_empty = not graph_batch.nodes and not graph_batch.relationships
    if not articles and graph_empty:
        logger.info("save_batch: 저장 대상 0건 — backend 호출 없이 통과")
        return SaveResponse(ok=True, saved=0, message="nothing to save")

    if BACKEND_SAVE_BATCH_SIZE is not None and len(articles) > BACKEND_SAVE_BATCH_SIZE:
        # 원자성 계약상 기사만 청크로 쪼개면 다른 청크의 NewsRef(url)가 해소되지 않는다(§3.3). '무해한
        # 분할' 방식은 api_contract 확정 전까지 미지원 — 경고만 남기고 한 배치로 함께 보낸다.
        logger.warning(
            "save_batch: articles %d건이 BACKEND_SAVE_BATCH_SIZE(%d) 초과 — 원자성 유지 위해 한 번에 전송",
            len(articles), BACKEND_SAVE_BATCH_SIZE,
        )

    payload = {
        # HttpUrl·datetime·Enum 을 JSON 직렬화 가능한 형태로(mode="json"). news_id 는 넣지 않는다(backend 가 해소).
        "articles": [a.model_dump(mode="json") for a in articles],
        "graph_batch": graph_batch.model_dump(mode="json"),
    }

    try:
        data = _get_client()._request("POST", BACKEND_SAVE_PATH, json=payload)
    except BackendError as exc:
        # 쓰기 실패는 degrade 금지 — ok=False 로 정확히 보고(성공 위장 금지, §2-5).
        logger.error("save_batch 실패 — 저장 안 됨(ok=False): %s", exc)
        return SaveResponse(ok=False, saved=0, message=str(exc))

    try:
        return SaveResponse.model_validate(data)
    except ValidationError as exc:
        logger.error("save_batch 응답 스키마 불일치(ok=False): %s", exc)
        return SaveResponse(ok=False, saved=0, message=f"invalid SaveResponse: {exc}")


def request_cleanup() -> CleanupResponse:
    """7일 롤링 삭제를 backend 에 **트리거만** 한다.

    168h 경과 판정·CASCADE(Event 기사수 0이면 삭제·고아 Keyword/Person/Country 삭제·**Company 유지**)·
    살아남은 이벤트 importance 재계산은 모두 backend 가 수행한다(SCHEMA_SPEC §5). 이 에이전트는 삭제
    판정을 하지 않는다. 호출 주체는 TASK 10 cleanup 스케줄러. 실패는 degrade 없이 ok=False 로 보고.
    """
    try:
        data = _get_client()._request("POST", BACKEND_CLEANUP_PATH, json={})
    except BackendError as exc:
        logger.error("request_cleanup 실패 — 삭제 트리거 실패(ok=False): %s", exc)
        return CleanupResponse(ok=False, message=str(exc))

    try:
        return CleanupResponse.model_validate(data)
    except ValidationError as exc:
        logger.error("request_cleanup 응답 스키마 불일치(ok=False): %s", exc)
        return CleanupResponse(ok=False, message=f"invalid CleanupResponse: {exc}")
