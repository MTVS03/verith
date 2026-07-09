"""industry report 저장/조회/삭제 통합 테스트."""

from __future__ import annotations

import copy
from collections.abc import AsyncGenerator
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from db.models.common.agent_report import AgentReport
from db.models.industry.industry_report import IndustryReport
from db.session import get_session
from src.api.deps import get_ai_client
from src.api.main import app

_POST = "/api/industry/reports"
_REQ = {"question": "삼성SDI와 경쟁하는 기업은?", "client_session_id": "industry-sess-1"}


def _normal_output() -> dict:
    return {
        "schemaVersion": "research-report.v1",
        "reportId": "rpt_20260709_samsung-sdi",
        "createdAt": "2026-07-09T13:00:00+00:00",
        "locale": "ko-KR",
        "question": {
            "text": "삼성SDI와 경쟁하는 기업은?",
            "type": "relational",
            "label": "Relational graph question",
        },
        "answer": {
            "headline": "삼성SDI의 경쟁사는 LG에너지솔루션입니다.",
            "body": "삼성SDI는 LG에너지솔루션과 경쟁 관계로 연결됩니다.",
            "tags": ["삼성SDI", "LG에너지솔루션"],
            "faithfulness": {
                "status": "verified",
                "label": "근거 검증 완료",
                "unsupportedClaims": [],
            },
        },
        "metrics": {
            "rows": 1,
            "attempts": 1,
            "graphEdges": 1,
            "graphNodes": 2,
            "citations": 1,
        },
        "graph": {"nodes": [], "edges": []},
        "evidence": [],
        "execution": {
            "pipeline": [],
            "cypher": "MATCH ...",
            "retrievalFlow": "LangGraph classify -> Cypher",
        },
        "graphSnapshot": {"nodes": {}, "relationships": {}},
    }


class FakeIndustryAIClient:
    def __init__(self, output: dict) -> None:
        self._output = output
        self.seen_payload: dict | None = None

    async def analyze_industry(self, payload: dict) -> dict:
        self.seen_payload = payload
        return copy.deepcopy(self._output)


async def _client(db_session, output: dict) -> AsyncGenerator[AsyncClient, None]:
    async def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_ai_client] = lambda: FakeIndustryAIClient(output)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _create(client: AsyncClient) -> UUID:
    resp = await client.post(_POST, json=_REQ)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert set(body.keys()) == {"report_id", "report"}
    assert body["report"]["schemaVersion"] == "research-report.v1"
    return UUID(body["report_id"])


async def test_industry_create_get_list_delete_roundtrip(db_session):
    async for client in _client(db_session, _normal_output()):
        rid = await _create(client)

        report = await db_session.get(IndustryReport, rid)
        assert report is not None
        assert report.report_id == "rpt_20260709_samsung-sdi"
        assert report.question == _REQ["question"]
        assert report.question_type == "relational"
        assert report.status == "completed"
        assert report.schema_version == "research-report.v1"
        assert report.payload["answer"]["headline"] == "삼성SDI의 경쟁사는 LG에너지솔루션입니다."

        agent = await db_session.scalar(select(AgentReport).where(AgentReport.agent_report_id == rid))
        assert agent is not None
        assert agent.agent_type == "industry"
        assert agent.client_session_id == "industry-sess-1"
        assert agent.stock_code is None
        assert agent.summary["question_type"] == "relational"
        assert agent.summary["faithfulness_status"] == "verified"

        get_resp = await client.get(f"{_POST}/{rid}")
        assert get_resp.status_code == 200
        detail = get_resp.json()
        assert detail["report_id"] == str(rid)
        assert detail["report"]["reportId"] == "rpt_20260709_samsung-sdi"

        list_resp = await client.get(_POST, params={"client_session_id": "industry-sess-1"})
        assert list_resp.status_code == 200
        listed = list_resp.json()
        assert listed["count"] >= 1
        assert any(item["agent_report_id"] == str(rid) for item in listed["items"])

        archive_resp = await client.get("/api/reports/archive", params={"agent_type": "industry"})
        assert archive_resp.status_code == 200
        archived = archive_resp.json()
        mine = next(item for item in archived["items"] if item["report_id"] == str(rid))
        assert mine["meta"]["detail_url"] == f"/api/industry/reports/{rid}"

        delete_resp = await client.delete(f"{_POST}/{rid}")
        assert delete_resp.status_code == 204
        assert await db_session.get(IndustryReport, rid) is None
        assert await db_session.scalar(select(AgentReport).where(AgentReport.agent_report_id == rid)) is None


async def test_industry_get_delete_missing_404(db_session):
    async for client in _client(db_session, _normal_output()):
        missing = "00000000-0000-0000-0000-000000000000"
        assert (await client.get(f"{_POST}/{missing}")).status_code == 404
        assert (await client.delete(f"{_POST}/{missing}")).status_code == 404


async def test_industry_contract_violation_rejected(db_session):
    broken = _normal_output()
    del broken["answer"]["body"]
    async for client in _client(db_session, broken):
        before = await db_session.scalar(select(func.count()).select_from(IndustryReport))
        resp = await client.post(_POST, json=_REQ)
        assert resp.status_code == 502, resp.text
        after = await db_session.scalar(select(func.count()).select_from(IndustryReport))
        assert after == before
