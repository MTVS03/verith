"""OpenAI LLM client adapter — Technical Agent의 `complete(prompt) -> str` 계약 구현.

**순수 어댑터**다: OpenAI Responses API 호출 → `output_text` 추출 → 예외를 `LlmCallError`로
변환하는 것만 한다. supervisor/node orchestration·prompt 구조·응답 schema·검증 로직은 건드리지 않고,
기존 fake LLM과 **교체 가능한 adapter**로 동작한다(구조적 Protocol `complete`).

secret-safe(technical_coding_guidelines §2.2·§13.2): raw prompt·raw response body·API key·
Authorization 헤더를 저장하거나 예외 메시지에 담지 않는다. 예외는 **type 이름 수준**만 남긴다.

trace 경계 밖: 이 어댑터는 trace sink를 알지 못한다. 대신 `model`과 `last_usage`(호출당 토큰
사용량)를 optional 속성으로 노출해, 후속 AI endpoint 통합에서 trace 배선을 준비만 해 둔다.

runtime wiring은 이 브랜치 범위 밖 — `run_technical_agent`는 자동으로 이 client를 만들지 않고
계속 주입식이다. 운영에서는 endpoint가 `default_openai_client()`를 생성해 주입한다.
"""

from __future__ import annotations

import logging
from typing import Any

import openai

from ..config import (
    OPENAI_MAX_OUTPUT_TOKENS,
    OPENAI_TEMPERATURE,
    OPENAI_TIMEOUT_SECONDS,
    load_openai_settings,
)
from ..nodes._llm_utils import LlmCallError

logger = logging.getLogger(__name__)


class OpenAiLlmClient:
    """OpenAI SDK를 감싼 `complete(prompt) -> str` 어댑터.

    주입식 SDK client(`client`)는 `client.responses.create(...)`만 요구한다 — 테스트는 fake를
    주입해 네트워크 없이 검증한다. `temperature`가 None이면 요청에서 생략한다(일부 모델 미허용 대비).
    """

    def __init__(
        self,
        client: Any,
        *,
        model: str,  # 코드 기본값 없음 — .env가 단일 출처(default_openai_client가 주입)
        temperature: float | None = OPENAI_TEMPERATURE,
        max_output_tokens: int = OPENAI_MAX_OUTPUT_TOKENS,
        timeout: float = OPENAI_TIMEOUT_SECONDS,
    ) -> None:
        self._client = client
        self.model = model
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._timeout = timeout
        # 후속 trace 배선용 optional 노출 — 마지막 호출의 토큰 사용량(없으면 None).
        self.last_usage: dict[str, int] | None = None

    def complete(self, prompt: str) -> str:
        """Responses API 1회 호출 → `output_text` 반환. 실패는 모두 `LlmCallError`로 변환한다."""
        request: dict[str, Any] = {
            "model": self.model,
            "input": prompt,
            "max_output_tokens": self._max_output_tokens,
            "timeout": self._timeout,
        }
        if self._temperature is not None:  # None이면 파라미터 생략(모델별 미허용 대비)
            request["temperature"] = self._temperature
        try:
            response = self._client.responses.create(**request)
        except openai.OpenAIError as exc:  # timeout·rate limit·auth·connection·API·BadRequest 전부
            self.last_usage = None
            # secret-free: exception type 이름만(raw 응답/prompt/key 미포함).
            raise LlmCallError(f"OpenAI 호출 실패: {type(exc).__name__}") from exc
        self.last_usage = _extract_usage(response)
        return _extract_text(response)


def _extract_text(response: Any) -> str:
    """Responses API 편의 property `output_text`에서 text만 추출. 비어 있으면 `LlmCallError`."""
    text = getattr(response, "output_text", None)
    if not isinstance(text, str) or not text.strip():
        # 응답 shape가 예상과 다르거나 빈 응답 → 호출 실패로 취급(raw 미포함).
        raise LlmCallError("OpenAI 응답에서 text를 추출하지 못했습니다(빈 output_text).")
    return text.strip()


def _extract_usage(response: Any) -> dict[str, int] | None:
    """`response.usage`에서 input/output/total 토큰만 안전 추출(없거나 불안정하면 None)."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    try:
        return {
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        }
    except (TypeError, ValueError):
        return None


def default_openai_client(
    *,
    model: str | None = None,
    temperature: float | None = OPENAI_TEMPERATURE,
    max_output_tokens: int = OPENAI_MAX_OUTPUT_TOKENS,
    timeout: float = OPENAI_TIMEOUT_SECONDS,
) -> OpenAiLlmClient:
    """운영용 OpenAI client 생성. **API key·model 누락은 여기서 fail-fast**(config error, LlmCallError 아님).

    api_key·model은 `config.load_openai_settings()`가 .env/환경변수에서 읽는다(코드/로그/trace 미저장).
    `model` 인자를 명시하면 .env 값 대신 그것을 쓴다(테스트/실험용). `run_technical_agent`는 이걸
    자동 호출하지 않는다 — endpoint 통합에서 주입한다(A안).
    """
    settings = load_openai_settings()  # api_key·model 누락 시 RuntimeError(어디에 무엇을 넣을지 명시)
    sdk_client = openai.OpenAI(api_key=settings.api_key, timeout=timeout)
    return OpenAiLlmClient(
        sdk_client,
        model=model or settings.model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        timeout=timeout,
    )
