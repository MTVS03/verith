from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from ..core.config import settings
from ..verify.stability import infer_verdict_label
from .fallback_template import build_fallback_interpretation
from .llm_client import complete_structured, qwen_is_skipped, skip_qwen_for, validate_json_output
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


class InterpretOutput(BaseModel):
    verdict_label: Literal["strong", "moderate", "weak", "insufficient_data"] | None = None
    verdict: str = Field(min_length=1)
    interpretation: str = Field(min_length=1)

    @model_validator(mode="after")
    def fill_label(self) -> InterpretOutput:
        if self.verdict_label is None:
            self.verdict_label = infer_verdict_label(self.verdict)
        return self


_qwen_skip_until = 0.0


def _parse_json_response(text: str) -> tuple[str, str, str | None]:
    data = validate_json_output(InterpretOutput, text)
    return data.verdict, data.interpretation, data.verdict_label


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
    # 해석 LLM은 이미 계산된 값만 설명한다. 점수·라벨·지표 값 생성 권한은 없다.
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
    local_skip_remaining = _qwen_skip_until - time.time()
    if local_skip_remaining > 0:
        skip_qwen_for(local_skip_remaining)
    qwen_skipped = qwen_is_skipped()
    flags = ["LLM_FALLBACK_OPENAI"]
    if qwen_skipped:
        flags.append("LLM_QWEN_CIRCUIT_OPEN")
    result = await complete_structured(
        InterpretOutput,
        system=SYSTEM_PROMPT,
        prompt=prompt,
        timeout=settings.LLM_TIMEOUT,
        max_tokens=1024,
    )
    if result is not None:
        return InterpretResult(
            verdict=result.data.verdict,
            interpretation=result.data.interpretation,
            verdict_label=result.data.verdict_label,
            provider=result.provider,
            model=result.model,
            flags=[] if result.provider == "qwen" else flags,
            latency_ms=result.latency_ms,
            prompt=prompt,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )

    if not settings.OPENAI_API_KEY and not qwen_is_skipped():
        skip_qwen_for(60)

    # 외부 LLM이 모두 실패해도 JSON 계약은 template 문장으로 닫는다.
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
