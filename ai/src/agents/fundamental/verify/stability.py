from __future__ import annotations

from dataclasses import dataclass, field


LABEL_TERMS = {
    "strong": ("양호", "우수", "견조", "강"),
    "moderate": ("보통", "중립", "혼재", "제한적", "관찰"),
    "weak": ("약", "주의", "부진", "취약", "압박", "제한"),
    "insufficient_data": ("부족", "제한", "산출 불가", "판단하기 어렵"),
}
VALID_LABELS = set(LABEL_TERMS)


@dataclass(frozen=True)
class VerdictStabilityResult:
    verdict_stable: bool
    outcome: str
    reasons: list[str] = field(default_factory=list)


def infer_verdict_label(verdict: str) -> str | None:
    for label in ("strong", "insufficient_data", "weak", "moderate"):
        if any(term in verdict for term in LABEL_TERMS[label]):
            return label
    return None


def assess_verdict_stability(verdict: str, expected_label: str, llm_label: str | None = None) -> VerdictStabilityResult:
    """결정론적 점수 라벨과 최종 verdict 라벨이 충돌하지 않는지 확인한다."""
    reasons: list[str] = []
    assessed_label = llm_label if llm_label in VALID_LABELS else infer_verdict_label(verdict)
    if assessed_label is None:
        reasons.append("verdict_label_unavailable")
    elif assessed_label != expected_label:
        reasons.append("verdict_label_language_mismatch")

    stable = not reasons
    return VerdictStabilityResult(
        verdict_stable=stable,
        outcome="passed" if stable else "guarded",
        reasons=reasons,
    )
