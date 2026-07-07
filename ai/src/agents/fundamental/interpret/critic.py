from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..core.config import settings
from .llm_client import complete_structured

CRITIC_SYSTEM_PROMPT = (
    "You are a compliance critic for a deterministic financial-analysis agent. "
    "Never output numeric values. Decide only whether the draft obeys the supplied evidence and rules. Return strict JSON only."
)


class CriticOutput(BaseModel):
    # critic도 accept/revise 판단만 한다. 수정 지시에는 숫자를 넣지 못하게 스키마를 좁힌다.
    decision: Literal["accept", "revise"] = "accept"
    reasons: list[str] = Field(default_factory=list)
    revision_guidance: str = ""


@dataclass
class CriticResult:
    output: CriticOutput | None
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def build_critic_prompt(state: dict[str, Any]) -> str:
    payload = {
        "corp_name": state.get("corp_name"),
        "label": state.get("label"),
        "risk_flags": state.get("risk_flags", []),
        "analysis_plan": state.get("analysis_plan", {}),
        "selected_paths": state.get("selected_paths", []),
        "draft": {"verdict": state.get("verdict"), "interpretation": state.get("interpretation")},
        "rules": [
            "Accept if the draft is grounded and uses only supplied evidence.",
            "Revise if it invents unsupported claims, market indicators, advice, or ignores major data limits.",
            "Do not output metric values, scores, labels, thresholds, or any other numbers.",
        ],
    }
    return (
        "Review the draft qualitatively. Return JSON keys decision, reasons, revision_guidance. "
        "Do not include any numeric value in the output.\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str)}"
    )


def build_revise_prompt(original_prompt: str, critic: CriticOutput) -> str:
    # revise는 초안의 근거 사용 방식을 고치는 절차다. 새 숫자 추가는 원문 프롬프트 규칙으로 다시 금지한다.
    return (
        f"{original_prompt}\n\n"
        "A critic requested one revision. Keep every numeric value exactly as supplied in the original payload and do not add new numbers. "
        "Follow this qualitative guidance only:\n"
        f"{json.dumps({'reasons': critic.reasons, 'revision_guidance': critic.revision_guidance}, ensure_ascii=False)}\n"
        "Return only JSON with keys verdict_label, verdict, interpretation."
    )


async def critic_review(state: dict[str, Any]) -> CriticResult:
    result = await complete_structured(
        CriticOutput,
        system=CRITIC_SYSTEM_PROMPT,
        prompt=build_critic_prompt(state),
        timeout=max(settings.LLM_TIMEOUT / 2, 1.0),
        max_tokens=500,
    )
    if result is None:
        return CriticResult(output=None, provider="template", model="critic-skipped", latency_ms=0)
    return CriticResult(
        output=result.data,
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )
