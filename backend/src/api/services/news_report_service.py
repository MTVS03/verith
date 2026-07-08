"""news report 저장/조회/삭제 오케스트레이션.

technical 과 달리 backend 는 AI 를 호출하지 않는다 — 뉴스 AI 가 완성한 `ReportModel` JSON 을
받아 그대로 `news_reports.report_json` 에 보관하고, 검색 편의를 위해 answer_text·evidence 만
승격 컬럼으로 복사한다. sentiment/importance 재계산·answer 재생성은 하지 않는다(handoff §5.3).

저장 흐름: report_id 생성 → 승격 필드 추출 → news_reports + agent_reports(목록 인덱스) → commit.
뉴스는 특정 종목 universe 에 묶이지 않으므로 agent_reports.stock_code 는 비운다(stocks FK 회피).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.common.agent_report import AgentReport
from db.models.news.news_report import NewsReport
from src.api.repositories import agent_report_repository as agent_repo
from src.api.repositories import news_report_repository as nr_repo
from src.api.schemas.news_report import (
    NewsReportCreateRequest,
    NewsReportEnvelope,
)


def _parse_dt(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


class NewsReportService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── 저장 ──────────────────────────────────────────────────────────────────
    async def create_report(self, req: NewsReportCreateRequest) -> NewsReportEnvelope:
        report = req.report
        report_id = uuid4()
        now = datetime.now(UTC)

        answer_text = report.get("answer_text") or None
        subject = report.get("subject") or None
        as_of = _parse_dt(report.get("generated_at")) or now
        data_limited = bool(report.get("data_limited"))
        # 근거 묶음 — cited_event_ids(이슈 칩→이벤트) + evidence_news_ids(근거 기사).
        evidence: dict[str, Any] = {
            "cited_event_ids": report.get("cited_event_ids", []),
            "evidence_news_ids": report.get("evidence_news_ids", []),
        }

        news_report = NewsReport(
            report_id=report_id,
            question=req.question,
            intent=req.intent,
            answer_text=answer_text,
            evidence=evidence,
            report_json=report,  # ai ReportModel 원본 그대로 보존(= API 가 반환할 report)
            created_at=now,
        )

        # 목록 인덱스(GET /api/reports?agent_type=news). stock_code 는 비움(자유 subject → FK 회피),
        # stock_name 에는 표시용 subject 를 담는다.
        agent_report = AgentReport(
            id=uuid4(),
            agent_type="news",
            agent_report_id=report_id,
            request_id=None,
            client_session_id=req.client_session_id,
            owner_user_id=None,
            owner_session_id=None,
            stock_code=None,
            stock_name=subject,
            question=req.question,
            answer_text=answer_text,
            data_status=("data_limited" if data_limited else None),
            trace_id=None,
            as_of=as_of,
            created_at=now,
            summary={
                "subject": subject,
                "data_limited": data_limited,
                "intent": req.intent,
            },
        )

        await nr_repo.add_report(self._session, news_report)
        await agent_repo.add(self._session, agent_report)
        await self._session.commit()

        return NewsReportEnvelope(report_id=report_id, report=report)

    # ── 조회 ──────────────────────────────────────────────────────────────────
    async def get_report(self, report_id: UUID) -> NewsReportEnvelope | None:
        report = await nr_repo.get_report(self._session, report_id)
        if report is None:
            return None
        return NewsReportEnvelope(report_id=report.report_id, report=report.report_json or {})

    # ── 삭제 ──────────────────────────────────────────────────────────────────
    async def delete_report(self, report_id: UUID) -> bool:
        # 1) agent_reports index(FK 없음) 먼저, 2) news_reports root.
        await nr_repo.delete_agent_index(self._session, report_id)
        deleted = await nr_repo.delete_root(self._session, report_id)
        await self._session.commit()
        return deleted > 0
