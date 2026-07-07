"""OpenAI LLM client adapter 단위 테스트 — **네트워크 없음**(fake SDK 주입).

실제 OpenAI API를 호출하지 않는다. `client.responses.create`만 흉내내는 fake를 주입해
파라미터 전달·text 추출·예외 변환·secret-free·token usage를 검증한다.
"""

from __future__ import annotations

import time

import httpx
import openai
import pytest

from src.agents.technical import config
from src.agents.technical.nodes._llm_utils import LlmCallError
from src.agents.technical.runtime.deadline import Deadline, DeadlineExceeded
from src.agents.technical.services.openai_llm_client import (
    OpenAiLlmClient,
    default_openai_client,
)


# ── fake OpenAI SDK (responses.create만 구현) ─────────────────────────────────
class _FakeUsage:
    def __init__(self, i: int, o: int, t: int) -> None:
        self.input_tokens, self.output_tokens, self.total_tokens = i, o, t


class _FakeResponse:
    def __init__(self, output_text, usage=None) -> None:
        self.output_text = output_text
        self.usage = usage


class _FakeResponses:
    def __init__(self, *, response=None, raise_exc=None) -> None:
        self._response = response
        self._raise = raise_exc
        self.last_kwargs: dict | None = None
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self._raise is not None:
            raise self._raise
        return self._response


class _FakeSDK:
    def __init__(self, responses: _FakeResponses) -> None:
        self.responses = responses


def _client(responses: _FakeResponses, **kw) -> OpenAiLlmClient:
    kw.setdefault("model", "gpt-test")  # model은 필수 인자 — 테스트 기본값 주입
    return OpenAiLlmClient(_FakeSDK(responses), **kw)


# ── 1. API key/model 누락 → config error(fail-fast, LlmCallError 아님) ────────
def test_missing_api_key_raises_config_error(monkeypatch):
    monkeypatch.setattr(config, "_find_env_file", lambda: None)  # .env 로드 차단
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(RuntimeError) as ei:
        default_openai_client()
    assert "OPENAI_API_KEY" in str(ei.value)  # 누락 항목을 명시
    assert not isinstance(ei.value, LlmCallError)  # 호출 실패가 아니라 설정 오류


# ── 2. request 파라미터 전달 ──────────────────────────────────────────────────
def test_complete_passes_request_params():
    fr = _FakeResponses(response=_FakeResponse("ok"))
    _client(fr, model="m1", temperature=0, max_output_tokens=99, timeout=7).complete("PROMPT")
    assert fr.last_kwargs == {
        "model": "m1", "input": "PROMPT", "max_output_tokens": 99, "timeout": 7,
        "temperature": 0, "store": False,
    }


def test_temperature_none_is_omitted():
    fr = _FakeResponses(response=_FakeResponse("ok"))
    _client(fr, temperature=None).complete("p")
    assert "temperature" not in fr.last_kwargs  # None이면 파라미터 생략


# ── store=False (OpenAI 측 미저장, stateless) ─────────────────────────────────
def test_store_false_is_passed_by_default():
    fr = _FakeResponses(response=_FakeResponse("ok"))
    _client(fr).complete("p")
    assert fr.last_kwargs["store"] is False  # 기본 stateless


def test_store_override():
    fr = _FakeResponses(response=_FakeResponse("ok"))
    _client(fr, store=True).complete("p")
    assert fr.last_kwargs["store"] is True  # 필요 시 override 가능


# ── 3. text 추출(strip) ───────────────────────────────────────────────────────
def test_extracts_and_strips_output_text():
    fr = _FakeResponses(response=_FakeResponse("  분석 결과  "))
    assert _client(fr).complete("p") == "분석 결과"


# ── 4. 빈/누락 text → LlmCallError ────────────────────────────────────────────
@pytest.mark.parametrize("bad", ["", "   ", None, 123])
def test_empty_or_missing_text_raises_llm_call_error(bad):
    fr = _FakeResponses(response=_FakeResponse(bad))
    with pytest.raises(LlmCallError):
        _client(fr).complete("p")


# ── 5. OpenAI SDK 예외 → LlmCallError ─────────────────────────────────────────
def _timeout_exc() -> openai.APITimeoutError:
    return openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))


class _FakeRateLimit(openai.OpenAIError):
    """status 계열 예외 생성이 번거로워, 변환 정책만 검증하는 최소 대역(OpenAIError 하위)."""


@pytest.mark.parametrize("exc", [_timeout_exc(), _FakeRateLimit("rate limited"), openai.OpenAIError("boom")])
def test_sdk_errors_convert_to_llm_call_error(exc):
    fr = _FakeResponses(raise_exc=exc)
    client = _client(fr)
    with pytest.raises(LlmCallError):
        client.complete("p")
    assert client.last_usage is None  # 실패 시 usage 초기화


def test_error_chain_is_broken_no_raw_cause():
    # raise ... from None → __cause__에 원본 OpenAIError가 남지 않는다(logger.exception raw 노출 방지)
    leak = "sk-proj-SECRET body=RAW_RESPONSE_BODY"
    fr = _FakeResponses(raise_exc=openai.OpenAIError(leak))
    with pytest.raises(LlmCallError) as ei:
        _client(fr).complete("p")
    assert ei.value.__cause__ is None                     # 체인 끊김
    assert ei.value.__suppress_context__ is True          # from None 표식
    # 전체 traceback chain 어디에도 raw가 없다(간접 재확인)
    import traceback
    tb = "".join(traceback.format_exception(type(ei.value), ei.value, ei.value.__traceback__))
    assert "RAW_RESPONSE_BODY" not in tb and "sk-proj-SECRET" not in tb


# ── 6. 예외 메시지에 secret/prompt/raw response 미포함 ────────────────────────
def test_error_message_has_no_secret_or_prompt():
    leak = "sk-proj-SECRET123 prompt=RAW_PROMPT_TEXT body=RAW_RESPONSE"
    fr = _FakeResponses(raise_exc=openai.OpenAIError(leak))
    with pytest.raises(LlmCallError) as ei:
        _client(fr).complete("RAW_PROMPT_TEXT")
    msg = str(ei.value)
    assert "sk-proj-SECRET123" not in msg
    assert "RAW_PROMPT_TEXT" not in msg and "RAW_RESPONSE" not in msg
    assert "OpenAIError" in msg  # type 이름만 남긴다


# ── 7. token usage optional 노출 ──────────────────────────────────────────────
def test_last_usage_exposed_when_present():
    fr = _FakeResponses(response=_FakeResponse("ok", usage=_FakeUsage(11, 22, 33)))
    client = _client(fr)
    client.complete("p")
    assert client.last_usage == {"input_tokens": 11, "output_tokens": 22, "total_tokens": 33}


def test_last_usage_none_when_absent():
    fr = _FakeResponses(response=_FakeResponse("ok", usage=None))
    client = _client(fr)
    client.complete("p")
    assert client.last_usage is None


def test_last_usage_none_on_empty_output_even_with_usage():
    # usage는 있지만 output_text가 빈 실패 → last_usage는 None(진입 시 리셋, text 성공 후에만 저장)
    fr = _FakeResponses(response=_FakeResponse("", usage=_FakeUsage(1, 2, 3)))
    client = _client(fr)
    with pytest.raises(LlmCallError):
        client.complete("p")
    assert client.last_usage is None


def test_last_usage_not_carried_over_after_failure():
    # 성공 호출로 usage 저장 → 이후 실패 호출 뒤에는 이전 usage가 남지 않는다
    ok = _FakeResponses(response=_FakeResponse("ok", usage=_FakeUsage(5, 6, 11)))
    client = _client(ok)
    client.complete("p")
    assert client.last_usage == {"input_tokens": 5, "output_tokens": 6, "total_tokens": 11}
    client._client = _FakeSDK(_FakeResponses(raise_exc=openai.OpenAIError("boom")))  # 다음 호출 실패
    with pytest.raises(LlmCallError):
        client.complete("p")
    assert client.last_usage is None  # carryover 없음


# ── 8. model 속성 노출 + fake 주입으로 네트워크 없음(전 테스트 공통) ──────────
def test_model_attribute_exposed():
    client = _client(_FakeResponses(response=_FakeResponse("ok")), model="gpt-x")
    assert client.model == "gpt-x"


# ── deadline: remaining time을 per-call timeout으로 전달 / 만료 시 호출 안 함 ──
def test_deadline_caps_request_timeout():
    fr = _FakeResponses(response=_FakeResponse("ok"))
    dl = Deadline(expires_at=time.monotonic() + 5.0)  # 남은 ~5초
    _client(fr, timeout=20.0, deadline=dl).complete("p")
    t = fr.last_kwargs["timeout"]
    assert 0.0 < t <= 5.0 and t < 20.0                # config timeout(20)이 아니라 남은 예산 이하


def test_expired_deadline_raises_before_call():
    fr = _FakeResponses(response=_FakeResponse("ok"))
    dl = Deadline(expires_at=time.monotonic() - 1.0)  # 이미 만료
    with pytest.raises(DeadlineExceeded):
        _client(fr, deadline=dl).complete("p")
    assert fr.calls == 0                               # responses.create 자체를 호출 안 함


def test_no_deadline_uses_config_timeout():
    fr = _FakeResponses(response=_FakeResponse("ok"))
    _client(fr, timeout=20.0).complete("p")
    assert fr.last_kwargs["timeout"] == 20.0           # deadline 없으면 기존 timeout


def test_default_client_builds_without_network(monkeypatch):
    # load_openai_settings를 가짜로 대체해 실제 .env/네트워크 없이 SDK 조립만 확인
    monkeypatch.setattr(
        "src.agents.technical.services.openai_llm_client.load_openai_settings",
        lambda: config.OpenAiSettings(api_key="sk-test", model="gpt-env"))
    assert default_openai_client().model == "gpt-env"          # .env 값 사용
    assert default_openai_client(model="gpt-x").model == "gpt-x"  # 명시 override 우선


# ── retry/timeout 안전화: SDK client에 max_retries=0·timeout=20.0 전달 ─────────
class _RecordingOpenAI:
    """openai.OpenAI 생성 인자를 기록하는 대역(네트워크 없음)."""
    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        _RecordingOpenAI.last_kwargs = kwargs
        self.responses = _FakeResponses(response=_FakeResponse("ok"))


def _patch_sdk(monkeypatch):
    monkeypatch.setattr(
        "src.agents.technical.services.openai_llm_client.load_openai_settings",
        lambda: config.OpenAiSettings(api_key="sk-test", model="gpt-env"))
    monkeypatch.setattr("src.agents.technical.services.openai_llm_client.openai.OpenAI", _RecordingOpenAI)


def test_default_client_disables_sdk_retries(monkeypatch):
    _patch_sdk(monkeypatch)
    default_openai_client()
    assert _RecordingOpenAI.last_kwargs["max_retries"] == 0     # SDK 재시도 끔
    assert _RecordingOpenAI.last_kwargs["timeout"] == 20.0      # 보수적 per-call timeout 기본


def test_default_client_retry_timeout_override(monkeypatch):
    _patch_sdk(monkeypatch)
    default_openai_client(max_retries=1, timeout=10.0)
    assert _RecordingOpenAI.last_kwargs["max_retries"] == 1
    assert _RecordingOpenAI.last_kwargs["timeout"] == 10.0


def test_default_client_store_flag_forwarded(monkeypatch):
    _patch_sdk(monkeypatch)
    client = default_openai_client()
    client.complete("p")
    assert client._client.responses.last_kwargs["store"] is False  # 기본 stateless
