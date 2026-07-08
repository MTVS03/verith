"""공통 리포트 보관함(archive) 목록 테스트 — technical reference 매핑 + 공통 카드 계약."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from db.models.common.agent_report import AgentReport
from db.models.common.stock import Stock
from src.api.services.technical_report_service import build_archive_item

_ARCHIVE = "/api/reports/archive"


def _agent_row(**over) -> AgentReport:
    base = dict(
        id=uuid4(), agent_type="technical", agent_report_id=uuid4(),
        request_id="req-1", client_session_id="sess-1", stock_code="005930",
        stock_name="삼성전자(저장)", question="삼성전자 기술 분석",
        answer_text="단기 박스권이지만 추세 훼손은 제한적입니다.", data_status="normal",
        trace_id="tr-1", as_of=datetime(2026, 7, 9, 9, tzinfo=UTC),
        created_at=datetime(2026, 7, 9, 10, tzinfo=UTC),
        summary={"final_regime": "neutral", "signal_score": 0.2, "confidence": 0.84},
    )
    base.update(over)
    return AgentReport(**base)


# ── 카드 projection 단위 ─────────────────────────────────────────────────────
def test_archive_card_technical_mapping():
    stock = Stock(stock_code="005930", stock_name="삼성전자", market="KOSPI")
    it = build_archive_item(row=_agent_row(), stock=stock)
    assert it.agent_type == "technical"
    assert it.stock.stock_name == "삼성전자" and it.stock.market == "KOSPI"   # canonical 우선
    assert it.card.title == "삼성전자 기술 리포트"
    assert it.card.summary.startswith("단기 박스권")
    assert it.card.badge_label == "Conf" and it.card.badge_value == "84%"     # confidence
    assert it.card.badge_tone == "green"                                      # signal_score>0.1
    assert it.card.meta_primary == "neutral"                                  # final_regime
    assert it.card.meta_secondary == "2026-07-09"
    assert it.status.data_status == "normal"
    assert it.meta.detail_url == f"/api/technical/reports/{it.report_id}"


def test_archive_card_tone_and_badge_fallbacks():
    # confidence 없음 → badge None, data_limited → amber tone
    row = _agent_row(data_status="data_limited", summary={"final_regime": "neutral"})
    it = build_archive_item(row=row, stock=None)
    assert it.card.badge_label is None and it.card.badge_value is None
    assert it.card.badge_tone == "amber"
    assert it.stock.stock_name == "삼성전자(저장)" and it.stock.market is None   # stock None → row fallback


def test_archive_card_summary_clipped_no_raw():
    row = _agent_row(answer_text="가" * 300)
    it = build_archive_item(row=row, stock=None)
    assert len(it.card.summary) <= 160 and it.card.summary.endswith("…")
    # raw summary(JSONB dict)는 카드에 노출되지 않는다(가공된 필드만).
    dumped = it.model_dump()
    assert "signal_score" not in str(dumped)   # summary JSONB 원본 미노출


def test_archive_card_unknown_agent_type_no_detail_url():
    it = build_archive_item(row=_agent_row(agent_type="flow", summary={}), stock=None)
    assert it.card.title.endswith("수급 리포트")
    assert it.meta.detail_url is None          # flow 상세경로 미확정 → None(정직)


# ── endpoint ─────────────────────────────────────────────────────────────────
async def _seed(db_session, **over) -> None:
    db_session.add(_agent_row(**over))
    await db_session.flush()


async def test_archive_endpoint_shape_and_filter(client, db_session):
    await _seed(db_session)
    await _seed(db_session, agent_type="news", summary={}, answer_text="뉴스 요약")
    resp = await client.get(_ARCHIVE, params={"agent_type": "technical"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"items", "total", "limit", "offset"}
    assert all(i["agent_type"] == "technical" for i in body["items"])   # agent_type 필터
    assert body["items"], "technical 카드가 있어야"
    item = body["items"][0]
    assert set(item.keys()) == {"report_id", "agent_type", "stock", "card", "status", "meta"}
    assert set(item["card"].keys()) == {
        "title", "summary", "badge_label", "badge_value", "badge_tone",
        "meta_primary", "meta_secondary"}


async def test_archive_endpoint_pagination(client, db_session):
    for _ in range(3):
        await _seed(db_session)
    body = (await client.get(_ARCHIVE, params={"agent_type": "technical", "limit": 2})).json()
    assert body["limit"] == 2 and len(body["items"]) <= 2 and body["total"] >= 3


async def test_archive_endpoint_empty_safe(client):
    body = (await client.get(_ARCHIVE, params={"agent_type": "industry"})).json()
    assert body["items"] == [] and body["total"] == 0        # 빈 결과 안전
