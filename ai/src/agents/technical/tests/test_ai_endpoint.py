"""AI 내부 HTTP endpoint 테스트 (`api_spec.md §7`) — **네트워크 없음**.

FastAPI TestClient + `app.dependency_overrides`로 fake llm/fetcher/cache/trace를 주입한다.
실제 OpenAI/KIS/Redis를 호출하지 않는다. 에러 매핑은 api_spec §9 envelope로 검증한다.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.agents.technical.observability.trace_logger import InMemoryTraceSink
from src.agents.technical.services.kis_client import KisApiError, OutOfScopeTickerError
from src.agents.technical.nodes._llm_utils import LlmCallError
from src.agents.technical.supervisor import technical_supervisor as sup
from src.agents.technical.tests import test_technical_supervisor as st
from src.api import dependencies as deps
from src.api import technical as tech
from src.api.errors import ai_unavailable
from src.main import app

_URL = "/internal/technical/analyze"
_BODY = {
    "request_id": "req-001",
    "ticker": "373220",
    "query": "373220 기술적 분석해줘",
    "as_of": "2026-06-30T14:30:00+09:00",
}


def _fake_fetcher(t, *, end_date=None):
    return {"D": st.DAILY, "W": st.WEEKLY, "M": st.MONTHLY}


@pytest.fixture(autouse=True)
def _intraday_off(monkeypatch):
    # 1D intraday flag가 env로 켜져 있어도 실 KIS 분봉 fetch를 막는다(네트워크 차단).
    monkeypatch.setattr(sup, "INTRADAY_FETCH_ENABLED", False)


@pytest.fixture
def client():
    """모든 runtime 의존성을 fake로 override한 TestClient. 테스트마다 override를 정리한다."""
    sink = InMemoryTraceSink()
    responses = [st.NORM_OK, st.FOCUS_OK, st.INTERP_BAD, st.INTERP_BAD]  # template fallback → 200
    app.dependency_overrides[deps.get_llm_client] = lambda: st.ScriptedLlm(responses)
    app.dependency_overrides[deps.get_fetcher] = lambda: _fake_fetcher
    app.dependency_overrides[deps.get_cache] = lambda: None
    app.dependency_overrides[deps.get_trace_sink] = lambda: sink
    c = TestClient(app)
    c.trace_sink = sink  # 테스트에서 이벤트 확인용
    yield c
    app.dependency_overrides.clear()


# ── 1. 정상 요청 → 200 + trace_id ─────────────────────────────────────────────
def test_analyze_ok_returns_200_with_trace_id(client):
    r = client.post(_URL, json=_BODY)
    assert r.status_code == 200
    data = r.json()
    assert data["request_id"] == "req-001" and data["ticker"] == "373220"
    assert data["trace_id"]                       # trace_id 포함
    assert data["source"] in ("KIS", "KIS (stale)")
    # trace_sink가 endpoint→agent→supervisor로 주입돼 이벤트가 쌓였다
    assert client.trace_sink.events and client.trace_sink.events[0]["event_type"] == "trace_start"


# ── 2. request_id 누락 → 422 VALIDATION_ERROR ─────────────────────────────────
def test_missing_request_id_returns_422(client):
    body = {k: v for k, v in _BODY.items() if k != "request_id"}
    r = client.post(_URL, json=body)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


# ── 3. malformed JSON → 400 INVALID_REQUEST ───────────────────────────────────
def test_malformed_json_returns_400(client):
    r = client.post(_URL, content="{not valid json",
                    headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_REQUEST"


# ── 4. OutOfScopeTickerError → 422 OUT_OF_SCOPE_TICKER ────────────────────────
def test_out_of_scope_returns_422(client, monkeypatch):
    def _raise(*a, **k):
        raise OutOfScopeTickerError("MVP 범위 밖")
    monkeypatch.setattr(tech, "run_technical_agent", _raise)
    r = client.post(_URL, json=_BODY)
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "OUT_OF_SCOPE_TICKER" and body["request_id"] == "req-001"


# ── 5. LlmCallError → 502 AI_UNAVAILABLE ──────────────────────────────────────
def test_llm_call_error_returns_502(client, monkeypatch):
    def _raise(*a, **k):
        raise LlmCallError("boom")
    monkeypatch.setattr(tech, "run_technical_agent", _raise)
    r = client.post(_URL, json=_BODY)
    assert r.status_code == 502 and r.json()["error"]["code"] == "AI_UNAVAILABLE"


# ── 6. LLM 설정 오류(OPENAI_API_KEY 누락) → 502 AI_UNAVAILABLE ────────────────
def test_llm_config_error_returns_502(monkeypatch):
    # 실 get_llm_client 사용: default_openai_client가 RuntimeError → get_llm_client가 502로 변환
    def _raise_runtime():
        raise RuntimeError("[OpenAI config] 필수 설정 누락: ['OPENAI_API_KEY']")
    monkeypatch.setattr(deps, "default_openai_client", _raise_runtime)
    app.dependency_overrides[deps.get_fetcher] = lambda: _fake_fetcher
    app.dependency_overrides[deps.get_cache] = lambda: None
    app.dependency_overrides[deps.get_trace_sink] = lambda: None
    try:
        r = TestClient(app).post(_URL, json=_BODY)
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 502
    err = r.json()["error"]
    assert err["code"] == "AI_UNAVAILABLE"
    assert "OPENAI_API_KEY" not in json.dumps(err)  # 원문 config 메시지 미노출


# ── 7. KisApiError → 502 AI_UNAVAILABLE ───────────────────────────────────────
def test_kis_api_error_returns_502(client, monkeypatch):
    def _raise(*a, **k):
        raise KisApiError("KIS 최대 재시도 초과")
    monkeypatch.setattr(tech, "run_technical_agent", _raise)
    r = client.post(_URL, json=_BODY)
    assert r.status_code == 502 and r.json()["error"]["code"] == "AI_UNAVAILABLE"


# ── 8. 예상 못한 오류 → 500 INTERNAL_ERROR ────────────────────────────────────
def test_unexpected_error_returns_500(client, monkeypatch):
    def _raise(*a, **k):
        raise ValueError("unexpected boom with sk-proj-SECRET leak")
    monkeypatch.setattr(tech, "run_technical_agent", _raise)
    r = client.post(_URL, json=_BODY)
    assert r.status_code == 500
    err = r.json()["error"]
    assert err["code"] == "INTERNAL_ERROR"
    assert "sk-proj-SECRET" not in json.dumps(err)  # 원문 예외 미노출


# ── 9. health → 200 ───────────────────────────────────────────────────────────
def test_health_returns_200():
    r = TestClient(app).get("/internal/technical/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "technical-agent"}


# ── 10. dependency override로 fake 주입 가능(위 전 테스트가 이를 사용) ─────────
def test_dependency_override_uses_fake_llm(client):
    # override된 fake ScriptedLlm이 실제로 쓰였는지 — 정상 200이면 실 OpenAI 없이 동작한 것
    assert client.post(_URL, json=_BODY).status_code == 200


# ── 11. 응답에 secret/raw가 없음(정상 경로) ──────────────────────────────────
def test_response_has_no_secret(client):
    dumped = json.dumps(client.post(_URL, json=_BODY).json(), ensure_ascii=False)
    for leak in ("sk-", "OPENAI_API_KEY", "Authorization", "Bearer "):
        assert leak not in dumped


def test_ai_unavailable_helper_shape():
    # §9 envelope 필드 존재 확인(단위)
    err = ai_unavailable("req-x")
    assert err.code == "AI_UNAVAILABLE" and err.status_code == 502 and err.request_id == "req-x"
