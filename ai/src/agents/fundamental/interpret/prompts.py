from __future__ import annotations

import json
from typing import Any

from ..verify.verdict_guard import _allowed_numbers


FORBIDDEN_RULES = (
    # 프롬프트 규칙은 verify guard와 같은 경계를 미리 알려 LLM 재생성 비용을 줄인다.
    "Do not create or alter numbers. Quote only the values in the payload.",
    "Do not add benchmark thresholds such as 100% unless the exact number appears in the payload.",
    "Do not mention metrics that are not calculated, including PER, PBR, ROIC, target price, or market price.",
    "Do not mention Korean market indicators such as 주가, 목표주가, 적정주가, 시가총액, PER, PBR, or ROIC.",
    "Do not mention market capitalization or valuation multiples unless supplied in the payload.",
    "Do not provide investment advice, buy/sell language, or target prices.",
    "Do not make claims outside the supplied evidence and ratios.",
    "If a metric has status unavailable, explain the supplied reason instead of guessing a value.",
    "If a growth rate is marked low_base or its absolute value exceeds 300%, do not quote the percent; describe only the direction and the low-base caveat.",
    "Avoid quoting raw large KRW trend amounts; describe large KRW trends directionally unless a formatted display value is supplied.",
    "Do not repeat schema placeholder text such as 'one Korean sentence' or '3-5 Korean analyst-style sentences'.",
)

SYSTEM_PROMPT = (
    "You are the fundamental interpretation layer for veriθ. "
    "All numeric calculations are already completed by deterministic code. "
    "Your job is only to explain the supplied financial ratios in Korean. "
    "Never mention market-price or valuation-multiple terms that are not supplied, including 주가, 목표주가, 적정주가, 시가총액, PER, PBR, and ROIC. "
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
    # allowed_numbers는 검증 가능한 수치 화이트리스트다. 여기에 없는 숫자는 verdict_guard에서 막힌다.
    allowed_numbers = sorted(
        {
            round(value, 4)
            for value in _allowed_numbers(ratios, [], trend, insights or {})
            if isinstance(value, (int, float))
        }
        | {float(score)}
    )
    selected_paths = (retrieval_context or {}).get("selected_paths", [])
    compact_ratios = {
        key: {
            "label": value.get("label", key),
            "display_value": value.get("display_value"),
            "status": value.get("status", "available"),
            "direction": value.get("direction"),
            "reason": value.get("reason", ""),
        }
        for key, value in ratios.items()
    }
    payload = {
        "corp_name": corp_name,
        "score": score,
        "verdict_label": label,
        "allowed_numbers": allowed_numbers,
        "intent": (analyst_plan or {}).get("score_context", {}).get("intent", "fundamental_health"),
        "ratios": compact_ratios,
        "trend": {"years": trend.get("years", []), "display": trend.get("display", {})},
        "insights": insights or {},
        "analyst_plan": analyst_plan or {},
        "retrieval_context": {
            "ordered_evidence_briefs": (retrieval_context or {}).get("ordered_evidence_briefs", []),
            "selected_paths": selected_paths,
            "agent_focus_sections": (retrieval_context or {}).get("agent_focus_sections", []),
            "agent_emphasis_notes": (retrieval_context or {}).get("agent_emphasis_notes", []),
        },
        "period_basis": period_basis or {},
        "risk_flags": risk_flags,
        "rules": FORBIDDEN_RULES,
        "output_schema": {
            "verdict_label": "one of: strong, moderate, weak, insufficient_data",
            "verdict": "one Korean sentence",
            "interpretation": "5-8 Korean analyst-style sentences",
        },
        "violation_examples": [
            {
                "bad": "주가가 저평가되어 있습니다.",
                "reason": "주가, 목표주가, 시가총액, PER/PBR/ROIC는 payload에 없는 시장지표이므로 금지합니다.",
            },
            {
                "bad": "부채비율은 업계 평균 100% 대비 높습니다.",
                "reason": "allowed_numbers에 없는 벤치마크 숫자와 외부 비교를 만들면 안 됩니다.",
            },
        ],
    }
    return (
        "Write a professional but cautious Korean fundamental analyst interpretation for the following payload. "
        "Follow analyst_plan.section_order and use retrieval_context.ordered_evidence_briefs as the reasoning backbone. "
        "Cover profitability, stability, growth, valuation basis, shareholder context, and data limits when relevant. "
        "Treat payload.intent as the user's emphasis and lead with that section when possible. "
        "Respect period_basis exactly; if it is an interim report, never describe the numbers as full-year results. "
        "Return only one final JSON object with keys verdict_label, verdict, and interpretation. "
        "Do not include <think>, reasoning, markdown, or any text outside JSON.\n"
        "Every numeric value in the answer must be included in payload.allowed_numbers. "
        "Avoid generic benchmark numbers, market indicators such as 주가 or PER, raw large KRW trend amounts, and schema placeholder text.\n"
        "When growth metrics are marked low_base, use the display_value and reason instead of inventing or quoting an extreme percent.\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def build_retry_prompt(original_prompt: str, violations: list[str]) -> str:
    return (
        f"{original_prompt}\n\n"
        "The previous response violated these checks. Rewrite once, obeying all rules exactly:\n"
        f"{json.dumps(violations, ensure_ascii=False)}\n"
        "Remove every number that is not explicitly present in the payload, including benchmark thresholds such as 100%. "
        "Remove every unsupported market indicator term, especially 주가, 목표주가, 적정주가, 시가총액, PER, PBR, and ROIC. "
        "Return only the final JSON object with keys verdict_label, verdict, and interpretation."
    )
