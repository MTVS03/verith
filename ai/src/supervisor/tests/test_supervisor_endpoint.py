"""상위 supervisor endpoint 테스트 (fake deps override, 실 네트워크·실 agent 없음).

resolver/adapters/llm 을 app.dependency_overrides 로 교체해 endpoint orchestration 만 검증한다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import (
    get_adapters,
    get_cache,
    get_fallback,
    get_llm_client,
    get_resolver,
)
from src.api.errors import ai_unavailable
from src.main import app
from src.supervisor.execution.adapters import TechnicalAdapter
from src.supervisor.planning.fallback_lookup import StaticFallbackLookup
from src.supervisor.planning.fallback_source import CompositeFallbackLookup, CuratedFallbackSource, FallbackEntry
from src.supervisor.schemas import AGENT_ORDER
from src.supervisor.tests._fakes import FakeResolver, not_found, resolved

_ANALYZE = "/internal/supervisor/analyze"


class FakeAdapter:
    def __init__(self, *, output=None, exc: Exception | None = None) -> None:
        self.output = output
        self.exc = exc

    def run(self, task, deps):
        if self.exc is not None:
            raise self.exc
        return self.output


def _fake_adapters(**overrides):
    reg = {a: FakeAdapter(output=f"{a}-ok") for a in AGENT_ORDER}
    reg.update(overrides)
    return reg


def _ok_llm_factory():
    return lambda deadline=None: "fake-llm"


def _raising_llm_factory():
    def _make(deadline=None):
        raise ai_unavailable()
    return _make


@pytest.fixture
def api():
    client = TestClient(app)
    # cache 는 Redis 접속 시도를 막기 위해 None 으로 고정.
    app.dependency_overrides[get_cache] = lambda: None
    yield client
    app.dependency_overrides.clear()


def _wire(*, resolver, adapters, llm_factory=None, fallback=None):
    app.dependency_overrides[get_resolver] = lambda: resolver
    app.dependency_overrides[get_adapters] = lambda: adapters
    app.dependency_overrides[get_llm_client] = lambda: (llm_factory or _ok_llm_factory())
    # 기본은 no-op fallback(빈 StaticFallbackLookup → 항상 not_found) — 오케스트레이션 테스트가 운영
    # curated 내용에 의존하지 않게 한다. fallback 경로를 볼 때만 명시 주입.
    app.dependency_overrides[get_fallback] = lambda: (fallback or StaticFallbackLookup())


def test_health(api):
    r = api.get("/internal/supervisor/health")
    assert r.status_code == 200 and r.json()["service"] == "supervisor"


def test_analyze_resolved_returns_five_results(api):
    _wire(resolver=FakeResolver(result=resolved("005930", "삼성전자")), adapters=_fake_adapters())
    r = api.post(_ANALYZE, json={"query": "삼성전자 차트 어때?"})
    assert r.status_code == 200
    body = r.json()
    assert body["original_query"] == "삼성전자 차트 어때?"
    assert body["resolution"]["status"] == "resolved"
    assert len(body["tasks"]) == 5 and len(body["results"]) == 5
    assert [x["agent_type"] for x in body["results"]] == list(AGENT_ORDER)
    assert all(x["status"] == "success" for x in body["results"])
    assert body["request_id"] and body["trace_id"] and body["as_of"]  # 생성됨


def test_analyze_echoes_provided_ids(api):
    _wire(resolver=FakeResolver(result=resolved("005930", "삼성전자")), adapters=_fake_adapters())
    r = api.post(_ANALYZE, json={"query": "삼성전자 어때?", "request_id": "R1", "trace_id": "T1"})
    body = r.json()
    assert body["request_id"] == "R1" and body["trace_id"] == "T1"


def test_analyze_not_found_skips_stock_dependent(api):
    # 기본 no-op fallback → canonical not_found 가 그대로 유지되고 종목 의존 agent 는 skip.
    _wire(resolver=FakeResolver(result=not_found()), adapters=_fake_adapters())
    r = api.post(_ANALYZE, json={"query": "삼성전자 수급 보여줘"})
    by = {x["agent_type"]: x for x in r.json()["results"]}
    for a in ("technical", "fundamental", "flow"):
        assert by[a]["status"] == "skipped" and by[a]["reason"] == "stock_not_found"
    for a in ("news", "industry"):
        assert by[a]["status"] == "success"


def test_analyze_fallback_resolves_ephemeral_through_endpoint(api):
    # canonical not_found + 운영형 fallback(curated) → endpoint 응답에 fallback ephemeral 이 실린다.
    fallback = CompositeFallbackLookup(
        [CuratedFallbackSource((FallbackEntry("035720", "카카오", "KOSPI", ("Kakao",)),))]
    )
    _wire(
        resolver=FakeResolver(result=not_found()),
        adapters=_fake_adapters(),
        fallback=fallback,
    )
    r = api.post(_ANALYZE, json={"query": "Kakao 분석해줘"})
    assert r.status_code == 200
    body = r.json()
    res = body["resolution"]
    assert res["status"] == "resolved"
    assert res["used_fallback_lookup"] is True
    assert res["source"] == "fallback_lookup" and res["persisted"] is False   # ephemeral(정본 아님)
    assert res["stock"]["stock_code"] == "035720" and res["stock"]["persisted"] is False
    # 종목이 (ephemeral 로) 확정 → 5 agent 모두 success, context 는 persisted=false 로 전파.
    by = {x["agent_type"]: x for x in body["results"]}
    for a in ("technical", "fundamental", "flow"):
        assert by[a]["status"] == "success"
        assert by[a]["context"]["persisted"] is False and by[a]["context"]["source"] == "fallback_lookup"


def test_analyze_resolver_tool_error_is_not_found_distinct(api):
    _wire(resolver=FakeResolver(raise_kind="timeout"), adapters=_fake_adapters())
    body = api.post(_ANALYZE, json={"query": "삼성전자 재무 분석해줘"}).json()
    assert body["resolution"]["status"] == "error"
    by = {x["agent_type"]: x for x in body["results"]}
    for a in ("technical", "fundamental", "flow"):
        assert by[a]["status"] == "skipped" and by[a]["reason"] == "resolver_unavailable"


def test_analyze_technical_llm_missing_is_isolated_failure(api):
    # technical 은 실제 adapter(llm None → AdapterConfigError, import 전 fail), 나머지는 fake.
    adapters = _fake_adapters(technical=TechnicalAdapter())
    _wire(
        resolver=FakeResolver(result=resolved("005930", "삼성전자")),
        adapters=adapters,
        llm_factory=_raising_llm_factory(),
    )
    body = api.post(_ANALYZE, json={"query": "삼성전자 차트 어때?"}).json()
    by = {x["agent_type"]: x for x in body["results"]}
    assert by["technical"]["status"] == "failed"
    assert by["technical"]["error"]["type"] == "AdapterConfigError"
    for a in ("fundamental", "news", "flow", "industry"):
        assert by[a]["status"] == "success"          # 부분 성공


def test_analyze_empty_query_is_422(api):
    _wire(resolver=FakeResolver(result=not_found()), adapters=_fake_adapters())
    r = api.post(_ANALYZE, json={"query": ""})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
