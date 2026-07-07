from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..core.contract import Evidence


FORBIDDEN_PATTERNS = (
    re.compile(r"(?<!아닙니다\s)(?<!아닌\s)(매수|매도|목표주가|적정주가|투자\s*추천)"),
)
UNSUPPORTED_METRICS = {
    "PER": re.compile(r"(?<![A-Za-z])PER(?![A-Za-z])", re.IGNORECASE),
    "PBR": re.compile(r"(?<![A-Za-z])PBR(?![A-Za-z])", re.IGNORECASE),
    "ROIC": re.compile(r"(?<![A-Za-z])ROIC(?![A-Za-z])", re.IGNORECASE),
    "주가": re.compile(r"(?<![가-힣])주가(?!치)"),
    "시가총액": re.compile(r"시가총액"),
}
PLACEHOLDER_PATTERNS = (
    re.compile(r"(한\s*문장|3\s*-\s*5\s*문장|one Korean sentence|3-5 Korean)", re.IGNORECASE),
)
BENCHMARK_NUMBERS = {0.0, 100.0}
EXTREME_PERCENT_LIMIT = 300.0


@dataclass
class GuardResult:
    ok: bool
    violations: list[str]


def _numbers(text: str) -> list[float]:
    values: list[float] = []
    for raw, unit, suffix in re.findall(r"([-+]?\d[\d,]*(?:\.\d+)?)\s*(%p|%|원|점)\s*([가-힣]{0,8})", text):
        if unit == "%p":
            continue
        normalized = raw.replace(",", "")
        try:
            value = float(normalized)
        except ValueError:
            continue
        if value > 0 and any(token in suffix for token in ("감소", "하락", "줄", "부진")):
            value = -value
        if 2020 <= value <= 2030:
            continue
        values.append(value)
    return values


def _extract_numbers(data: Any) -> list[float]:
    values: list[float] = []
    if isinstance(data, dict):
        for value in data.values():
            values.extend(_extract_numbers(value))
    elif isinstance(data, list):
        for value in data:
            values.extend(_extract_numbers(value))
    elif isinstance(data, (int, float)):
        values.append(float(data))
    return values


def _allowed_numbers(
    ratios: dict[str, Any],
    evidence: list[Evidence],
    trend: dict[str, Any] | None = None,
    insights: dict[str, Any] | None = None,
) -> list[float]:
    values: list[float] = []
    for item in ratios.values():
        value = item.get("value")
        if isinstance(value, (int, float)):
            if item.get("unit") == "%" and abs(float(value)) > EXTREME_PERCENT_LIMIT:
                continue
            values.append(float(value))
    values.extend(float(item.value) for item in evidence)
    if trend:
        for series in trend.values():
            if not isinstance(series, list):
                continue
            for value in series:
                if isinstance(value, (int, float)):
                    values.append(float(value))
    if insights:
        values.extend(_extract_numbers(insights))
    return values


def _matches_allowed(value: float, allowed: list[float]) -> bool:
    if value in BENCHMARK_NUMBERS:
        return True
    for candidate in allowed:
        if abs(value - candidate) <= 0.05:
            return True
        if abs(value - round(candidate, 1)) <= 0.05:
            return True
        if abs(value - round(candidate)) <= 0.05:
            return True
    return False


def guard_llm_output(
    verdict: str,
    interpretation: str,
    ratios: dict[str, Any],
    evidence: list[Evidence],
    *,
    score: int | None = None,
    trend: dict[str, Any] | None = None,
    insights: dict[str, Any] | None = None,
) -> GuardResult:
    # LLM 문장에 등장한 숫자는 계산 결과, evidence, trend, insight, score 화이트리스트 안에 있어야 한다.
    text = f"{verdict}\n{interpretation}"
    violations: list[str] = []
    allowed = _allowed_numbers(ratios, evidence, trend, insights)
    if score is not None:
        allowed.append(float(score))

    for pattern in FORBIDDEN_PATTERNS:
        if pattern.search(text):
            violations.append("forbidden investment expression")
            break

    for metric, pattern in UNSUPPORTED_METRICS.items():
        if pattern.search(text):
            violations.append(f"unsupported metric mentioned: {metric}")

    for pattern in PLACEHOLDER_PATTERNS:
        if pattern.search(text):
            violations.append("schema placeholder text returned")
            break

    for value in _numbers(text):
        if not _matches_allowed(value, allowed):
            violations.append(f"unbound or altered number: {value:g}")

    return GuardResult(ok=not violations, violations=violations)
