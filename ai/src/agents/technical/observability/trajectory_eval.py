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

from ..schemas.enums import (
    AlignmentFlag,
    ConfidenceLevel,
    Consensus,
    IndicatorType,
    Regime,
    RiskFlag,
    Signal,
)
from .keyword_rules import (
    ALIGNMENT_RULES,
    CONFIDENCE_RULES,
    CONSENSUS_RULES,
    FORBIDDEN_TERMS,
    REGIME_RULES,
    RISK_MENTION_TERMS,
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
def _strip_md(text: str) -> str:
    """verify 는 **마크다운 기호를 제거한 plain text** 기준으로 검사한다. 핵심 조건 bold(`**...**`)로 인해
    대표 표현이 `**지지** 구간`처럼 별표로 쪼개져 부분 매칭이 깨지는 것을 방지한다(별표만 제거·내용 보존)."""
    return text.replace("**", "")


def contains_forbidden_terms(text: str) -> list[str]:
    """금지어 등장 목록(부정문 안이어도 등장 자체가 위반, §5.3 규칙 5). 마크다운 제거 후 검사."""
    plain = _strip_md(text)
    return [t for t in FORBIDDEN_TERMS if t in plain]


def check_label(text: str, rule: LabelRule) -> list[str]:
    """확정 라벨 규칙으로 text를 검사. 통과면 빈 리스트, 실패면 사유 리스트.

    - 대표 표현(required_any) 부재와 충돌 표현을 **둘 다** 보고한다(하나에서 멈추지 않음).
    - 대표 표현은 단순 포함 매칭(§5.3 규칙 1).
    - 충돌 표현 검사 전에 문장에 실제로 등장한 대표 표현 구간을 마스킹한다(긴 것부터).
      이로써 대표 표현과 겹치는 짧은 충돌어를 무효화한다(§5.3 규칙 3).
    - 남은 텍스트에서 충돌 표현을 긴 것부터 찾는다(§5.3 규칙 2), 첫 충돌 1건만 보고.
    """
    reasons: list[str] = []
    text = _strip_md(text)  # 마크다운 별표 제거 후 대표/충돌 표현 매칭(부분 bold 로 인한 매칭 깨짐 방지)
    if rule.require_representative and rule.required_any and not any(t in text for t in rule.required_any):
        reasons.append("missing_required")

    masked = text
    for term in sorted(rule.required_any, key=len, reverse=True):
        if term in masked:
            masked = masked.replace(term, " " * len(term))

    for conflict in sorted(rule.conflict_any, key=len, reverse=True):
        if conflict in masked:
            reasons.append(f"conflict:{conflict}")
            break
    return reasons


# ─────────────────────────────────────────────────────────────────────────────
# 개별 검사
# ─────────────────────────────────────────────────────────────────────────────
def _check_forbidden_output_fields(llm_output: dict) -> list[TargetFailure]:
    """LLM 출력 어느 깊이든 확정값 필드 key가 있으면 실패(§5.2 조건 5, 중첩 포함)."""
    failures: list[TargetFailure] = []
    _walk_forbidden_fields(llm_output, failures)
    return failures


def _walk_forbidden_fields(node: object, failures: list[TargetFailure]) -> None:
    """dict/list를 재귀 순회하며 FORBIDDEN_OUTPUT_FIELDS key를 탐지한다."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in FORBIDDEN_OUTPUT_FIELDS:
                failures.append(TargetFailure("output", "forbidden_output_field", key))
            _walk_forbidden_fields(value, failures)
    elif isinstance(node, list):
        for item in node:
            _walk_forbidden_fields(item, failures)


def evaluate_text(
    text: str,
    *,
    final_regime: Regime,
    consensus: Consensus,
    alignment_flag: AlignmentFlag,
    confidence_level: ConfidenceLevel | None = None,
    risk_flags: Sequence[RiskFlag] = (),
) -> list[TargetFailure]:
    """interpretation.text를 확정값(regime·consensus·alignment·confidence)·금지어·risk 언급으로 검사.

    confidence_level·risk_flags는 선택 입력(None/빈값이면 해당 검사 생략) — 노드 verify는 항상 넘긴다.
    """
    target = "interpretation.text"
    failures: list[TargetFailure] = []

    if not isinstance(text, str) or not text.strip():
        return [TargetFailure(target, "missing_text")]

    for term in contains_forbidden_terms(text):
        failures.append(TargetFailure(target, "forbidden_term", term))

    rules = [
        REGIME_RULES.get(final_regime),
        CONSENSUS_RULES.get(consensus),
        ALIGNMENT_RULES.get(alignment_flag),
    ]
    if confidence_level is not None:
        rules.append(CONFIDENCE_RULES.get(confidence_level))
    for rule in rules:
        if rule is None:  # regime=unavailable 등 사전 없는 값은 이 경로로 오지 않는다(폴백 처리).
            continue
        for reason in check_label(text, rule):
            failures.append(TargetFailure(target, reason))

    if risk_flags and not _mentions_any_risk(text, risk_flags):
        failures.append(TargetFailure(target, "risk_not_mentioned"))

    return failures


def _mentions_any_risk(text: str, risk_flags: Sequence[RiskFlag]) -> bool:
    """확정 risk flag 중 최소 하나의 판정어가 문장에 등장하는지(전부 나열은 불필요)."""
    for flag in risk_flags:
        for term in RISK_MENTION_TERMS.get(flag, ()):
            if term in text:
                return True
    return False


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
            for reason in check_label(detail_text, rule):
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
    confidence_level: ConfidenceLevel | None = None,
    risk_flags: Sequence[RiskFlag] = (),
) -> EvalResult:
    """LLM 출력(파싱된 dict)을 코드 확정값과 대조해 검증 ③ 결과를 낸다.

    llm_output = {"interpretation_text": str, "details": [{"indicator": str, "detail": str}, ...]}
    signals    = 코드 확정 (indicator, signal) 목록.
    confidence_level·risk_flags = 확정 신뢰도 구간·리스크 flag(반대 라벨 단정·risk 누락 검사용).
    """
    failures: list[TargetFailure] = []
    failures.extend(_check_forbidden_output_fields(llm_output))
    failures.extend(
        evaluate_text(
            llm_output.get("interpretation_text", ""),
            final_regime=final_regime,
            consensus=consensus,
            alignment_flag=alignment_flag,
            confidence_level=confidence_level,
            risk_flags=risk_flags,
        )
    )
    failures.extend(evaluate_details(llm_output.get("details"), signals=signals))
    failures.extend(_evaluate_sections(llm_output))
    return EvalResult(passed=not failures, failures=tuple(failures))


# 구조화 섹션(additive) 문자열에도 금지어(투자 조언·미래 단정)가 새지 않도록 스캔한다. 라벨 요구 검사는
# interpretation_text 에만 적용하고, 섹션은 forbidden-term 안전성만 본다(과도한 결합 회피).
_SECTION_STR_KEYS = (
    "one_line_summary", "trend_interpretation", "signal_interpretation", "risk_interpretation",
    "timeframe_alignment", "what_to_watch_next", "invalidation_or_caution",
)
_SECTION_LIST_KEYS = ("key_drivers", "warning_points")


def _evaluate_sections(llm_output: dict) -> list[TargetFailure]:
    failures: list[TargetFailure] = []
    for key in _SECTION_STR_KEYS:
        val = llm_output.get(key)
        if isinstance(val, str):
            for term in contains_forbidden_terms(val):
                failures.append(TargetFailure(f"interpretation.{key}", "forbidden_term", term))
    for key in _SECTION_LIST_KEYS:
        val = llm_output.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    for term in contains_forbidden_terms(item):
                        failures.append(TargetFailure(f"interpretation.{key}", "forbidden_term", term))
    return failures
