"""runtime 조립(run_analysis) + JSON 직렬화(to_response_dict) 테스트 (fake, 실 네트워크 없음)."""

from __future__ import annotations

from pydantic import BaseModel

from src.supervisor.runtime import run_analysis, to_response_dict
from src.supervisor.schemas import AGENT_ORDER, SupervisorInput
from src.supervisor.tests._fakes import FakeResolver, not_found, resolved


class _Out(BaseModel):
    request_id: str
    final_regime: str


class FakeAdapter:
    def __init__(self, *, output=None, exc: Exception | None = None) -> None:
        self.output = output
        self.exc = exc

    def run(self, task, deps):
        if self.exc is not None:
            raise self.exc
        return self.output


def _adapters(**overrides):
    reg = {a: FakeAdapter(output=f"{a}-ok") for a in AGENT_ORDER}
    reg.update(overrides)
    return reg


def _resolved_input(query="삼성전자 차트 어때?"):
    return SupervisorInput(query=query)


def test_run_analysis_plans_then_executes():
    ex = run_analysis(
        _resolved_input(),
        resolver=FakeResolver(result=resolved("005930", "삼성전자")),
        adapters=_adapters(),
    )
    assert [r.agent_type for r in ex.results] == list(AGENT_ORDER)
    assert all(r.status == "success" for r in ex.results)


def test_to_response_dict_serializes_pydantic_output():
    ex = run_analysis(
        _resolved_input(),
        resolver=FakeResolver(result=resolved("005930", "삼성전자")),
        adapters=_adapters(technical=FakeAdapter(output=_Out(request_id="r", final_regime="uptrend"))),
    )
    body = to_response_dict(ex)
    assert body["original_query"] == "삼성전자 차트 어때?"
    assert body["resolution"]["status"] == "resolved"
    assert len(body["tasks"]) == 5 and len(body["results"]) == 5
    tech = next(r for r in body["results"] if r["agent_type"] == "technical")
    assert tech["output"] == {"request_id": "r", "final_regime": "uptrend"}  # pydantic → dict


def test_to_response_dict_skipped_and_secret_safe_error():
    ex = run_analysis(
        _resolved_input("삼성전자 수급 보여줘"),
        resolver=FakeResolver(result=not_found()),
        adapters=_adapters(news=FakeAdapter(exc=RuntimeError("boom\nSECRET=xyz"))),
    )
    body = to_response_dict(ex)
    by = {r["agent_type"]: r for r in body["results"]}
    assert by["technical"]["status"] == "skipped" and by["technical"]["output"] is None
    assert by["news"]["status"] == "failed" and by["news"]["error"]["type"] == "RuntimeError"
    assert "\n" not in by["news"]["error"]["message"]
