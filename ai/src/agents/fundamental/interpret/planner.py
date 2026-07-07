from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..core.config import settings
from .llm_client import complete_structured

SECTION_KEYS = ("profitability", "stability", "growth", "valuation_basis", "shareholder", "data_limits")
SectionKey = Literal["profitability", "stability", "growth", "valuation_basis", "shareholder", "data_limits"]

PLANNER_SYSTEM_PROMPT = (
    "You are a financial-analysis planner. Deterministic code already calculated every metric and score. "
    "Do not create, modify, rank, or output numeric values. Return strict JSON only."
)


class AnalysisPlan(BaseModel):
    # planner는 섹션과 근거 우선순위만 정한다. 숫자·점수·라벨 필드는 의도적으로 두지 않는다.
    focus_sections: list[SectionKey] = Field(default_factory=list)
    section_order: list[SectionKey] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    evidence_priority: list[str] = Field(default_factory=list)
    emphasis_notes: list[str] = Field(default_factory=list)

    @field_validator("section_order", "focus_sections")
    @classmethod
    def unique_sections(cls, value: list[SectionKey]) -> list[SectionKey]:
        seen: list[SectionKey] = []
        for item in value:
            if item not in seen:
                seen.append(item)
        return seen


def fallback_plan(analyst_plan: dict[str, Any]) -> AnalysisPlan:
    order = [item for item in analyst_plan.get("section_order", []) if item in SECTION_KEYS]
    briefs = analyst_plan.get("section_briefs", {})
    return AnalysisPlan(
        focus_sections=order[:3],
        section_order=order,
        key_risks=[briefs[key] for key in order if key in briefs and ("한계" in briefs[key] or "주의" in briefs[key])],
        evidence_priority=[],
        emphasis_notes=[briefs[key] for key in order if key in briefs][:4],
    )


def build_planner_prompt(
    *,
    corp_name: str,
    intent: str,
    analyst_plan: dict[str, Any],
    evidence_graph: dict[str, Any],
    risk_flags: list[str],
) -> str:
    sections = [
        {"id": item.get("id"), "signal": item.get("signal"), "summary": item.get("summary"), "metrics": item.get("metrics", [])}
        for item in evidence_graph.get("sections", [])
    ]
    payload = {
        "corp_name": corp_name,
        "intent": intent,
        "allowed_sections": SECTION_KEYS,
        "deterministic_section_order": analyst_plan.get("section_order", []),
        "sections": sections,
        "risk_flags": risk_flags,
        "rules": [
            "Return no numbers.",
            "Do not change score, label, metric values, or thresholds.",
            "evidence_priority must contain metric keys only, not values.",
        ],
    }
    return (
        "Choose a concise analysis plan for a Korean financial-health report. "
        "Use only section keys and qualitative risk notes from the payload. "
        "Return JSON keys: focus_sections, section_order, key_risks, evidence_priority, emphasis_notes.\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


async def plan_analysis(
    *,
    corp_name: str,
    intent: str,
    analyst_plan: dict[str, Any],
    evidence_graph: dict[str, Any],
    risk_flags: list[str],
) -> tuple[AnalysisPlan, dict[str, Any]]:
    prompt = build_planner_prompt(
        corp_name=corp_name,
        intent=intent,
        analyst_plan=analyst_plan,
        evidence_graph=evidence_graph,
        risk_flags=risk_flags,
    )
    result = await complete_structured(
        AnalysisPlan,
        system=PLANNER_SYSTEM_PROMPT,
        prompt=prompt,
        timeout=max(settings.LLM_TIMEOUT / 2, 1.0),
        max_tokens=700,
    )
    if result is None:
        # planner 실패는 분석 중단 사유가 아니다. deterministic analyst_plan으로 안전하게 닫는다.
        return fallback_plan(analyst_plan), {"provider": "template", "model": "rule-based", "latency_ms": 0}
    return result.data, {
        "provider": result.provider,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
    }
