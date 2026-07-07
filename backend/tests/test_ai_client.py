"""AIClient 단위 테스트 — 실제 AI 서버 없이 httpx MockTransport 로 상태코드 매핑 검증."""

from __future__ import annotations

import httpx
import pytest

from src.api.clients.ai_client import (
    AIClient,
    AITimeoutError,
    AIUnavailableError,
    AIValidationError,
)


def _client(handler) -> AIClient:
    return AIClient(
        base_url="http://ai-test",
        timeout_seconds=5.0,
        transport=httpx.MockTransport(handler),
    )


async def test_success_returns_json():
    out = await _client(lambda req: httpx.Response(200, json={"ok": True})).analyze_technical(
        {"ticker": "373220"}
    )
    assert out == {"ok": True}


async def test_422_raises_validation():
    with pytest.raises(AIValidationError):
        await _client(lambda req: httpx.Response(422, json={})).analyze_technical({})


async def test_504_raises_timeout():
    with pytest.raises(AITimeoutError):
        await _client(lambda req: httpx.Response(504)).analyze_technical({})


@pytest.mark.parametrize("code", [502, 503, 500])
async def test_5xx_raises_unavailable(code: int):
    with pytest.raises(AIUnavailableError):
        await _client(lambda req: httpx.Response(code)).analyze_technical({})


async def test_timeout_exception_raises_timeout():
    def _raise(req):
        raise httpx.TimeoutException("timeout")

    with pytest.raises(AITimeoutError):
        await _client(_raise).analyze_technical({})


async def test_connect_error_raises_unavailable():
    def _raise(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(AIUnavailableError):
        await _client(_raise).analyze_technical({})
