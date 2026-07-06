from __future__ import annotations

import json
from typing import Any


FORBIDDEN_RULES = (
    "Do not create or alter numbers. Quote only the values in the payload.",
    "Do not add benchmark thresholds such as 100% unless the exact number appears in the payload.",
    "Do not mention metrics that are not calculated, including PER, PBR, ROIC, target price, or market price.",
    "Do not mention market capitalization or valuation multiples unless supplied in the payload.",
    "Do not provide investment advice, buy/sell language, or target prices.",
    "Do not make claims outside the supplied evidence and ratios.",
    "If a metric has status unavailable, explain the supplied reason instead of guessing a value.",
    "Avoid quoting raw large KRW trend amounts; describe large KRW trends directionally unless a formatted display value is supplied.",
    "Do not repeat schema placeholder text such as 'one Korean sentence' or '3-5 Korean analyst-style sentences'.",
)

SYSTEM_PROMPT = (
    "You are the fundamental interpretation layer for veriθ. "
    "All numeric calculations are already completed by deterministic code. "
    "Your job is only to explain the supplied financial ratios in Korean. "
    "Return strict JSON only. Do not include markdown, explanations, or <think> blocks."
)


def build_interpret_prompt(
    corp_name: str,
    score: int,
    label: str,
    ratios: dict[str, Any],
    trend: dict[str, Any],
    risk_flags: list[str],
    insights: dict[str, Any] | None = None,
    analyst_plan: dict[str, Any] | None = None,
    retrieval_context: dict[str, Any] | None = None,
    period_basis: dict[str, Any] | None = None,
) -> str:
    payload = {
        "corp_name": corp_name,
        "score": score,
        "verdict_label": label,
        "intent": (analyst_plan or {}).get("score_context", {}).get("intent", "fundamental_health"),
        "ratios": ratios,
        "trend": trend,
        "insights": insights or {},
        "analyst_plan": analyst_plan or {},
        "retrieval_context": retrieval_context or {},
        "period_basis": period_basis or {},
        "risk_flags": risk_flags,
        "rules": FORBIDDEN_RULES,
        "output_schema": {
            "verdict_label": "one of: strong, moderate, weak, insufficient_data",
            "verdict": "one Korean sentence",
            "interpretation": "5-8 Korean analyst-style sentences",
        },
    }
    return (
        "Write a professional but cautious Korean fundamental analyst interpretation for the following payload. "
        "Follow analyst_plan.section_order and use retrieval_context.ordered_evidence_briefs as the reasoning backbone. "
        "Cover profitability, stability, growth, valuation basis, shareholder context, and data limits when relevant. "
        "Treat payload.intent as the user's emphasis and lead with that section when possible. "
        "Respect period_basis exactly; if it is an interim report, never describe the numbers as full-year results. "
        "Return only one final JSON object with keys verdict_label, verdict, and interpretation. "
        "Do not include <think>, reasoning, markdown, or any text outside JSON.\n"
        "Every numeric value in the answer must already exist in the payload. "
        "Avoid generic benchmark numbers, raw large KRW trend amounts, and schema placeholder text.\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def build_retry_prompt(original_prompt: str, violations: list[str]) -> str:
    return (
        f"{original_prompt}\n\n"
        "The previous response violated these checks. Rewrite once, obeying all rules exactly:\n"
        f"{json.dumps(violations, ensure_ascii=False)}\n"
        "Remove every number that is not explicitly present in the payload, including benchmark thresholds such as 100%. "
        "Return only the final JSON object with keys verdict_label, verdict, and interpretation."
    )
