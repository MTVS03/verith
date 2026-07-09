"""technical report 저장/조회/삭제 통합 테스트.

DB: docker PostgreSQL(트랜잭션 롤백 격리). AI: FakeAIClient(conftest) mock.
계약(api_spec §6) + 응답 검증(계약 위반 거부) + stocks 마스터 보호를 커버한다.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models.common.agent_report import AgentReport
from db.models.common.stock import Stock
from db.models.technical.report_chart import TechnicalReportChart
from db.models.technical.report_interpretation import TechnicalReportInterpretation
from db.models.technical.report_signal import TechnicalReportSignal
from db.models.technical.report_verification import TechnicalReportVerification
from db.models.technical.technical_report import TechnicalReport
from tests.fixtures.ai_output import INDICATORS, TICKER

_POST = "/api/technical/reports"
_REQ = {"ticker": TICKER, "query": "373220 기술적 흐름 분석", "client_session_id": "test-sess-1"}


_READ_MODEL_KEYS = {
    "report_id", "stock", "meta", "summary", "interpretation",
    "drivers", "signals", "risks", "charts", "verification", "trace_summary",
    "trust_summary", "indicator_cards", "followup_count",
}


async def _create(client) -> UUID:
    resp = await client.post(_POST, json=_REQ)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert set(body.keys()) == _READ_MODEL_KEYS                 # read model(저장 직후도 일관)
    assert body["stock"]["stock_code"] == TICKER                # canonical stock 블록
    return UUID(body["report_id"])


async def _count(session, model, report_id) -> int:
    return await session.scalar(
        select(func.count()).select_from(model).where(model.report_id == report_id)
    )


# 1) POST → technical_reports 저장 + 원본 보존
async def test_create_persists_technical_report(client, db_session):
    rid = await _create(client)
    report = await db_session.get(TechnicalReport, rid)
    assert report is not None
    assert report.ticker == TICKER
    assert report.stock_code == TICKER
    assert report.data_status == "normal"
    assert report.final_regime == "uptrend_intact"
    assert report.input_payload["request_id"] == report.request_id  # backend 생성 request_id 저장
    assert report.output_payload["source"] == "KIS"                 # AI 원본 보존


# 2) child tables 저장
async def test_create_persists_children(client, db_session):
    rid = await _create(client)
    assert await _count(db_session, TechnicalReportChart, rid) == 1
    assert await _count(db_session, TechnicalReportSignal, rid) == len(INDICATORS)
    assert await _count(db_session, TechnicalReportInterpretation, rid) == 1
    assert await _count(db_session, TechnicalReportVerification, rid) == 1


# 3) agent_reports index 저장
async def test_create_persists_agent_report_index(client, db_session):
    rid = await _create(client)
    row = await db_session.scalar(select(AgentReport).where(AgentReport.agent_report_id == rid))
    assert row is not None
    assert row.agent_type == "technical"
    assert row.stock_code == TICKER
    assert row.summary["final_regime"] == "uptrend_intact"


# 9) stocks upsert (allowlist 이름)
async def test_create_upserts_stock(client, db_session):
    await _create(client)
    stock = await db_session.get(Stock, TICKER)
    assert stock is not None
    assert stock.stock_name == "LG에너지솔루션"


# stocks 마스터 보호: 요청 stock_name 이 기존 마스터를 덮지 못한다
async def test_stock_master_not_overwritten_by_request(client, db_session):
    # 기존 마스터를 다른 이름으로 강제(seed 된 DB에서도 견고하도록 upsert — raw add 금지).
    await db_session.execute(
        pg_insert(Stock)
        .values(stock_code=TICKER, stock_name="정상마스터명")
        .on_conflict_do_update(
            index_elements=[Stock.stock_code], set_={"stock_name": "정상마스터명"}
        )
    )
    await db_session.flush()
    resp = await client.post(_POST, json={**_REQ, "stock_name": "가짜회사명"})
    assert resp.status_code == 201
    stock = await db_session.get(Stock, TICKER)
    await db_session.refresh(stock)
    assert stock.stock_name == "정상마스터명"  # 요청값으로 덮이지 않음


# 4) GET 상세 = read model
async def test_get_report_read_model(client):
    rid = await _create(client)
    resp = await client.get(f"{_POST}/{rid}")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == _READ_MODEL_KEYS
    assert body["report_id"] == str(rid)
    assert body["stock"]["stock_code"] == TICKER                # canonical block
    assert body["stock"]["stock_name"]                          # stocks 조인
    assert body["verification"]["outcome"] == "passed"          # verification read summary
    assert body["summary"]["final_regime"] == "uptrend_intact"  # summary 블록
    assert body["meta"]["source"] == "KIS"                      # meta 블록
    # signals/charts 섹션이 누락 없이 구조화돼 있다.
    assert len(body["signals"]["items"]) == len(INDICATORS)
    assert body["charts"]["available_periods"]                  # 기간 목록
    assert isinstance(body["interpretation"]["text"], str)      # text 는 호환 유지
    # trace_summary: 생성/검증/품질 요약이 뱃지·flag 로 바로 소비 가능.
    ts = body["trace_summary"]
    assert ts["generation_path"]["source"] == "KIS"
    assert ts["generation_path"]["path_label"] in ("normal", "regenerated", "template_fallback")
    assert ts["verification_summary"]["outcome"] == "passed"
    assert ts["flags"]["verification_warning"] is False
    assert set(ts.keys()) == {
        "trace_id", "generation_path", "data_quality", "verification_summary", "stability", "flags"
    }


# 4a-2) 상세에 trust_summary 카드 집계 포함
async def test_detail_has_trust_summary(client):
    rid = await _create(client)
    body = (await client.get(f"{_POST}/{rid}")).json()
    tsum = body["trust_summary"]
    assert set(tsum.keys()) == {
        "signal_quality", "data_quality", "verification_gate", "source_linkage"}
    assert "signal_score" in tsum["signal_quality"] and "signal_label" in tsum["signal_quality"]
    assert "source_coverage_ratio" in tsum["source_linkage"]
    assert tsum["verification_gate"]["outcome"] == "passed"


# 4f) 차트 full payload 전용 endpoint
async def test_charts_endpoint_full_payload(client):
    rid = await _create(client)
    resp = await client.get(f"{_POST}/{rid}/charts")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"report_id", "stock", "available_periods", "charts"}
    assert body["stock"]["stock_code"] == TICKER
    if body["charts"]:
        c = body["charts"][0]
        assert set(c.keys()) == {
            "period", "candle_unit", "display_order", "has_chart_data",
            "annotation_count", "chart_data", "annotations"}


async def test_charts_endpoint_404(client):
    from uuid import uuid4
    assert (await client.get(f"{_POST}/{uuid4()}/charts")).status_code == 404


# 4g) trace drawer 전용 endpoint (truthful, duration null)
async def test_trace_endpoint_steps_null_duration(client):
    rid = await _create(client)
    body = (await client.get(f"{_POST}/{rid}/trace")).json()
    assert set(body.keys()) == {"report_id", "overall", "steps"}
    assert body["overall"]["total_duration_ms"] is None          # 미측정 → null(정직)
    assert body["overall"]["total_steps"] == len(body["steps"]) == 5
    assert [s["step_key"] for s in body["steps"]] == [
        "data_collect", "regime_classify", "signal_aggregate", "interpret_report", "verify"]
    assert all(s["duration_ms"] is None for s in body["steps"])


async def test_trace_endpoint_404(client):
    from uuid import uuid4
    assert (await client.get(f"{_POST}/{uuid4()}/trace")).status_code == 404


# 4b) POST 직후 응답 == GET 단건 응답 (정본 계약 잠금 — 두 진입점 shape·값 완전 동일)
async def test_post_and_get_return_identical_read_model(client):
    post = await client.post(_POST, json=_REQ)
    assert post.status_code == 201, post.text
    post_body = post.json()
    rid = post_body["report_id"]
    get_body = (await client.get(f"{_POST}/{rid}")).json()
    assert post_body == get_body           # 저장 직후 == 조회: 프론트가 믿을 단일 응답 계약


# 4c) follow-up read flow (parent report 기준)
async def test_followups_empty_for_fresh_report(client):
    rid = await _create(client)
    # detail 에 followup_count=0
    detail = (await client.get(f"{_POST}/{rid}")).json()
    assert detail["followup_count"] == 0
    # followups endpoint: report 존재하지만 follow-up 0 → 빈 배열, shape 안정
    resp = await client.get(f"{_POST}/{rid}/followups")
    assert resp.status_code == 200
    flow = resp.json()
    assert flow["report_id"] == str(rid)
    assert flow["stock"]["stock_code"] == TICKER and flow["stock"]["stock_name"]
    assert flow["followup_count"] == 0 and flow["followups"] == []
    assert "one_line_summary" in flow["report_summary"]


async def test_followups_thread_bound_to_parent(client, db_session):
    from datetime import UTC, datetime
    from db.models.technical.report_followup import TechnicalReportFollowup
    rid = await _create(client)
    # 같은 세션에 follow-up 2건 seed(대화 순서 확인용, 역순 삽입)
    db_session.add_all([
        TechnicalReportFollowup(
            report_id=rid, question="두번째?", answer="두번째 답변",
            model_name="gpt-x", trace_id="tr-2", request_id="req-2",
            created_at=datetime(2026, 7, 9, 2, tzinfo=UTC),
            context_snapshot={"final_regime": "downtrend", "signal_score": -0.4},
        ),
        TechnicalReportFollowup(
            report_id=rid, question="첫번째?", answer="첫 답변",
            created_at=datetime(2026, 7, 9, 1, tzinfo=UTC), context_snapshot=None,
        ),
    ])
    await db_session.flush()

    flow = (await client.get(f"{_POST}/{rid}/followups")).json()
    assert flow["followup_count"] == 2
    qs = [f["question"] for f in flow["followups"]]
    assert qs == ["첫번째?", "두번째?"]                              # created_at 오름차순
    second = flow["followups"][1]
    assert second["answer_length"] == len("두번째 답변") and second["trace_id"] == "tr-2"
    assert second["context"]["has_context_snapshot"] is True
    assert second["context"]["base_report_regime"] == "downtrend"
    assert flow["followups"][0]["context"]["has_context_snapshot"] is False
    # detail followup_count 도 반영
    assert (await client.get(f"{_POST}/{rid}")).json()["followup_count"] == 2


async def test_followups_404_for_missing_report(client):
    from uuid import uuid4
    resp = await client.get(f"{_POST}/{uuid4()}/followups")
    assert resp.status_code == 404


# 4d) follow-up write path (POST)
async def test_create_followup_persists_and_returns_item(client, db_session):
    from db.models.technical.report_followup import TechnicalReportFollowup
    rid = await _create(client)
    body_in = {"question": "왜 과열인가요?", "answer": "단기 과열 신호가 관찰됩니다.",
               "model_name": "gpt-x", "trace_id": "tr-fu-1", "client_session_id": "sess-9"}
    resp = await client.post(f"{_POST}/{rid}/followups", json=body_in)
    assert resp.status_code == 201, resp.text
    item = resp.json()
    # 응답 = FollowupItem shape
    assert set(item.keys()) == {
        "followup_id", "request_id", "question", "answer", "model_name",
        "trace_id", "created_at", "answer_length", "context",
    }
    assert item["question"] == "왜 과열인가요?" and item["answer_length"] == len(body_in["answer"])
    assert item["model_name"] == "gpt-x" and item["trace_id"] == "tr-fu-1"
    assert item["request_id"]                                   # caller 미제공 → backend fallback(fu-...)
    # context_snapshot 이 parent 맥락으로 채워지고 read 는 요약 projection 으로 노출
    assert item["context"]["has_context_snapshot"] is True
    assert item["context"]["base_report_regime"] == "uptrend_intact"
    # DB row 저장 확인(raw snapshot 은 base_report_* 키 보존)
    row = await db_session.scalar(
        select(TechnicalReportFollowup).where(
            TechnicalReportFollowup.id == UUID(item["followup_id"]))
    )
    assert row.answer == body_in["answer"] and row.context_snapshot["base_report_id"] == str(rid)
    assert row.context_snapshot["snapshot_version"] == 1


async def test_create_followup_404_missing_report(client):
    from uuid import uuid4
    resp = await client.post(f"{_POST}/{uuid4()}/followups",
                             json={"question": "q", "answer": "a"})
    assert resp.status_code == 404


async def test_create_followup_validation(client):
    rid = await _create(client)
    # 빈 question / 빈 answer → 422
    assert (await client.post(f"{_POST}/{rid}/followups",
            json={"question": "", "answer": "a"})).status_code == 422
    assert (await client.post(f"{_POST}/{rid}/followups",
            json={"question": "q"})).status_code == 422        # answer 필수


async def test_create_followup_read_after_write(client):
    rid = await _create(client)
    await client.post(f"{_POST}/{rid}/followups", json={"question": "첫?", "answer": "첫 답"})
    await client.post(f"{_POST}/{rid}/followups", json={"question": "둘?", "answer": "둘 답"})
    flow = (await client.get(f"{_POST}/{rid}/followups")).json()
    assert flow["followup_count"] == 2
    assert [f["question"] for f in flow["followups"]] == ["첫?", "둘?"]   # created_at asc
    # POST item 과 GET list item 의 shape 가 동일(키 집합)
    post_item = (await client.post(f"{_POST}/{rid}/followups",
                 json={"question": "셋?", "answer": "셋 답"})).json()
    get_item = (await client.get(f"{_POST}/{rid}/followups")).json()["followups"][-1]
    assert set(post_item.keys()) == set(get_item.keys())
    assert get_item["question"] == "셋?"
    # detail followup_count 반영
    assert (await client.get(f"{_POST}/{rid}")).json()["followup_count"] == 3


# 4e) technical 전용 목록 index (GET /api/technical/reports)
async def test_technical_list_index_shape_and_sort(client):
    rid1 = await _create(client)
    rid2 = await _create(client)                                 # 더 최신
    resp = await client.get(_POST, params={"limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"items", "total", "limit", "offset"}
    assert body["total"] >= 2 and body["limit"] == 10 and body["offset"] == 0
    item = body["items"][0]
    assert set(item.keys()) == {"report_id", "stock", "summary", "status", "engagement", "meta"}
    assert set(item["summary"].keys()) == {"one_line_summary", "directional_bias", "final_regime"}
    assert set(item["status"].keys()) == {
        "data_status", "path_label", "verification_warning", "limited_data"}
    assert item["engagement"]["followup_count"] == 0
    assert item["stock"]["stock_code"] == TICKER and item["stock"]["stock_name"]
    # created_at DESC → 방금 만든 rid2 가 앞
    ids = [i["report_id"] for i in body["items"]]
    assert ids.index(str(rid2)) < ids.index(str(rid1))
    # 목록엔 charts/interpretation full/verification detail 없음(경량)
    assert "charts" not in item and "interpretation" not in item and "verification" not in item


async def test_technical_list_reflects_followup_count(client):
    rid = await _create(client)
    await client.post(f"{_POST}/{rid}/followups", json={"question": "q?", "answer": "a"})
    body = (await client.get(_POST, params={"stock_code": TICKER})).json()
    mine = next(i for i in body["items"] if i["report_id"] == str(rid))
    assert mine["engagement"]["followup_count"] == 1


async def test_technical_list_empty_and_filter(client):
    # 매칭 없는 stock_code → 빈 목록, shape 안정
    body = (await client.get(_POST, params={"stock_code": "999999"})).json()
    assert body["items"] == [] and body["total"] == 0


# 5) GET /api/reports 목록(cross-agent, 유지)
async def test_list_reports(client):
    rid = await _create(client)
    resp = await client.get("/api/reports", params={"agent_type": "technical"})
    assert resp.status_code == 200
    body = resp.json()
    assert any(item["agent_report_id"] == str(rid) for item in body["items"])


# 6·7) DELETE → agent_reports + technical_reports 삭제, 자식 cascade, stocks 유지
async def test_delete_cascades(client, db_session):
    rid = await _create(client)
    resp = await client.delete(f"{_POST}/{rid}")
    assert resp.status_code == 204
    assert await db_session.get(TechnicalReport, rid) is None
    assert await _count(db_session, TechnicalReportSignal, rid) == 0
    assert await _count(db_session, TechnicalReportChart, rid) == 0
    agent = await db_session.scalar(select(AgentReport).where(AgentReport.agent_report_id == rid))
    assert agent is None
    assert await db_session.get(Stock, TICKER) is not None  # 마스터 유지


# 8) 없는 report_id → 404
async def test_get_missing_404(client):
    resp = await client.get(f"{_POST}/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_delete_missing_404(client):
    resp = await client.delete(f"{_POST}/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


# ── AI 응답 계약 검증(위반 시 502, 저장 안 함) ────────────────────────────────
async def _assert_rejected_and_not_saved(client, db_session):
    before = await db_session.scalar(select(func.count()).select_from(TechnicalReport))
    resp = await client.post(_POST, json=_REQ)
    assert resp.status_code == 502, resp.text
    after = await db_session.scalar(select(func.count()).select_from(TechnicalReport))
    assert after == before  # 위반 응답은 저장되지 않음


# 10) 중복 indicator → 502, 미저장
@pytest.mark.parametrize("ai_output", ["DUP"], indirect=True)
async def test_duplicate_indicator_rejected(client, db_session):
    await _assert_rejected_and_not_saved(client, db_session)


# 요청↔응답 ticker 불일치 → 502
@pytest.mark.parametrize("ai_output", ["MISMATCH"], indirect=True)
async def test_ticker_mismatch_rejected(client, db_session):
    await _assert_rejected_and_not_saved(client, db_session)


# 구조 누락(regime 없음) → 502
@pytest.mark.parametrize("ai_output", ["MALFORMED"], indirect=True)
async def test_malformed_output_rejected(client, db_session):
    await _assert_rejected_and_not_saved(client, db_session)
