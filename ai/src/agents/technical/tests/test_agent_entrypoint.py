"""agent.py 외부 진입점 테스트 (test_plan §5.11 AGENT-*).

technical_supervisor.run을 monkeypatch해 호출 인자만 확인한다 — 실제 supervisor 흐름·KIS·LLM 없음.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.agents.technical import agent
from src.agents.technical.supervisor import technical_supervisor

VALID_PAYLOAD = {
    "ticker": "373220",
    "query": "LG에너지솔루션 기술적 분석",
    "request_id": "req_1",
    "as_of": "2026-06-30T14:30:00+09:00",
}

_SENTINEL_OUTPUT = object()  # supervisor.run 반환 대역(그대로 되돌아오는지 확인용)


class FakeLlm:
    def complete(self, prompt: str) -> str:  # pragma: no cover - 호출되지 않음(위임만 확인)
        return "{}"


def _patch_supervisor(monkeypatch):
    """technical_supervisor.run을 기록용 fake로 교체. (args, kwargs)를 담고 sentinel 반환."""
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return _SENTINEL_OUTPUT

    monkeypatch.setattr(technical_supervisor, "run", fake_run)
    return calls


# ── AGENT-01·02·03·04: 입력 타입/검증 ────────────────────────────────────────
def test_agent01_accepts_technical_agent_input(monkeypatch):
    from src.agents.technical.schemas.contracts import TechnicalAgentInput
    calls = _patch_supervisor(monkeypatch)
    agent_input = TechnicalAgentInput.model_validate(VALID_PAYLOAD)
    agent.run_technical_agent(agent_input, llm_client=FakeLlm())
    assert calls[0][0][0] is agent_input  # 그대로 전달


def test_agent02_accepts_dict_payload(monkeypatch):
    from src.agents.technical.schemas.contracts import TechnicalAgentInput
    calls = _patch_supervisor(monkeypatch)
    agent.run_technical_agent(dict(VALID_PAYLOAD), llm_client=FakeLlm())
    passed = calls[0][0][0]
    assert isinstance(passed, TechnicalAgentInput)  # dict → 검증된 모델
    assert passed.ticker == "373220"


def test_agent03_invalid_dict_raises_validation_error(monkeypatch):
    _patch_supervisor(monkeypatch)
    with pytest.raises(ValidationError):
        agent.run_technical_agent({"ticker": "373220"}, llm_client=FakeLlm())  # 필수 누락
    with pytest.raises(ValidationError):
        agent.run_technical_agent({**VALID_PAYLOAD, "extra": 1}, llm_client=FakeLlm())  # extra=forbid


@pytest.mark.parametrize("bad", [123, ["a"], "payload", None])
def test_agent04_unsupported_type_raises_typeerror(monkeypatch, bad):
    _patch_supervisor(monkeypatch)
    with pytest.raises(TypeError):
        agent.run_technical_agent(bad, llm_client=FakeLlm())


# ── AGENT-05·06·07: 의존성 전달 ──────────────────────────────────────────────
def test_agent05_llm_client_and_trace_id_forwarded(monkeypatch):
    calls = _patch_supervisor(monkeypatch)
    client = FakeLlm()
    agent.run_technical_agent(dict(VALID_PAYLOAD), llm_client=client, trace_id="trace_x")
    _, kwargs = calls[0]
    assert kwargs["llm_client"] is client
    assert kwargs["trace_id"] == "trace_x"


def test_agent06_fetcher_forwarded_when_given(monkeypatch):
    calls = _patch_supervisor(monkeypatch)

    def fake_fetcher(ticker, *, end_date=None):
        return {}
    agent.run_technical_agent(dict(VALID_PAYLOAD), llm_client=FakeLlm(), fetcher=fake_fetcher)
    assert calls[0][1]["fetcher"] is fake_fetcher


def test_agent07_fetcher_omitted_when_none(monkeypatch):
    calls = _patch_supervisor(monkeypatch)
    agent.run_technical_agent(dict(VALID_PAYLOAD), llm_client=FakeLlm(), fetcher=None)
    assert "fetcher" not in calls[0][1]  # supervisor 기본 fetcher 사용


# ── AGENT-08: 반환값 pass-through ────────────────────────────────────────────
def test_agent08_returns_supervisor_result(monkeypatch):
    _patch_supervisor(monkeypatch)
    result = agent.run_technical_agent(dict(VALID_PAYLOAD), llm_client=FakeLlm())
    assert result is _SENTINEL_OUTPUT


# ── AGENT-09: 계층 경계 — import 화이트리스트(부분집합) 검사 ─────────────────
# 허용 외 import(nodes·kis_client·indicators·regime·synthesis·charts·observability·
# openai·httpx·redis 등)가 하나라도 추가되면 실패한다(회귀 방지).
_ALLOWED_IMPORT_MODULES = frozenset({
    "__future__", "typing",
    "schemas.contracts",
    "supervisor", "supervisor.technical_supervisor",
})


def _imported_modules() -> set[str]:
    tree = ast.parse(Path(agent.__file__).read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
    return mods


def test_agent09_import_whitelist():
    mods = _imported_modules()
    extra = mods - _ALLOWED_IMPORT_MODULES
    assert not extra, f"agent.py에 허용되지 않은 import: {sorted(extra)}"


def test_agent_required_imports_present():
    mods = _imported_modules()
    assert "schemas.contracts" in mods                     # TechnicalAgentInput/Output
    assert {"supervisor", "supervisor.technical_supervisor"} & mods  # supervisor 위임
