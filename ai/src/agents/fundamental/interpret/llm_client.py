from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..core.config import settings

T = TypeVar("T", bound=BaseModel)

_qwen_failures = 0
_qwen_skip_until = 0.0


@dataclass
class StructuredCompletion:
    data: BaseModel
    provider: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int


def qwen_is_skipped() -> bool:
    return time.time() < _qwen_skip_until


def skip_qwen_for(seconds: float) -> None:
    global _qwen_skip_until
    _qwen_skip_until = time.time() + seconds


def _strip_json_text(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def validate_json_output(schema: type[T], text: str) -> T:
    # LLM 출력은 regex가 아니라 pydantic v2 스키마로만 계약 통과 여부를 판단한다.
    return schema.model_validate_json(_strip_json_text(text))


async def _call_provider(
    *,
    base_url: str | None,
    api_key: str,
    model: str,
    system: str,
    prompt: str,
    timeout: float,
    max_tokens: int,
) -> tuple[str, dict[str, int | None]]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    kwargs = {
        "model": model,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    }
    if base_url is None:
        kwargs["response_format"] = {"type": "json_object"}
    else:
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    response = await client.chat.completions.create(**kwargs)
    message = response.choices[0].message
    content = message.content or getattr(message, "reasoning_content", "") or ""
    usage = getattr(response, "usage", None)
    return content, {
        "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage is not None else None,
        "completion_tokens": getattr(usage, "completion_tokens", None) if usage is not None else None,
    }


def _retry_prompt(prompt: str, error: ValidationError) -> str:
    return (
        f"{prompt}\n\n"
        "The previous output failed JSON schema validation. Return only one valid JSON object matching the schema. "
        "Do not add markdown, prose, <think>, or extra keys. Validation errors:\n"
        f"{json.dumps(error.errors(), ensure_ascii=False)}"
    )


async def _complete_with_provider(
    schema: type[T],
    *,
    provider: str,
    base_url: str | None,
    api_key: str,
    model: str,
    system: str,
    prompt: str,
    timeout: float,
    max_tokens: int,
) -> StructuredCompletion | None:
    started = time.perf_counter()
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    current_prompt = prompt
    for attempt in range(2):
        content, usage = await _call_provider(
            base_url=base_url,
            api_key=api_key,
            model=model,
            system=system,
            prompt=current_prompt,
            timeout=timeout,
            max_tokens=max_tokens,
        )
        prompt_tokens = usage["prompt_tokens"]
        completion_tokens = usage["completion_tokens"]
        try:
            data = validate_json_output(schema, content)
            return StructuredCompletion(
                data=data,
                provider=provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=round((time.perf_counter() - started) * 1000),
            )
        except ValidationError as exc:
            if attempt == 1:
                return None
            # structured output은 한 번만 재요청한다. 이후 fallback은 상위 노드가 결정한다.
            current_prompt = _retry_prompt(prompt, exc)
    return None


async def complete_structured(
    schema: type[T],
    *,
    system: str,
    prompt: str,
    timeout: float,
    max_tokens: int = 1024,
) -> StructuredCompletion | None:
    global _qwen_failures, _qwen_skip_until

    if time.time() >= _qwen_skip_until:
        try:
            result = await _complete_with_provider(
                schema,
                provider="qwen",
                base_url=settings.QWEN_BASE_URL,
                api_key=settings.LLM_DUMMY_KEY,
                model=settings.QWEN_MODEL,
                system=system,
                prompt=prompt,
                timeout=timeout,
                max_tokens=max_tokens,
            )
            if result is not None:
                _qwen_failures = 0
                return result
            _qwen_failures += 1
        except Exception:
            _qwen_failures += 1
        if _qwen_failures >= 3:
            # Qwen 연속 실패 시 같은 요청들이 timeout에 묶이지 않도록 짧게 회로를 연다.
            _qwen_skip_until = time.time() + 60

    if settings.OPENAI_API_KEY:
        try:
            return await _complete_with_provider(
                schema,
                provider="openai",
                base_url=None,
                api_key=settings.OPENAI_API_KEY,
                model=settings.OPENAI_MODEL,
                system=system,
                prompt=prompt,
                timeout=min(timeout, 15.0),
                max_tokens=max_tokens,
            )
        except Exception:
            return None
    return None
