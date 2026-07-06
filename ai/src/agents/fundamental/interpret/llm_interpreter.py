from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..core.config import settings
from ..verify.stability import infer_verdict_label
from .fallback_template import build_fallback_interpretation
from .prompts import SYSTEM_PROMPT, build_interpret_prompt


@dataclass
class InterpretResult:
    verdict: str
    interpretation: str
    verdict_label: str | None
    provider: str
    model: str
    flags: list[str] = field(default_factory=list)
    latency_ms: int = 0
    prompt: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


_qwen_failures = 0
_qwen_skip_until = 0.0


def _parse_json_response(text: str) -> tuple[str, str, str | None]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL | re.IGNORECASE).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end >= start:
        decoder = json.JSONDecoder()
        for index, char in enumerate(cleaned):
            if char != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(cleaned[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and {"verdict", "interpretation"} <= set(candidate):
                data = candidate
                break
        else:
            data = json.loads(cleaned[start : end + 1])
    else:
        data = json.loads(cleaned)
    verdict = str(data.get("verdict", "")).strip()
    interpretation = str(data.get("interpretation", "")).strip()
    verdict_label = str(data.get("verdict_label", "")).strip() or None
    if not verdict or not interpretation:
        raise ValueError("empty LLM verdict or interpretation")
    return verdict, interpretation, verdict_label if verdict_label in {"strong", "moderate", "weak", "insufficient_data"} else infer_verdict_label(verdict)


async def _call_openai_compatible(
    *,
    base_url: str | None,
    api_key: str,
    model: str,
    prompt: str,
    timeout: float,
) -> tuple[str, str, str | None, dict[str, int | None]]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    chat_error: Exception | None = None
    attempts = 3 if base_url is not None else 1
    for _ in range(attempts):
        try:
            if base_url is None:
                response = await client.chat.completions.create(
                    model=model,
                    temperature=0.2,
                    max_tokens=1024,
                    response_format={"type": "json_object"},
                    messages=messages,
                )
            else:
                response = await client.chat.completions.create(
                    model=model,
                    temperature=0.0,
                    max_tokens=1024,
                    messages=messages,
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                )
            message = response.choices[0].message
            content = message.content or getattr(message, "reasoning_content", "") or ""
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage is not None else None
            completion_tokens = getattr(usage, "completion_tokens", None) if usage is not None else None
            verdict, interpretation, verdict_label = _parse_json_response(content)
            return verdict, interpretation, verdict_label, {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
        except Exception as exc:
            chat_error = exc

    try:
        response = await client.completions.create(
            model=model,
            temperature=0.0,
            max_tokens=1024,
            prompt=f"{SYSTEM_PROMPT}\n\n{prompt}\n\nReturn only the final JSON object. No <think>:",
        )
        content = response.choices[0].text or ""
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage is not None else None
        completion_tokens = getattr(usage, "completion_tokens", None) if usage is not None else None
        verdict, interpretation, verdict_label = _parse_json_response(content)
        return verdict, interpretation, verdict_label, {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
    except Exception:
        if chat_error is not None:
            raise chat_error
        raise


async def interpret(
    corp_name: str,
    score: int,
    label: str,
    ratios: dict[str, Any],
    trend: dict[str, Any],
    risk_flags: list[str],
    *,
    insights: dict[str, Any] | None = None,
    analyst_plan: dict[str, Any] | None = None,
    retrieval_context: dict[str, Any] | None = None,
    period_basis: dict[str, Any] | None = None,
    prompt_override: str | None = None,
) -> InterpretResult:
    global _qwen_failures, _qwen_skip_until

    started = time.perf_counter()
    prompt = prompt_override or build_interpret_prompt(
        corp_name,
        score,
        label,
        ratios,
        trend,
        risk_flags,
        insights,
        analyst_plan=analyst_plan,
        retrieval_context=retrieval_context,
        period_basis=period_basis,
    )
    now = time.time()

    if now >= _qwen_skip_until:
        try:
            verdict, interpretation, verdict_label, usage = await _call_openai_compatible(
                base_url=settings.QWEN_BASE_URL,
                api_key=settings.LLM_DUMMY_KEY,
                model=settings.QWEN_MODEL,
                prompt=prompt,
                timeout=settings.LLM_TIMEOUT,
            )
            _qwen_failures = 0
            return InterpretResult(
                verdict=verdict,
                interpretation=interpretation,
                verdict_label=verdict_label,
                provider="qwen",
                model=settings.QWEN_MODEL,
                latency_ms=round((time.perf_counter() - started) * 1000),
                prompt=prompt,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
            )
        except Exception:
            _qwen_failures += 1
            if _qwen_failures >= 3:
                _qwen_skip_until = time.time() + 60
    flags = ["LLM_FALLBACK_OPENAI"]

    if settings.OPENAI_API_KEY:
        try:
            verdict, interpretation, verdict_label, usage = await _call_openai_compatible(
                base_url=None,
                api_key=settings.OPENAI_API_KEY,
                model=settings.OPENAI_MODEL,
                prompt=prompt,
                timeout=min(settings.LLM_TIMEOUT, 15.0),
            )
            return InterpretResult(
                verdict=verdict,
                interpretation=interpretation,
                verdict_label=verdict_label,
                provider="openai",
                model=settings.OPENAI_MODEL,
                flags=flags,
                latency_ms=round((time.perf_counter() - started) * 1000),
                prompt=prompt,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
            )
        except Exception:
            pass

    verdict, interpretation = build_fallback_interpretation(corp_name, score, label, ratios, risk_flags)
    if "LLM_FALLBACK_TEMPLATE" not in flags:
        flags.append("LLM_FALLBACK_TEMPLATE")
    await asyncio.sleep(0)
    return InterpretResult(
        verdict=verdict,
        interpretation=interpretation,
        verdict_label=label,
        provider="template",
        model="rule-based",
        flags=flags,
        latency_ms=round((time.perf_counter() - started) * 1000),
        prompt=prompt,
    )
