from typing import Any

from ..report.formatting import format_metric_value


LABEL_TEXT = {
    "strong": "재무 체력이 양호한 편입니다",
    "moderate": "재무 체력은 보통 수준입니다",
    "weak": "재무 체력이 약한 편입니다",
    "insufficient_data": "재무 판단에 필요한 핵심 데이터가 부족합니다",
}


def _display_metric(ratios: dict[str, Any], metric: str) -> str:
    item = ratios.get(metric, {})
    if item.get("value") is None:
        return f"{item.get('label', metric)}는 산출 불가입니다"
    return f"{item.get('label', metric)}는 {format_metric_value(item.get('value'), item.get('unit', ''))}"


def _reason(ratios: dict[str, Any], metric: str) -> str | None:
    reason = ratios.get(metric, {}).get("reason")
    return str(reason) if reason else None


def build_fallback_interpretation(
    corp_name: str,
    score: int,
    label: str,
    ratios: dict[str, Any],
    risk_flags: list[str] | None = None,
) -> tuple[str, str]:
    verdict = f"{corp_name}은 현재 점수 {score}점 기준으로 {LABEL_TEXT[label]}."
    parts = [
        f"수익성은 {_display_metric(ratios, 'roe')}, {_display_metric(ratios, 'operating_margin')}을 중심으로 확인됩니다.",
        f"안정성은 {_display_metric(ratios, 'debt_ratio')}, {_display_metric(ratios, 'current_ratio')}을 함께 봐야 합니다.",
        f"성장성은 {_display_metric(ratios, 'revenue_growth')}, {_display_metric(ratios, 'operating_income_growth')}로 요약됩니다.",
        f"밸류에이션 기초 지표는 {_display_metric(ratios, 'eps')}, {_display_metric(ratios, 'bps')}로 제한적으로 확인됩니다.",
    ]
    missing_reasons = [_reason(ratios, metric) for metric in ("roe", "operating_margin", "debt_ratio", "current_ratio", "revenue_growth", "operating_income_growth", "eps", "bps")]
    missing_reasons = [reason for reason in missing_reasons if reason]
    if missing_reasons:
        parts.append(f"산출 불가 항목은 {missing_reasons[0]}")
    if risk_flags:
        parts.append(f"데이터 한계 플래그는 {', '.join(risk_flags[:4])}입니다.")
    parts.append("본 문장은 DART 재무제표 기반 정보 제공용이며 투자 권유가 아닙니다.")
    interpretation = " ".join(parts)
    return verdict, interpretation
