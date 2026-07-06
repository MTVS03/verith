# tests/test_backend_client.py — services/backend/* + nodes/save.py 테스트 (mock 기반, TASK 08)
"""backend HTTP 계층(BackendClient)·저장(save_client)·조회(providers·query_client)·저장 노드 검증.

⚠️ 실제 backend·네트워크를 부르지 않는다(CLAUDE.md: tests 는 mock). BackendClient._request 또는
   httpx 세션을 mock 해 고정 응답/예외를 돌려준다. DB(SQL·Cypher·드라이버) import 는 어디에도 없다.
검증 축(§7):
- _request: 타임아웃·5xx·연결 실패에서 재시도 후 BackendError 변환, 2xx JSON 파싱, 재시도 상한, 4xx 즉시 실패.
- save_batch: 성공→ok=True, 실패→ok=False(degrade 금지), payload 에 articles·graph_batch 포함·news_id 미생성, 0건.
- request_cleanup: 성공→CleanupResponse, 실패→ok=False.
- providers: 정상 매핑 / HTTP 실패 → [] · None degrade(예외 전파 안 함), TASK 05/06 계약 호환.
- query_client: importance순·SentimentGauge(backend 집계)·subject_found 매핑, multi-hop 파라미터, limit.
- save_node: save_client 만 호출(backend 직접 호출 없음), ok=False 통과, 0건 통과.
"""
from __future__ import annotations

import httpx
import pytest

import nodes.save as save_node_mod
import services.backend.providers as providers_mod
import services.backend.query_client as query_client
import services.backend.save_client as save_client
from config import (
    BACKEND_QUERY_SHARED_PATH,
    BACKEND_QUERY_SUBJECT_PATH,
    BACKEND_SAVE_PATH,
)
from nodes.save import save_node
from schemas.article import Article
from schemas.event import CandidateEvent, EventArticleStats
from schemas.graph import GraphBatch, GraphNode, NodeLabel
from schemas.report import ArticleRef
from schemas.response import CleanupResponse, SaveResponse, SubjectQueryResponse
from services.backend.client import BackendClient, BackendError


# ---------------------------------------------------------------------------
# 헬퍼: fake httpx 응답 / 기록형 클라이언트
# ---------------------------------------------------------------------------
class FakeResponse:
    """httpx.Response 시임 — status_code·content·json() 만 흉내낸다."""

    def __init__(self, status_code: int, body=None, *, raw: bytes | None = None):
        self.status_code = status_code
        self._body = body
        self.content = raw if raw is not None else (b"{}" if body is not None else b"")
        self.request = httpx.Request("GET", "http://test/local")

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class RecordingClient:
    """BackendClient 시임 — _request 호출을 기록하고 고정 응답/예외를 돌려준다."""

    def __init__(self, response=None, error: Exception | None = None):
        self.calls: list[dict] = []
        self.response = response
        self.error = error

    def _request(self, method, path, json=None, params=None):
        self.calls.append({"method": method, "path": path, "json": json, "params": params})
        if self.error is not None:
            raise self.error
        return self.response


def _script_session(client: BackendClient, results: list):
    """client._session.request 가 results 를 순서대로 돌려주도록 교체(예외면 raise). 호출 수를 센다."""
    state = {"n": 0}
    it = iter(results)

    def fake(method, path, json=None, params=None, headers=None):
        state["n"] += 1
        item = next(it)
        if isinstance(item, Exception):
            raise item
        return item

    client._session.request = fake  # type: ignore[assignment]
    return state


def _article(url: str = "https://news.example.com/a/1", **kw) -> Article:
    base = dict(title="삼성전자 HBM 공급 계약", url=url, publisher="매일경제")
    base.update(kw)
    return Article(**base)


# ---------------------------------------------------------------------------
# BackendClient._request
# ---------------------------------------------------------------------------
def _client() -> BackendClient:
    # backoff=0 으로 테스트가 sleep 하지 않게. 재시도 상한은 명시.
    return BackendClient(base_url="http://backend.test", timeout=1.0, max_retries=2, backoff=0.0)


def test_request_parses_2xx_json():
    c = _client()
    _script_session(c, [FakeResponse(200, {"ok": True, "saved": 3})])
    assert c._request("POST", BACKEND_SAVE_PATH, json={}) == {"ok": True, "saved": 3}


def test_request_204_returns_none():
    c = _client()
    _script_session(c, [FakeResponse(204, None)])
    assert c._request("POST", "/x") is None


def test_request_retries_5xx_then_raises_backend_error():
    c = _client()
    st = _script_session(c, [FakeResponse(500), FakeResponse(503), FakeResponse(500)])
    with pytest.raises(BackendError):
        c._request("GET", "/x")
    assert st["n"] == 3  # 1 + max_retries(2)


def test_request_retries_transport_error_then_succeeds():
    c = _client()
    st = _script_session(c, [httpx.ConnectError("boom"), FakeResponse(200, {"ok": True})])
    assert c._request("GET", "/x") == {"ok": True}
    assert st["n"] == 2  # 첫 시도 실패 후 재시도 성공


def test_request_timeout_converts_to_backend_error():
    c = _client()
    st = _script_session(c, [httpx.TimeoutException("t"), httpx.TimeoutException("t"), httpx.TimeoutException("t")])
    with pytest.raises(BackendError):
        c._request("GET", "/x")
    assert st["n"] == 3  # 재시도 상한 준수(BACKEND_MAX_RETRIES)


def test_request_4xx_no_retry():
    c = _client()
    st = _script_session(c, [FakeResponse(404)])
    with pytest.raises(BackendError):
        c._request("GET", "/x")
    assert st["n"] == 1  # 4xx 는 재시도하지 않음


def test_request_bad_json_raises_backend_error():
    c = _client()
    _script_session(c, [FakeResponse(200, None, raw=b"not json")])
    with pytest.raises(BackendError):
        c._request("GET", "/x")


# ---------------------------------------------------------------------------
# save_batch
# ---------------------------------------------------------------------------
def _use_client(monkeypatch, module, fake: RecordingClient):
    monkeypatch.setattr(module, "_get_client", lambda: fake)


def test_save_batch_success(monkeypatch):
    fake = RecordingClient(response={"ok": True, "saved": 2, "message": "done"})
    _use_client(monkeypatch, save_client, fake)
    graph = GraphBatch(nodes=[GraphNode(label=NodeLabel.EVENT, key="e1")])
    resp = save_client.save_batch([_article(), _article("https://x/2")], graph)
    assert isinstance(resp, SaveResponse)
    assert resp.ok is True and resp.saved == 2
    # POST 로 save 경로에 보냄
    assert fake.calls[0]["method"] == "POST"
    assert fake.calls[0]["path"] == BACKEND_SAVE_PATH


def test_save_batch_payload_has_articles_graph_and_no_news_id(monkeypatch):
    fake = RecordingClient(response={"ok": True, "saved": 1})
    _use_client(monkeypatch, save_client, fake)
    graph = GraphBatch(nodes=[GraphNode(label=NodeLabel.EVENT, key="e1")])
    save_client.save_batch([_article()], graph)
    payload = fake.calls[0]["json"]
    assert "articles" in payload and "graph_batch" in payload
    assert len(payload["articles"]) == 1
    # 에이전트는 news_id 를 만들지 않는다 — Article.id 는 None(backend 가 url 로 해소).
    assert payload["articles"][0]["id"] is None
    # graph_batch 는 델타 그대로 실린다.
    assert payload["graph_batch"]["nodes"][0]["key"] == "e1"


def test_save_batch_failure_reports_ok_false(monkeypatch):
    # 쓰기 실패는 degrade(성공 위장) 금지 → ok=False 로 정확 보고.
    fake = RecordingClient(error=BackendError("5xx"))
    _use_client(monkeypatch, save_client, fake)
    resp = save_client.save_batch([_article()], GraphBatch(nodes=[GraphNode(label=NodeLabel.EVENT, key="e1")]))
    assert resp.ok is False and resp.saved == 0
    assert resp.message  # 사유 기록


def test_save_batch_zero_targets_skips_backend(monkeypatch):
    fake = RecordingClient(response={"ok": True, "saved": 99})
    _use_client(monkeypatch, save_client, fake)
    resp = save_client.save_batch([], GraphBatch())
    assert resp.ok is True and resp.saved == 0
    assert fake.calls == []  # backend 호출 없음


# ---------------------------------------------------------------------------
# request_cleanup
# ---------------------------------------------------------------------------
def test_request_cleanup_success(monkeypatch):
    fake = RecordingClient(response={"ok": True, "deleted_articles": 5, "deleted_events": 2})
    _use_client(monkeypatch, save_client, fake)
    resp = save_client.request_cleanup()
    assert isinstance(resp, CleanupResponse)
    assert resp.deleted_articles == 5 and resp.deleted_events == 2
    # 에이전트는 삭제 판정을 하지 않고 트리거만(요청 본문 비어 있음).
    assert fake.calls[0]["json"] == {}


def test_request_cleanup_failure_reports_ok_false(monkeypatch):
    fake = RecordingClient(error=BackendError("down"))
    _use_client(monkeypatch, save_client, fake)
    resp = save_client.request_cleanup()
    assert resp.ok is False


# ---------------------------------------------------------------------------
# BackendRecentEventProvider (TASK 05 계약)
# ---------------------------------------------------------------------------
def test_recent_event_provider_maps_candidates():
    fake = RecordingClient(response=[
        {"canonical_id": "e1", "companies": ["삼성전자"], "embedding": [0.1, 0.2], "event_time": None},
    ])
    prov = providers_mod.BackendRecentEventProvider(client=fake)
    events = prov.get_recent_events(["삼성전자"], 7)
    assert len(events) == 1
    assert isinstance(events[0], CandidateEvent)
    # centroid 는 backend 값 그대로(계산 안 함).
    assert events[0].embedding == [0.1, 0.2]
    assert fake.calls[0]["params"] == {"companies": ["삼성전자"], "within_days": 7}


def test_recent_event_provider_degrades_to_empty_on_failure():
    prov = providers_mod.BackendRecentEventProvider(client=RecordingClient(error=BackendError("x")))
    # HTTP 실패 → 예외 전파하지 않고 [] (모든 기사 신규).
    assert prov.get_recent_events(["삼성전자"], 7) == []


def test_recent_event_provider_contract_compatible_with_decide_merge():
    # TASK 05 fake 자리에 이 provider 를 끼워도 decide_merge 가 동작(계약 호환).
    import services.event_merge as event_merge
    from schemas.article import ExtractResult

    prov = providers_mod.BackendRecentEventProvider(client=RecordingClient(response=[]))
    art = _article(embedding=[0.1, 0.2, 0.3])
    decision = event_merge.decide_merge(art, ExtractResult(summary="요약", companies=["삼성전자"]), prov)
    assert decision is not None and decision.is_new_event is True  # 후보 [] → 신규


# ---------------------------------------------------------------------------
# BackendEventArticleStatsProvider (TASK 06 계약)
# ---------------------------------------------------------------------------
def test_stats_provider_maps_stats():
    fake = RecordingClient(response={
        "article_count": 4, "publishers": ["매일경제", "한국경제"],
        "sentiment_magnitude_sum": 1.5, "sentiment_count": 3,
    })
    prov = providers_mod.BackendEventArticleStatsProvider(client=fake)
    stats = prov.get_event_article_stats("e1")
    assert isinstance(stats, EventArticleStats)
    assert stats.article_count == 4 and stats.publishers == ["매일경제", "한국경제"]
    assert fake.calls[0]["params"] == {"event_id": "e1"}


def test_stats_provider_none_on_missing():
    prov = providers_mod.BackendEventArticleStatsProvider(client=RecordingClient(response=None))
    assert prov.get_event_article_stats("e1") is None


def test_stats_provider_degrades_to_none_on_failure():
    prov = providers_mod.BackendEventArticleStatsProvider(client=RecordingClient(error=BackendError("x")))
    assert prov.get_event_article_stats("e1") is None


# ---------------------------------------------------------------------------
# query_client
# ---------------------------------------------------------------------------
def _subject_payload():
    return {
        "subject": "삼성전자",
        "subject_found": True,
        "events": [
            {
                "event": {"canonical_id": "e1", "canonical_title": "실적 발표", "importance": 2.0, "companies": ["삼성전자"]},
                "article_count": 3,
                "articles": [{"news_id": 1, "summary": "요약", "url": "https://x/1"}],
                "gauge": {"positive": 2, "neutral": 1, "negative": 0},
            }
        ],
        "overall_gauge": {"positive": 2, "neutral": 1, "negative": 0},
    }


def test_get_events_by_subject_maps_response(monkeypatch):
    fake = RecordingClient(response=_subject_payload())
    _use_client(monkeypatch, query_client, fake)
    resp = query_client.get_events_by_subject(["삼성전자"], 7)
    assert isinstance(resp, SubjectQueryResponse)
    assert resp.subject_found is True
    # SentimentGauge 는 backend 집계값을 받기만 한다(ai 재집계 안 함).
    assert resp.overall_gauge.positive == 2
    assert resp.events[0].articles[0].news_id == 1  # 근거 news_id 사슬의 원천
    assert fake.calls[0]["path"] == BACKEND_QUERY_SUBJECT_PATH
    assert fake.calls[0]["params"] == {"companies": ["삼성전자"], "within_days": 7}


def test_get_shared_events_sends_multi_hop_params(monkeypatch):
    fake = RecordingClient(response=_subject_payload())
    _use_client(monkeypatch, query_client, fake)
    query_client.get_shared_events("삼성전자", "SK하이닉스", 7)
    assert fake.calls[0]["path"] == BACKEND_QUERY_SHARED_PATH
    assert fake.calls[0]["params"] == {"company_a": "삼성전자", "company_b": "SK하이닉스", "within_days": 7}


def test_get_articles_by_event_sends_limit_and_maps(monkeypatch):
    fake = RecordingClient(response=[{"news_id": 7, "summary": "s", "url": "https://x/7"}])
    _use_client(monkeypatch, query_client, fake)
    refs = query_client.get_articles_by_event("e1", limit=5)
    assert [type(r) for r in refs] == [ArticleRef]
    assert refs[0].news_id == 7
    assert fake.calls[0]["params"] == {"limit": 5}
    assert "e1" in fake.calls[0]["path"]  # event_id 가 path 에 치환됨


def test_query_client_propagates_backend_error(monkeypatch):
    # 조회 실패는 degrade 하지 않고 전파(리포트가 데이터 제한 처리).
    _use_client(monkeypatch, query_client, RecordingClient(error=BackendError("down")))
    with pytest.raises(BackendError):
        query_client.get_events_by_subject(["삼성전자"], 7)


# ---------------------------------------------------------------------------
# save_node (얇은 노드)
# ---------------------------------------------------------------------------
def test_save_node_calls_save_client_only(monkeypatch):
    captured = {}

    def fake_save_batch(articles, graph_batch):
        captured["articles"] = articles
        captured["graph"] = graph_batch
        return SaveResponse(ok=True, saved=1)

    monkeypatch.setattr(save_node_mod.save_client, "save_batch", fake_save_batch)
    graph = GraphBatch(nodes=[GraphNode(label=NodeLabel.EVENT, key="e1")])
    state = {"articles": [_article()], "graph_batch": graph}
    out = save_node(state)
    # 같은 state 의 articles·graph_batch 짝을 그대로 넘김(원자성 계약).
    assert captured["articles"] is state["articles"]
    assert captured["graph"] is graph
    assert out["save_result"].ok is True


def test_save_node_ok_false_passes_through(monkeypatch):
    monkeypatch.setattr(
        save_node_mod.save_client, "save_batch",
        lambda a, g: SaveResponse(ok=False, message="boom"),
    )
    state = {"articles": [_article()], "graph_batch": GraphBatch(nodes=[GraphNode(label=NodeLabel.EVENT, key="e1")])}
    out = save_node(state)  # 예외 없이 통과(루프 안 죽음)
    assert out["save_result"].ok is False


def test_save_node_zero_targets_skips(monkeypatch):
    called = {"n": 0}

    def fake_save_batch(a, g):
        called["n"] += 1
        return SaveResponse(ok=True)

    monkeypatch.setattr(save_node_mod.save_client, "save_batch", fake_save_batch)
    out = save_node({"articles": [], "graph_batch": GraphBatch()})
    assert called["n"] == 0  # backend/save_client 호출 없음
    assert "save_result" not in out


def test_save_node_survives_unexpected_exception(monkeypatch):
    def boom(a, g):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(save_node_mod.save_client, "save_batch", boom)
    state = {"articles": [_article()], "graph_batch": GraphBatch(nodes=[GraphNode(label=NodeLabel.EVENT, key="e1")])}
    out = save_node(state)  # 예외를 삼키고 ok=False 로 통과
    assert out["save_result"].ok is False
