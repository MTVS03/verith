# services/backend/report_client.py — 질의 리포트 저장 (POST /news/reports)
"""질의 흐름의 마지막 단계(리포트 영속화)의 backend HTTP 구현.

report_node 가 만든 report_json(ai `ReportModel`)을 backend 에 저장하고, backend 가 생성한 report_id 를
돌려받는다. frontend 는 이 report_id 로 나중에 `GET /news/reports/{id}` 를 호출해 리포트를 다시 연다
(technical 과 동형: 저장 → id → 프론트 조회). report_id 는 **backend 가 만든다** — 에이전트가 만들지
않는다(환각 금지, CLAUDE.md §2-5).

⚠️ 경계(절대규칙 1): DB 에 직접 닿지 않는다. SQL·Cypher·드라이버 없음. HTTP 는 BackendClient 로만.
⚠️ 저장 실패는 성공으로 위장하지 않는다(§2-5): report_id 를 못 받으면 None 을 돌려준다. 다만 저장 실패가
   인라인 응답(질문 답변)을 죽이지는 않는다 — 리포트는 이미 만들어져 사용자에게 나가고 영속화만 실패한
   것이므로, report_id 없이(=미저장) 정직하게 통과시킨다(조회 provider 의 degrade 와는 성격이 다르다).
"""
from __future__ import annotations

import logging

from pydantic import ValidationError

from src.agents.news.config import BACKEND_REPORT_SAVE_PATH
from src.agents.news.schemas.response import ReportSaveResponse
from src.agents.news.services.backend.client import BackendClient, BackendError

logger = logging.getLogger(__name__)

# 모듈 공용 클라이언트(커넥션 재사용). 테스트는 _get_client 를 교체하거나 BackendClient._request 를 mock.
_client: BackendClient | None = None


def _get_client() -> BackendClient:
    global _client
    if _client is None:
        _client = BackendClient()
    return _client


def save_report(
    report_json: dict,
    *,
    question: str | None = None,
    intent: str | None = None,
    client_session_id: str | None = None,
) -> str | None:
    """report_json 을 backend(POST /news/reports)에 저장하고 backend 가 생성한 report_id 를 반환한다.

    - question/intent 는 ReportModel 에 담기지 않으므로(리포트는 subject 만 가짐) 별도로 함께 넘긴다 —
      backend 가 목록 인덱스·검색 컬럼으로 승격한다. 없으면 null 로 저장(둘 다 nullable).
    - 성공: backend envelope `{report_id, report}` 의 report_id(str)를 반환.
    - 실패(BackendError·스키마 불일치): 저장 안 됨을 로깅하고 None 반환(성공 위장 금지, §2-5).
    - 저장 대상 없음(빈 report_json): backend 를 부르지 않고 None(환각 금지 — 없으면 없는 대로).
    """
    if not report_json:
        logger.info("save_report: 저장할 리포트 없음 — backend 호출 없이 통과")
        return None

    payload = {
        "report": report_json,          # ai ReportModel JSON 원본(backend 가 그대로 보존)
        "question": question,           # 사용자 원문 질문(ReportModel 에 없음 → 별도 수신)
        "intent": intent,               # query understanding intent(표시/검색용)
        "client_session_id": client_session_id,
    }

    try:
        data = _get_client()._request("POST", BACKEND_REPORT_SAVE_PATH, json=payload)
    except BackendError as exc:
        # 쓰기 실패는 성공 위장 금지 — report_id 없이 정직 보고(인라인 답변은 이미 나갔다, §2-5).
        logger.error("save_report 실패 — 리포트 저장 안 됨(report_id 없음): %s", exc)
        return None

    try:
        envelope = ReportSaveResponse.model_validate(data)
    except ValidationError as exc:
        logger.error("save_report 응답 스키마 불일치(report_id 없음): %s", exc)
        return None

    logger.info("save_report: 리포트 저장 완료(report_id=%s)", envelope.report_id)
    return envelope.report_id
