"""AI 내부 HTTP endpoint 테스트 (`api_spec.md §7`·§9) — **네트워크 없음**.

FastAPI TestClient + `app.dependency_overrides`로 fake llm/fetcher/cache/trace를 주입한다.
allowlist·입력검증·deadline은 monkeypatch가 아니라 **실제 경계**로 검증한다.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from src.agents.technical.observability.trace_logger import InMemoryTraceSink
from src.agents.technical.runtime.deadline import DeadlineExceeded
from src.agents.technical.services.kis_client import KisApiError
from src.agents.technical.nodes._llm_utils import LlmCallError
from src.agents.technical.supervisor import pipeline_steps as steps
from src.agents.technical.tests import test_technical_supervisor as st
from src.api import dependencies as deps
from src.api import technical as tech
from src.main import app

_URL = "/internal/technical/analyze"
_BODY = {
    "request_id": "req-001",
    "ticker": "373220",  # allowlist(BATTERY_TICKERS) 내
    "query": "373220 기술적 분석해줘",
    "as_of": "2026-06-30T14:30:00+09:00",
}


class _RecordingFetcher:
    """호출 여부를 기록하는 fake fetcher(실 KIS 아님)."""

    def __init__(self):
        self.calls = 0

    def __call__(self, t, *, end_date=None):
        self.calls += 1
        return {"D": st.DAILY, "W": st.WEEKLY, "M": st.MONTHLY}


@pytest.fixture(autouse=True)
def _intraday_off(monkeypatch):
    monkeypatch.setattr(steps, "INTRADAY_FETCH_ENABLED", False)  # 실 KIS 분봉 fetch 차단


@pytest.fixture
def ctx(monkeypatch):
    """fake 의존성 주입 + 관측 핸들(llm 호출·fetcher 호출·trace 이벤트)."""
    llm = st.ScriptedLlm([st.NORM_OK, st.FOCUS_OK, st.INTERP_BAD, st.INTERP_BAD])
    fetcher = _RecordingFetcher()
    sink = InMemoryTraceSink()
    app.dependency_overrides[deps.get_llm_client] = lambda: (lambda deadline=None: llm)
    app.dependency_overrides[deps.get_fetcher] = lambda: fetcher
    app.dependency_overrides[deps.get_cache] = lambda: None
    app.dependency_overrides[deps.get_trace_sink] = lambda: sink
    client = TestClient(app)
    yield type("Ctx", (), {"client": client, "llm": llm, "fetcher": fetcher, "sink": sink})
    app.dependency_overrides.clear()


# ── 1. 정상 요청 → 200 + trace_id ─────────────────────────────────────────────
def test_analyze_ok_returns_200_with_trace_id(ctx):
    r = ctx.client.post(_URL, json=_BODY)
    assert r.status_code == 200
    data = r.json()
    assert data["request_id"] == "req-001" and data["trace_id"]
    assert ctx.sink.events[0]["event_type"] == "trace_start"  # trace_sink가 agent까지 주입됨


# ── 2. request_id 누락 → 422 VALIDATION_ERROR ─────────────────────────────────
def test_missing_request_id_returns_422(ctx):
    body = {k: v for k, v in _BODY.items() if k != "request_id"}
    r = ctx.client.post(_URL, json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


# ── 3. malformed JSON → 400 INVALID_REQUEST ───────────────────────────────────
def test_malformed_json_returns_400(ctx):
    r = ctx.client.post(_URL, content="{not valid json",
                        headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_REQUEST"


# ── 입력 의미 검증 → 422 (OpenAI/KIS 호출 없이 차단) ─────────────────────────
@pytest.mark.parametrize("patch", [
    {"ticker": "ABC"},          # 6자리 숫자 아님
    {"ticker": "12345"},        # 5자리
    {"query": "   "},           # 빈 query
    {"request_id": ""},         # 빈 request_id
    {"as_of": "2099-01-01T00:00:00+09:00"},  # 미래
])
def test_semantic_validation_returns_422(ctx, patch):
    r = ctx.client.post(_URL, json={**_BODY, **patch})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert ctx.llm.prompts == [] and ctx.fetcher.calls == 0  # OpenAI/KIS 미호출


# ── validation error에서 request_id 복원 ──────────────────────────────────────
def test_validation_error_preserves_request_id(ctx):
    r = ctx.client.post(_URL, json={**_BODY, "ticker": "BAD"})
    assert r.status_code == 422
    assert r.json()["error"]["request_id"] == "req-001"  # body의 request_id 유지


def test_malformed_json_request_id_is_null(ctx):
    r = ctx.client.post(_URL, content="{bad", headers={"content-type": "application/json"})
    assert r.json()["error"]["request_id"] is None


# ── 전체 종목 확장: 구 out-of-scope 6자리 ticker도 수용(200), 형식 오류만 422 ─────────────
def test_expanded_ticker_accepted(ctx):
    r = ctx.client.post(_URL, json={**_BODY, "ticker": "999999"})  # 구 allowlist 밖, 이제 지원
    assert r.status_code == 200
    assert r.json()["request_id"] == "req-001"
    assert ctx.llm.prompts and ctx.fetcher.calls > 0     # OpenAI·KIS 정상 진입(미차단)


def test_invalid_format_ticker_is_422(ctx):
    r = ctx.client.post(_URL, json={**_BODY, "ticker": "12345"})  # 6자리 아님 → 계약 검증 실패
    assert r.status_code == 422
    assert ctx.llm.prompts == [] and ctx.fetcher.calls == 0


# ── 5. LlmCallError → 502 (매핑) ──────────────────────────────────────────────
def test_llm_call_error_returns_502(ctx, monkeypatch):
    monkeypatch.setattr(tech, "run_technical_agent",
                        lambda *a, **k: (_ for _ in ()).throw(LlmCallError("boom")))
    r = ctx.client.post(_URL, json=_BODY)
    assert r.status_code == 502 and r.json()["error"]["code"] == "AI_UNAVAILABLE"


# ── 6. LLM 설정 오류(OPENAI_API_KEY 누락) → 502 ──────────────────────────────
def test_llm_config_error_returns_502(monkeypatch):
    def _raise_runtime(*a, **k):
        raise RuntimeError("[OpenAI config] 필수 설정 누락: ['OPENAI_API_KEY']")
    monkeypatch.setattr(deps, "default_openai_client", _raise_runtime)  # 실 get_llm_client 팩토리 사용
    app.dependency_overrides[deps.get_fetcher] = lambda: _RecordingFetcher()
    app.dependency_overrides[deps.get_cache] = lambda: None
    app.dependency_overrides[deps.get_trace_sink] = lambda: None
    try:
        r = TestClient(app).post(_URL, json=_BODY)
    finally:
        app.dependency_overrides.clear()
    err = r.json()["error"]
    assert r.status_code == 502 and err["code"] == "AI_UNAVAILABLE"
    assert "OPENAI_API_KEY" not in json.dumps(err)  # 원문 config 메시지 미노출


# ── 7. KisApiError → 502 (매핑) ───────────────────────────────────────────────
def test_kis_api_error_returns_502(ctx, monkeypatch):
    monkeypatch.setattr(tech, "run_technical_agent",
                        lambda *a, **k: (_ for _ in ()).throw(KisApiError("KIS 최대 재시도 초과")))
    r = ctx.client.post(_URL, json=_BODY)
    assert r.status_code == 502 and r.json()["error"]["code"] == "AI_UNAVAILABLE"


# ── 8. 예상 못한 오류 → 500, 원문 미노출 ──────────────────────────────────────
def test_unexpected_error_returns_500(ctx, monkeypatch):
    monkeypatch.setattr(tech, "run_technical_agent",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("boom sk-proj-SECRET")))
    r = ctx.client.post(_URL, json=_BODY)
    err = r.json()["error"]
    assert r.status_code == 500 and err["code"] == "INTERNAL_ERROR"
    assert "sk-proj-SECRET" not in json.dumps(err)


# ── deadline: DeadlineExceeded → 504, wait_for timeout → 504 ──────────────────
def test_deadline_exceeded_returns_504(ctx, monkeypatch):
    monkeypatch.setattr(tech, "run_technical_agent",
                        lambda *a, **k: (_ for _ in ()).throw(DeadlineExceeded("budget")))
    r = ctx.client.post(_URL, json=_BODY)
    assert r.status_code == 504 and r.json()["error"]["code"] == "AI_TIMEOUT"


def test_wait_for_timeout_returns_504(ctx, monkeypatch):
    monkeypatch.setattr(tech, "TECHNICAL_AGENT_TIMEOUT_SECONDS", 0.05)

    def _slow(*a, **k):
        time.sleep(0.4)  # wait_for(0.05)를 초과 → TimeoutError → 504
        return None
    monkeypatch.setattr(tech, "run_technical_agent", _slow)
    r = ctx.client.post(_URL, json=_BODY)
    assert r.status_code == 504 and r.json()["error"]["code"] == "AI_TIMEOUT"


# ── 9. health → 200 + version ─────────────────────────────────────────────────
def test_health_returns_200_with_version():
    r = TestClient(app).get("/internal/technical/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "technical-agent", "version": "0.1.0"}


# ── 11. 응답에 secret/raw 없음(정상 경로) ────────────────────────────────────
def test_response_has_no_secret(ctx):
    dumped = json.dumps(ctx.client.post(_URL, json=_BODY).json(), ensure_ascii=False)
    for leak in ("sk-", "OPENAI_API_KEY", "Authorization", "Bearer "):
        assert leak not in dumped
