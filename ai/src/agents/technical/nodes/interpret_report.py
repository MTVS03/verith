"""노드 10 — 국면 해석·리포트 (LLM). 정본: `docs/prompts.md §4·§5`, `docs/contracts.md §2`.

책임(순수 함수만):
  - 코드 확정값으로 LLM 프롬프트 입력 payload를 구성한다.
  - prompts/*.md 텍스트 자원을 로드해 렌더한다.
  - LLM 응답(JSON)을 파싱한다.
  - observability/trajectory_eval(검증 ③)을 호출한다.
  - 검증 통과 문장을 technical_signals[].detail·interpretation.text로 병합한다.
  - 검증 실패분에 대한 template fallback 문장을 만든다(새 판단 없음).

경계(확정 사항):
  - **코드가 확정한 값(signal·value·metrics·weight·regime·consensus·confidence·risk)을 바꾸지 않는다.**
    이 노드는 `detail`/`interpretation.text` 문장만 만든다.
  - `TechnicalSignal`을 새로 조립하지 않는다. 따라서 `IndicatorSignalResult.value=None`(계산 불가)이
    있어도 payload에는 그대로(JSON null) 흘려보내고 임의로 0/±1로 바꾸지 않는다(확정 4).
  - "1차 생성→검증 실패→재생성 1회→재검증→최종 fallback" 루프 orchestration은 여기 없다.
    그건 `supervisor/technical_supervisor.py` 몫이다(확정 3). 이 파일은 그 루프가 조립할 부품만 제공한다.
  - 실제 LLM API를 호출하지 않는다. `LlmClient` Protocol로 주입받고, 테스트는 fake로 대체한다.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..observability import trajectory_eval
from ..observability.keyword_rules import (
    CONFIDENCE_LABELS,
    CONSENSUS_LABELS,
    INDICATOR_LABELS,
    REGIME_LABELS,
    RISK_LABELS,
    SIGNAL_LABELS,
)
from ..schemas.contracts import InterpretationResult, RegimeResult, RiskItem, SignalSummary
from ..schemas.enums import GenerationSource, IndicatorType, Signal
from ..synthesis.signal_score import IndicatorSignalResult

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
INTERPRET_PROMPT = "interpret_report.md"
REGENERATE_PROMPT = "regenerate_report.md"
_PAYLOAD_PLACEHOLDER = "{payload_json}"


class LlmClient(Protocol):
    """LLM 호출 경계. 실제 구현(네트워크)은 이 단계 범위 밖 — 테스트는 fake로 주입한다."""

    def complete(self, prompt: str) -> str: ...


class LlmOutputParseError(ValueError):
    """LLM 응답을 JSON으로 파싱하지 못함(조용히 삼키지 않고 명시적으로 실패)."""


@dataclass(frozen=True)
class DetailResult:
    """한 지표의 최종 설명 문장 + 출처. signal·value·weight는 여기에 없다(코드 확정값 불변)."""
    indicator: str
    detail: str
    detail_source: GenerationSource


# ─────────────────────────────────────────────────────────────────────────────
# 프롬프트 자원 로드·렌더 (LLM에 넘길 텍스트)
# ─────────────────────────────────────────────────────────────────────────────
def load_prompt(name: str) -> str:
    """prompts/<name>을 읽어 반환. 로컬 텍스트 자원이며 외부 호출이 아니다."""
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def build_payload(
    *,
    regime: RegimeResult,
    signal: SignalSummary,
    signals: Sequence[IndicatorSignalResult],
    risks: Sequence[RiskItem],
) -> dict:
    """코드 확정값 → 프롬프트 입력 payload(prompts.md §4). LLM은 이 값을 읽기만 한다.

    `weight`는 넣지 않는다(LLM 서술에 불필요). `value`는 None이면 그대로 null로 흘린다(확정 4).
    """
    return {
        "daily_regime": regime.daily_regime.value,
        "final_regime": regime.final_regime.value,
        "weekly_trend": regime.weekly_trend.value,
        "monthly_trend": regime.monthly_trend.value,
        "alignment_flag": regime.alignment_flag.value,
        "regime_context": regime.regime_context,
        "consensus": signal.consensus.value,
        "signal_score": signal.signal_score,
        "confidence": signal.confidence,
        "confidence_level": signal.confidence_level.value,
        "confidence_basis": signal.confidence_basis,
        "technical_signals": [
            {
                "indicator": s.indicator.value,
                "signal": s.signal.value,
                "value": s.value,
                "metrics": list(s.metrics),
            }
            for s in signals
        ],
        "risk_items": [{"flag": r.flag.value, "note": r.note} for r in risks],
    }


def render_prompt(template: str, payload: dict) -> str:
    """{payload_json} 자리에 payload JSON을 넣는다. 템플릿에 리터럴 중괄호가 많아 str.replace를 쓴다."""
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
    return template.replace(_PAYLOAD_PLACEHOLDER, payload_json)


def generate(client: LlmClient, *, template: str, payload: dict) -> dict:
    """단일 LLM 호출: 렌더 → 호출 → 파싱. 재생성 루프가 아니다(1회 호출)."""
    prompt = render_prompt(template, payload)
    return parse_llm_output(client.complete(prompt))


def parse_llm_output(raw: str) -> dict:
    """LLM 원문 → dict. 코드펜스(```json)를 벗기고 json.loads. 실패는 명시적 예외."""
    text = _strip_code_fence(raw)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise LlmOutputParseError(f"LLM 응답을 JSON으로 파싱하지 못했습니다: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LlmOutputParseError(f"LLM 응답 최상위는 object여야 합니다: {type(parsed).__name__}")
    return parsed


def _strip_code_fence(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        first_newline = s.find("\n")
        s = s[first_newline + 1:] if first_newline != -1 else s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


# ─────────────────────────────────────────────────────────────────────────────
# 검증 ③ 호출 (판정 로직은 trajectory_eval, 여기선 확정값에서 라벨만 뽑아 넘김)
# ─────────────────────────────────────────────────────────────────────────────
def verify(
    llm_output: dict,
    *,
    regime: RegimeResult,
    signal: SignalSummary,
    signals: Sequence[IndicatorSignalResult],
) -> trajectory_eval.EvalResult:
    return trajectory_eval.evaluate(
        llm_output,
        final_regime=regime.final_regime,
        consensus=signal.consensus,
        alignment_flag=regime.alignment_flag,
        signals=[(s.indicator, s.signal) for s in signals],
    )


# ─────────────────────────────────────────────────────────────────────────────
# 병합 (LLM 문장을 확정값 옆에 얹음 — 확정값은 건드리지 않음)
# ─────────────────────────────────────────────────────────────────────────────
def interpretation_from_llm(llm_output: dict, *, source: GenerationSource) -> InterpretationResult:
    """검증을 통과한 종합 해석 문장을 InterpretationResult로. source는 호출자(supervisor)가 결정."""
    text = str(llm_output.get("interpretation_text", "")).strip()
    return InterpretationResult(text=text, source=source)


def details_from_llm(
    llm_output: dict,
    *,
    signals: Sequence[IndicatorSignalResult],
    source: GenerationSource,
    failed_indicators: frozenset[str] = frozenset(),
) -> list[DetailResult]:
    """지표별 detail을 확정 signals 순서대로 조립. 실패한 indicator만 template fallback으로 대체(REGEN-04).

    코드 확정 signals의 순서·개수를 그대로 따르며, LLM에 없거나 실패한 지표는 폴백 문장을 쓴다.
    signal·value·weight는 읽기만 하고 바꾸지 않는다.
    """
    detail_map = {
        e["indicator"]: str(e.get("detail", "")).strip()
        for e in llm_output.get("details", []) or []
        if isinstance(e, dict) and "indicator" in e
    }
    results: list[DetailResult] = []
    for s in signals:
        code = s.indicator.value
        if code in failed_indicators or code not in detail_map or not detail_map[code]:
            results.append(fallback_detail(s.indicator, s.signal, s.metrics))
        else:
            results.append(DetailResult(code, detail_map[code], source))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# template fallback (새 판단 없이 확정값만 문장화 — 확정 5)
# ─────────────────────────────────────────────────────────────────────────────
def fallback_interpretation(
    *,
    regime: RegimeResult,
    signal: SignalSummary,
    risks: Sequence[RiskItem],
) -> InterpretationResult:
    """검증·재생성 실패 시 종합 해석 폴백. final_regime·consensus·confidence_level·risk flags만 사용."""
    regime_label = REGIME_LABELS[regime.final_regime]
    consensus_label = CONSENSUS_LABELS[signal.consensus]
    confidence_label = CONFIDENCE_LABELS[signal.confidence_level]

    parts = [
        f"현재 기술적 상태는 {regime_label}로 분류됩니다.",
        f"종합 신호는 {consensus_label}이며, 신뢰도는 {confidence_label} 수준입니다.",
    ]
    if risks:
        risk_str = "·".join(RISK_LABELS[r.flag] for r in risks)
        parts.append(f"주요 위험 요인으로 {risk_str}이(가) 함께 확인됩니다.")
    parts.append("이 내용은 투자 판단을 대신하지 않으며, 기술적 지표 기반 참고 정보입니다.")
    return InterpretationResult(text=" ".join(parts), source=GenerationSource.TEMPLATE_FALLBACK)


def unavailable_interpretation() -> InterpretationResult:
    """regime 판단 불가(데이터 부족) 시 고정 폴백 문장(contracts.md §4). 종합·신뢰도가 없을 때 사용."""
    return InterpretationResult(
        text="분석 가능한 데이터가 부족해 국면을 판정하지 않으며, 기술적 지표 기반 참고 정보입니다.",
        source=GenerationSource.TEMPLATE_FALLBACK,
    )


def fallback_detail(indicator: IndicatorType, signal: Signal, metrics: Sequence[str]) -> DetailResult:
    """지표별 detail 폴백. 확정 signal·metrics만 문장화하고 매수/매도·미래 단정을 쓰지 않는다."""
    indicator_label = INDICATOR_LABELS[indicator]
    signal_label = SIGNAL_LABELS[signal]
    text = f"{indicator_label} 지표는 {signal_label} 신호로 확인됩니다."
    if metrics:
        text += f" ({', '.join(metrics)})"
    return DetailResult(indicator.value, text, GenerationSource.TEMPLATE_FALLBACK)
