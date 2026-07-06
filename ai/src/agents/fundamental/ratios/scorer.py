from typing import Any

from ..core.config import SCORE_TABLES


LABEL_DISPLAY = {
    "strong": "양호",
    "moderate": "중립",
    "weak": "주의",
    "insufficient_data": "데이터 제한",
}


def display_label(label: str) -> str:
    return LABEL_DISPLAY.get(label, label)


GROWTH_METRICS = {"revenue_growth", "operating_income_growth"}
METRIC_COMPONENTS = {
    "roe": "profitability",
    "operating_margin": "profitability",
    "debt_ratio": "stability",
    "current_ratio": "stability",
    "revenue_growth": "growth",
    "operating_income_growth": "growth",
}


def _interpolate_score(value: float, table: list[tuple[float, int]]) -> float:
    anchors = sorted((float(threshold), float(points)) for threshold, points in table)
    if value <= anchors[0][0]:
        return anchors[0][1]
    if value >= anchors[-1][0]:
        return anchors[-1][1]
    for (left_value, left_points), (right_value, right_points) in zip(anchors, anchors[1:], strict=False):
        if left_value <= value <= right_value:
            span = right_value - left_value
            if span == 0:
                return right_points
            ratio = (value - left_value) / span
            return left_points + (right_points - left_points) * ratio
    return 0.0


def _max_points(table: list[tuple[float, int]]) -> float:
    return float(max(points for _, points in table))


def _score_higher_better(value: float | None, table: list[tuple[float, int]]) -> float:
    if value is None:
        return 0.0
    return _interpolate_score(float(value), table)


def _score_lower_better(value: float | None, table: list[tuple[float, int]]) -> float:
    if value is None:
        return 0.0
    return _interpolate_score(float(value), table)


def _metric_value(item: dict[str, Any]) -> float | None:
    metric_value = item.get("value")
    return metric_value if isinstance(metric_value, int | float) and not isinstance(metric_value, bool) else None


def _metric_points(metric: str, item: dict[str, Any]) -> tuple[float, float] | None:
    table = SCORE_TABLES[metric]
    value = _metric_value(item)
    if value is not None:
        scorer = _score_lower_better if metric == "debt_ratio" else _score_higher_better
        return scorer(value, table), _max_points(table)
    direction = item.get("direction")
    if metric in GROWTH_METRICS and direction:
        max_points = _max_points(table)
        points = max_points / 2 if direction == "turnaround_positive" else 0.0
        return points, max_points
    return None


def score_financials(ratios: dict[str, Any]) -> tuple[int, dict[str, Any], str]:
    earned_by_component = {"profitability": 0.0, "stability": 0.0, "growth": 0.0}
    attainable_by_component = {"profitability": 0.0, "stability": 0.0, "growth": 0.0}
    scored_metrics: list[dict[str, Any]] = []
    skipped_metrics: list[str] = []

    for metric, component in METRIC_COMPONENTS.items():
        item = ratios.get(metric, {})
        result = _metric_points(metric, item)
        if result is None:
            skipped_metrics.append(metric)
            continue
        points, max_points = result
        earned_by_component[component] += points
        attainable_by_component[component] += max_points
        scored_metrics.append(
            {
                "metric": metric,
                "value": item.get("value"),
                "direction": item.get("direction"),
                "points": round(points, 2),
                "max_points": int(max_points),
            }
        )

    earned = sum(earned_by_component.values())
    attainable_max = sum(attainable_by_component.values())
    score = round(earned / attainable_max * 100) if attainable_max else 0
    missing_core = sum(metric in skipped_metrics for metric in ("roe", "operating_margin", "debt_ratio"))
    if len(scored_metrics) < 3 or missing_core >= 2:
        label = "insufficient_data"
    elif score >= 70:
        label = "strong"
    elif score >= 45:
        label = "moderate"
    else:
        label = "weak"
    explanation = (
        "절대 재무점수는 ROE/영업이익률, 부채비율/유동비율, 매출/영업이익 성장률을 "
        "보수적으로 합산한 100점 기준입니다. 업황이 약하거나 적자/역성장 구간이면 "
        "리포트 데이터가 충분해도 점수가 낮게 나올 수 있습니다."
    )
    return (
        score,
        {
            "profitability": round(earned_by_component["profitability"], 2),
            "stability": round(earned_by_component["stability"], 2),
            "growth": round(earned_by_component["growth"], 2),
            "score_basis": "100",
            "score_type": "absolute_financial_health",
            "label_display": display_label(label),
            "score_explanation": explanation,
            "attainable_max": int(attainable_max),
            "earned_points": round(earned, 2),
            "scored_metrics": scored_metrics,
            "skipped_metrics": skipped_metrics,
            "component_attainable_max": {
                key: int(value) for key, value in attainable_by_component.items()
            },
            "component_max": {"profitability": 40, "stability": 30, "growth": 30},
        },
        label,
    )


def confidence_from(ratios: dict[str, Any], risk_flags: list[str]) -> float:
    missing_count = sum(1 for item in ratios.values() if item.get("value") is None)
    confidence = 0.9 - missing_count * 0.05
    if "OFS_FALLBACK" in risk_flags:
        confidence -= 0.05
    if "LLM_FALLBACK_TEMPLATE" in risk_flags:
        confidence -= 0.05
    if "EVIDENCE_UNBOUND_EXCLUDED" in risk_flags:
        confidence -= 0.1
    if any(flag.startswith("VERIFY_") for flag in risk_flags):
        confidence -= 0.1
    return round(max(confidence, 0.3), 2)
