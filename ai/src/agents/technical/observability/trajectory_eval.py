"""검증 ③ 판정 로직 — LLM 문장이 코드 확정 라벨·신호를 왜곡했는지 결정론으로 검사한다.

정본: `docs/test_plan.md §5`(통과 조건·매칭 규칙·케이스). LLM-as-judge가 아니라 키워드/라벨
사전 매칭이며, 검증 로직 자체가 단위테스트 대상이다(§5.1). 사전(데이터)은 `keyword_rules.py`.

통과 조건(§5.2, 다섯 AND):
  1. 대표 표현 1개 이상 존재 (require_representative인 라벨)
  2. 무효화 규칙 적용 후 남은 충돌 표현 없음
  3. details 구조 일치 (개수 · indicator 코드값)
  4. 금지 표현 없음 (부정문 안이어도)
  5. 확정값 재생성 필드 없음

이 모듈은 **판정만** 한다. 재생성/폴백 orchestration은 supervisor, 병합은 node가 맡는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..schemas.enums import AlignmentFlag, Consensus, IndicatorType, Regime, Signal
from .keyword_rules import (
    ALIGNMENT_RULES,
    CONSENSUS_RULES,
    FORBIDDEN_TERMS,
    REGIME_RULES,
    SIGNAL_RULES,
    LabelRule,
)

# LLM 출력에 나타나면 "확정값을 재생성하려 한다"는 신호 → 실패(§5.2 조건 5, prompts §4.1).
FORBIDDEN_OUTPUT_FIELDS: frozenset[str] = frozenset(
    {
        "final_regime", "daily_regime", "weekly_trend", "monthly_trend", "alignment_flag",
        "regime_context", "consensus", "signal_score", "confidence", "confidence_level",
        "confidence_basis", "signal", "value", "metrics", "weight",
        "risk", "risk_flags", "risk_items",
    }
)


@dataclass(frozen=True)
class TargetFailure:
    """검증 실패 1건. target=어느 문장이, reason=왜, info=부가정보(충돌어·indicator 등)."""
    target: str
    reason: str
    info: str | None = None


@dataclass(frozen=True)
class EvalResult:
    passed: bool
    failures: tuple[TargetFailure, ...]

    @property
    def failed_indicators(self) -> frozenset[str]:
        """detail이 실패한 indicator 코드값 집합(부분 폴백 대상)."""
        out: set[str] = set()
        for f in self.failures:
            if f.target.startswith("technical_signals[") and f.info:
                out.add(f.info)
        return frozenset(out)

    @property
    def interpretation_failed(self) -> bool:
        return any(f.target == "interpretation.text" for f in self.failures)

    @property
    def details_structure_failed(self) -> bool:
        return any(f.target == "details" for f in self.failures)


# ─────────────────────────────────────────────────────────────────────────────
# 문자열 매칭 (test_plan §5.3)
# ─────────────────────────────────────────────────────────────────────────────
def contains_forbidden_terms(text: str) -> list[str]:
    """금지어 등장 목록(부정문 안이어도 등장 자체가 위반, §5.3 규칙 5)."""
    return [t for t in FORBIDDEN_TERMS if t in text]


def check_label(text: str, rule: LabelRule) -> str | None:
    """확정 라벨 규칙으로 text를 검사. 통과면 None, 실패면 사유 문자열.

    - 대표 표현(required_any)은 단순 포함 매칭(§5.3 규칙 1).
    - 충돌 표현 검사 전에 문장에 실제로 등장한 대표 표현 구간을 마스킹한다(긴 것부터).
      이로써 대표 표현과 겹치는 짧은 충돌어를 무효화한다(§5.3 규칙 3).
    - 남은 텍스트에서 충돌 표현을 긴 것부터 찾는다(§5.3 규칙 2).
    """
    if rule.require_representative and rule.required_any and not any(t in text for t in rule.required_any):
        return "missing_required"

    masked = text
    for term in sorted(rule.required_any, key=len, reverse=True):
        if term in masked:
            masked = masked.replace(term, " " * len(term))

    for conflict in sorted(rule.conflict_any, key=len, reverse=True):
        if conflict in masked:
            return f"conflict:{conflict}"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 개별 검사
# ─────────────────────────────────────────────────────────────────────────────
def _check_forbidden_output_fields(llm_output: dict) -> list[TargetFailure]:
    """LLM이 확정값 필드를 되돌려주면 실패(§5.2 조건 5)."""
    failures: list[TargetFailure] = []
    for key in llm_output:
        if key in FORBIDDEN_OUTPUT_FIELDS:
            failures.append(TargetFailure("output", "forbidden_output_field", key))
    for entry in llm_output.get("details", []) or []:
        if not isinstance(entry, dict):
            continue
        for key in entry:
            if key in FORBIDDEN_OUTPUT_FIELDS:
                failures.append(TargetFailure("details", "forbidden_output_field", key))
    return failures


def evaluate_text(
    text: str,
    *,
    final_regime: Regime,
    consensus: Consensus,
    alignment_flag: AlignmentFlag,
) -> list[TargetFailure]:
    """interpretation.text를 regime·consensus·alignment 확정값과 금지어로 검사."""
    target = "interpretation.text"
    failures: list[TargetFailure] = []

    if not isinstance(text, str) or not text.strip():
        return [TargetFailure(target, "missing_text")]

    for term in contains_forbidden_terms(text):
        failures.append(TargetFailure(target, "forbidden_term", term))

    for rule in (
        REGIME_RULES.get(final_regime),
        CONSENSUS_RULES.get(consensus),
        ALIGNMENT_RULES.get(alignment_flag),
    ):
        if rule is None:  # regime=unavailable 등 사전 없는 값은 이 경로로 오지 않는다(폴백 처리).
            continue
        reason = check_label(text, rule)
        if reason is not None:
            failures.append(TargetFailure(target, reason))
    return failures


def evaluate_details(
    details: object,
    *,
    signals: Sequence[tuple[IndicatorType, Signal]],
) -> list[TargetFailure]:
    """details 구조(개수·indicator 일치) + 각 detail의 signal 왜곡·금지어 검사."""
    failures: list[TargetFailure] = []
    expected = {ind.value: sig for ind, sig in signals}

    if not isinstance(details, list):
        return [TargetFailure("details", "missing_details")]

    if len(details) != len(expected):
        failures.append(TargetFailure("details", "count_mismatch",
                                       f"{len(details)}!={len(expected)}"))

    seen: set[str] = set()
    for entry in details:
        if not isinstance(entry, dict):
            failures.append(TargetFailure("details", "invalid_entry"))
            continue
        indicator = entry.get("indicator")
        detail_text = entry.get("detail", "")
        if indicator not in expected:
            failures.append(TargetFailure("details", "indicator_mismatch", str(indicator)))
            continue
        seen.add(indicator)
        target = f"technical_signals[{indicator}].detail"
        if not isinstance(detail_text, str) or not detail_text.strip():
            failures.append(TargetFailure(target, "missing_text", indicator))
            continue
        for term in contains_forbidden_terms(detail_text):
            failures.append(TargetFailure(target, "forbidden_term", indicator))
        rule = SIGNAL_RULES.get(expected[indicator])
        if rule is not None:
            reason = check_label(detail_text, rule)
            if reason is not None:
                failures.append(TargetFailure(target, reason, indicator))

    for missing in expected.keys() - seen:
        failures.append(TargetFailure("details", "indicator_missing", missing))

    return failures


# ─────────────────────────────────────────────────────────────────────────────
# 상위 진입점
# ─────────────────────────────────────────────────────────────────────────────
def evaluate(
    llm_output: dict,
    *,
    final_regime: Regime,
    consensus: Consensus,
    alignment_flag: AlignmentFlag,
    signals: Sequence[tuple[IndicatorType, Signal]],
) -> EvalResult:
    """LLM 출력(파싱된 dict)을 코드 확정값과 대조해 검증 ③ 결과를 낸다.

    llm_output = {"interpretation_text": str, "details": [{"indicator": str, "detail": str}, ...]}
    signals    = 코드 확정 (indicator, signal) 목록.
    """
    failures: list[TargetFailure] = []
    failures.extend(_check_forbidden_output_fields(llm_output))
    failures.extend(
        evaluate_text(
            llm_output.get("interpretation_text", ""),
            final_regime=final_regime,
            consensus=consensus,
            alignment_flag=alignment_flag,
        )
    )
    failures.extend(evaluate_details(llm_output.get("details"), signals=signals))
    return EvalResult(passed=not failures, failures=tuple(failures))
