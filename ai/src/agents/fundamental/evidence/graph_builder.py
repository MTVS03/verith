from __future__ import annotations

from typing import Any

from ..core.contract import Evidence
from ..report.formatting import format_metric_value


SECTION_METRICS = {
    "profitability": ("roe", "operating_margin", "net_margin"),
    "stability": ("debt_ratio", "current_ratio"),
    "growth": ("revenue_growth", "operating_income_growth"),
    "valuation_basis": ("eps", "bps"),
}


SECTION_LABELS = {
    "profitability": "수익성",
    "stability": "재무 안정성",
    "growth": "성장성",
    "valuation_basis": "밸류에이션 기초",
    "shareholder": "주주/배당/감사의견",
    "data_limits": "데이터 한계",
}


def _metric_display(item: dict[str, Any]) -> str:
    return item.get("display_value") or format_metric_value(item.get("value"), item.get("unit", ""))


def _has_final_consonant(text: str) -> bool:
    for char in reversed(text.strip()):
        code = ord(char)
        if 0xAC00 <= code <= 0xD7A3:
            return (code - 0xAC00) % 28 != 0
        if char.isdigit() or char in {"%", "원"}:
            return True
    return True


def _object_particle(text: str) -> str:
    return "을" if _has_final_consonant(text) else "를"


def _stance(metric: str, value: float | int | None, status: str = "available") -> str:
    if status == "not_meaningful":
        return "caution"
    if value is None:
        return "missing"
    if metric in {"roe", "operating_margin", "net_margin", "revenue_growth", "operating_income_growth"}:
        return "supportive" if value > 0 else "caution"
    if metric == "current_ratio":
        return "supportive" if value >= 100 else "caution"
    if metric == "debt_ratio":
        if value <= 120:
            return "supportive"
        if value <= 200:
            return "watch"
        return "caution"
    if metric == "eps":
        return "supportive" if value > 0 else "caution"
    return "context"


def _section_signal(metrics: list[dict[str, Any]]) -> str:
    stances = [item["stance"] for item in metrics]
    if not metrics or all(stance == "missing" for stance in stances):
        return "insufficient"
    if "caution" in stances:
        return "caution"
    if "watch" in stances:
        return "watch"
    return "supportive"


def _section_summary(section: str, metrics: list[dict[str, Any]]) -> str:
    if not metrics:
        return f"{SECTION_LABELS[section]} 판단에 사용할 계산 지표가 부족합니다."
    available = [item for item in metrics if item["stance"] != "missing"]
    missing = [item for item in metrics if item["stance"] == "missing"]
    if not available:
        return f"{SECTION_LABELS[section]} 지표가 산출 불가하여 데이터 한계를 먼저 설명해야 합니다."
    values = ", ".join(f"{item['label']} {item['display_value']}" for item in available if item.get("display_value"))
    suffix = f" 산출 불가 지표: {', '.join(item['label'] for item in missing)}." if missing else ""
    return f"{SECTION_LABELS[section]} 지표는 {values}{_object_particle(values)} 중심으로 판단합니다.{suffix}"


def _join_context(parts: list[str]) -> str:
    clean = [part for part in parts if part and "산출 불가" not in part]
    return ", ".join(clean) if clean else "추가로 확인 가능한 정성 정보가 제한적입니다."


def build_evidence_graph(
    ratios: dict[str, Any],
    trend: dict[str, Any],
    insights: dict[str, Any],
    evidence: list[Evidence],
    risk_flags: list[str],
) -> dict[str, Any]:
    metric_nodes: dict[str, dict[str, Any]] = {}
    for metric, item in ratios.items():
        metric_nodes[metric] = {
            "id": f"metric:{metric}",
            "type": "metric",
            "metric": metric,
            "label": item.get("label", metric),
            "category": item.get("category", ""),
            "value": item.get("value"),
            "unit": item.get("unit", ""),
            "display_value": _metric_display(item),
            "status": item.get("status", "available"),
            "stance": _stance(metric, item.get("value"), item.get("status", "available")),
            "reason": item.get("reason", ""),
        }

    filing_nodes: dict[str, dict[str, Any]] = {}
    account_edges: list[dict[str, str]] = []
    for item in evidence:
        filing_nodes[item.rcept_no] = {
            "id": f"filing:{item.rcept_no}",
            "type": "filing",
            "rcept_no": item.rcept_no,
            "source_url": item.source_url,
        }
        account_edges.append(
            {
                "from": f"metric:{item.metric}",
                "to": f"filing:{item.rcept_no}",
                "relation": "supported_by",
                "accounts": ", ".join(item.account_ids),
            }
        )

    sections: list[dict[str, Any]] = []
    for section, metric_keys in SECTION_METRICS.items():
        metrics = [metric_nodes[key] for key in metric_keys if key in metric_nodes]
        sections.append(
            {
                "id": section,
                "label": SECTION_LABELS[section],
                "signal": _section_signal(metrics),
                "metrics": [item["metric"] for item in metrics],
                "summary": _section_summary(section, metrics),
            }
        )

    shareholder = insights.get("major_holder") or {}
    audit = insights.get("audit") or {}
    dividend = insights.get("dividend") or {}
    shareholder_context = _join_context(
        [
            f"최대주주 {shareholder.get('name')}" if shareholder.get("name") else "",
            f"지분율 {format_metric_value(shareholder.get('ratio'), '%')}" if shareholder.get("ratio") is not None else "",
            f"DART EPS {format_metric_value(dividend.get('dart_eps'), '원')}" if dividend.get("dart_eps") is not None else "",
            f"감사의견 {audit.get('opinion')}" if audit.get("opinion") else "",
        ]
    )
    sections.append(
        {
            "id": "shareholder",
            "label": SECTION_LABELS["shareholder"],
            "signal": "context",
            "metrics": [],
            "summary": f"주주/배당/감사의견은 {shareholder_context} 정보를 참고합니다.",
        }
    )

    if risk_flags:
        sections.append(
            {
                "id": "data_limits",
                "label": SECTION_LABELS["data_limits"],
                "signal": "caution",
                "metrics": [],
                "summary": f"데이터 한계와 검증 플래그: {', '.join(risk_flags)}.",
            }
        )

    return {
        "nodes": list(metric_nodes.values()) + list(filing_nodes.values()),
        "edges": account_edges,
        "sections": sections,
        "trend_display": trend.get("display", {}),
    }


def build_analyst_plan(evidence_graph: dict[str, Any], score: int, label: str, intent: str = "fundamental_health") -> dict[str, Any]:
    sections = evidence_graph.get("sections", [])
    priorities = []
    intent_section = {
        "profitability": "profitability",
        "stability": "stability",
        "growth": "growth",
        "valuation": "valuation_basis",
    }.get(intent)
    if intent_section:
        priorities.append(intent_section)
    for section in sections:
        if section.get("signal") in {"caution", "watch", "insufficient"}:
            priorities.append(section["id"])
    for section in sections:
        if section["id"] not in priorities:
            priorities.append(section["id"])

    return {
        "objective": "DART 근거와 계산 지표만 사용해 전문적이고 보수적인 재무 리포트를 작성합니다.",
        "score_context": {
            "score": score,
            "label": label,
            "intent": intent,
            "interpretation_rule": "절대 재무점수와 지표별 원인을 분리해서 설명합니다.",
        },
        "section_order": priorities,
        "section_briefs": {section["id"]: section["summary"] for section in sections},
        "writing_rules": [
            "첫 문장은 투자 판단이 아니라 재무 상태 진단으로 시작합니다.",
            "수익성, 안정성, 성장성, 밸류에이션 기초, 데이터 한계를 분리해 설명합니다.",
            "숫자는 payload에 있는 값만 사용합니다.",
            "매수, 매도, 목표가, 투자 권유 표현은 금지합니다.",
        ],
    }


def build_retrieval_context(evidence_graph: dict[str, Any], analyst_plan: dict[str, Any]) -> dict[str, Any]:
    briefs = analyst_plan.get("section_briefs", {})
    ordered = analyst_plan.get("section_order", [])
    return {
        "ordered_evidence_briefs": [briefs[key] for key in ordered if key in briefs],
        "metric_claims": [
            {
                "metric": node["metric"],
                "label": node["label"],
                "display_value": node["display_value"],
                "stance": node["stance"],
            }
            for node in evidence_graph.get("nodes", [])
            if node.get("type") == "metric"
        ],
    }
