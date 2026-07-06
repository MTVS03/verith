import time

import pytest

from src.agents.fundamental.interpret import llm_interpreter
from src.agents.fundamental.interpret.llm_interpreter import _parse_json_response, interpret


def test_parse_json_response_reads_verdict_label() -> None:
    verdict, interpretation, verdict_label = _parse_json_response(
        '{"verdict_label":"weak","verdict":"재무 체력이 약합니다.","interpretation":"ROE가 낮습니다."}'
    )

    assert verdict == "재무 체력이 약합니다."
    assert interpretation == "ROE가 낮습니다."
    assert verdict_label == "weak"


def test_parse_json_response_infers_missing_verdict_label() -> None:
    _, _, verdict_label = _parse_json_response(
        '{"verdict":"재무 체력이 양호합니다.","interpretation":"안정성이 우수합니다."}'
    )

    assert verdict_label == "strong"


@pytest.mark.asyncio
async def test_interpret_uses_template_when_qwen_is_skipped_and_openai_key_missing(monkeypatch):
    monkeypatch.setattr(llm_interpreter, "_qwen_skip_until", time.time() + 60)
    monkeypatch.setattr(llm_interpreter.settings, "OPENAI_API_KEY", "")

    result = await interpret(
        "Test Corp",
        45,
        "moderate",
        {"roe": {"value": 3.0, "unit": "%"}},
        {"years": ["2025"]},
        [],
    )

    assert result.provider == "template"
    assert result.model == "rule-based"
    assert result.verdict_label == "moderate"
    assert "LLM_FALLBACK_OPENAI" in result.flags
    assert "LLM_FALLBACK_TEMPLATE" in result.flags
