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


def test_agent05b_trace_sink_forwarded(monkeypatch):
    calls = _patch_supervisor(monkeypatch)
    sink = object()  # 임의 sink 대역 — agent는 만들지 않고 통과만 시킨다
    agent.run_technical_agent(dict(VALID_PAYLOAD), llm_client=FakeLlm(), trace_sink=sink)
    assert calls[0][1]["trace_sink"] is sink


def test_agent05c_trace_sink_defaults_none(monkeypatch):
    calls = _patch_supervisor(monkeypatch)
    agent.run_technical_agent(dict(VALID_PAYLOAD), llm_client=FakeLlm())
    assert calls[0][1]["trace_sink"] is None  # 미주입 시 None(하위호환·Noop)


def test_agent05d_cache_forwarded(monkeypatch):
    calls = _patch_supervisor(monkeypatch)
    sentinel_cache = object()  # 임의 cache 대역 — agent는 만들지 않고 통과만 시킨다
    agent.run_technical_agent(dict(VALID_PAYLOAD), llm_client=FakeLlm(), cache=sentinel_cache)
    assert calls[0][1]["cache"] is sentinel_cache


def test_agent05e_cache_defaults_none(monkeypatch):
    calls = _patch_supervisor(monkeypatch)
    agent.run_technical_agent(dict(VALID_PAYLOAD), llm_client=FakeLlm())
    assert calls[0][1]["cache"] is None  # 미주입 시 None(캐시 미사용)


def test_agent05f_deadline_forwarded(monkeypatch):
    calls = _patch_supervisor(monkeypatch)
    sentinel = object()  # 임의 deadline 대역 — agent는 만들지 않고 통과만 시킨다
    agent.run_technical_agent(dict(VALID_PAYLOAD), llm_client=FakeLlm(), deadline=sentinel)
    assert calls[0][1]["deadline"] is sentinel


def test_agent05g_deadline_defaults_none(monkeypatch):
    calls = _patch_supervisor(monkeypatch)
    agent.run_technical_agent(dict(VALID_PAYLOAD), llm_client=FakeLlm())
    assert calls[0][1]["deadline"] is None  # 미주입 시 None(시간 제한 없음)


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
    "observability.trace_logger",  # TraceSink 타입만(주입 통과용) — sink 생성/경로는 agent가 모른다
    "services.cache_service",      # OhlcvCache 타입만(주입 통과용) — cache 생성은 agent가 모른다
    "runtime.deadline",            # Deadline 타입만(주입 통과용) — deadline 생성은 endpoint가 함
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


# ── AGENT-E2E: chart annotation이 agent output까지 보존되는지 (전달 경로 회귀) ──
from typing import get_args  # noqa: E402

from src.agents.technical.config import REGEN_MAX_COUNT  # noqa: E402
from src.agents.technical.schemas.chart import AnnotationKind  # noqa: E402
from src.agents.technical.tests import test_technical_supervisor as st  # noqa: E402
from src.agents.technical.tests.test_chart_builder import _cup_series  # noqa: E402

_TEN_KINDS = set(get_args(AnnotationKind))


def _e2e_responses():
    # NORM/FOCUS 통과 + interpret는 regen 소진 후 template fallback → 유효 output(charts 포함).
    return [st.NORM_OK, st.FOCUS_OK] + [st.INTERP_BAD] * (REGEN_MAX_COUNT + 1)


def test_agent_output_preserves_chart_annotations():
    # 실제 supervisor를 fake fetcher/LLM으로 실행 → agent output까지 annotation이 보존되는지
    out = agent.run_technical_agent(
        st._input(),
        llm_client=st.ScriptedLlm(_e2e_responses()),
        fetcher=lambda t, *, end_date=None: {"D": st.DAILY, "W": st.WEEKLY, "M": st.MONTHLY},
    )
    assert {"3m", "1y", "5y"} <= {c.period.value for c in out.charts}   # D/W/M 3종 존재
    all_anns = [a for c in out.charts for a in c.chart_data.annotations]
    assert all_anns                                                     # annotation 실제로 실려 나옴
    assert {a.kind for a in all_anns} <= _TEN_KINDS                     # 허용 10종 안
    assert {a.importance for a in all_anns} <= {"low", "medium", "high"}
    out.model_dump_json()                                              # 직렬화 무오류(kind/meta 포함)


def test_5y_cup_importance_high_survives_agent_output():
    # 5y 주봉 컵 시계열 주입 → output 5y chart의 cup_handle_candidate가 high(retier 생존)
    cup_weekly = _cup_series(78, step_days=7)
    out = agent.run_technical_agent(
        st._input(),
        llm_client=st.ScriptedLlm(_e2e_responses()),
        fetcher=lambda t, *, end_date=None: {"D": st.DAILY, "W": cup_weekly, "M": st.MONTHLY},
    )
    chart_5y = next(c for c in out.charts if c.period.value == "5y")
    cups = [a for a in chart_5y.chart_data.annotations if a.kind == "cup_handle_candidate"]
    assert cups                                                        # 5y 컵 후보 생성
    assert all(a.importance == "high" for a in cups)                   # 5y retier 생존(medium→high)
