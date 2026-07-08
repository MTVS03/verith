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
from ..schemas.enums import (
    AlignmentFlag,
    Consensus,
    DirectionalBias,
    GenerationSource,
    IndicatorType,
    Signal,
    Trend,
)
from ..synthesis.signal_score import IndicatorSignalResult

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
INTERPRET_PROMPT = "interpret_report.md"
REGENERATE_PROMPT = "regenerate_report.md"
_PAYLOAD_PLACEHOLDER = "{payload_json}"

# LLM 출력 스키마(contracts §2·prompts §4). 이 밖의 key는 파싱 단계에서 거부한다(extra 유입 차단).
# 구조화 섹션(additive): 문자열 필드 + 배열 필드(key_drivers/warning_points). directional_bias 는 LLM 이
# 아니라 코드가 consensus 에서 파생하므로 출력 스키마에 넣지 않는다(넣어도 무시).
_STR_SECTION_KEYS = frozenset({
    "one_line_summary", "trend_interpretation", "signal_interpretation", "risk_interpretation",
    "timeframe_alignment", "what_to_watch_next", "invalidation_or_caution",
})
_LIST_SECTION_KEYS = frozenset({"key_drivers", "warning_points"})
_ALLOWED_TOP_KEYS = frozenset({"interpretation_text", "details"}) | _STR_SECTION_KEYS | _LIST_SECTION_KEYS
_ALLOWED_DETAIL_KEYS = frozenset({"indicator", "detail"})

# 결정론 파생용 라벨(fallback·기본 섹션 문구). regime/consensus/confidence/risk 라벨은 keyword_rules 재사용.
_TREND_LABELS: dict[Trend, str] = {
    Trend.UP: "상승", Trend.DOWN: "하락", Trend.SIDEWAYS: "횡보", Trend.UNAVAILABLE: "판정 불가",
}
_ALIGNMENT_LABELS: dict[AlignmentFlag, str] = {
    AlignmentFlag.ALIGNED: "정합", AlignmentFlag.COUNTER_TREND: "역행", AlignmentFlag.NEUTRAL: "중립",
}
_BIAS_FROM_CONSENSUS: dict[Consensus, DirectionalBias] = {
    Consensus.STRONG_POSITIVE: DirectionalBias.BULLISH,
    Consensus.WEAK_POSITIVE: DirectionalBias.BULLISH,
    Consensus.NEUTRAL: DirectionalBias.NEUTRAL,
    Consensus.WEAK_NEGATIVE: DirectionalBias.BEARISH,
    Consensus.STRONG_NEGATIVE: DirectionalBias.BEARISH,
}


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
    analysis_focus: Sequence[str] | None = None,
    focus_summary: str | None = None,
    data_status: str | None = None,
) -> dict:
    """코드 확정값 → 프롬프트 입력 payload(prompts.md §4). LLM은 이 값을 읽기만 한다.

    `weight`는 넣지 않는다(LLM 서술에 불필요). `value`는 None이면 그대로 null로 흘린다(확정 4).
    `analysis_focus`·`focus_summary`(노드 2 산출)는 **설명 강조 힌트**로만 넣는다 — LLM은 이 힌트로
    어떤 관점을 더 풀지 정할 뿐, 확정 라벨·수치는 바꾸지 않는다(prompts.md §3·§4).
    `data_status`(있으면)는 limited/unavailable 일 때 LLM 이 단정하지 않도록 하는 **hedge 힌트**다.
    """
    payload: dict = {
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
    if analysis_focus is not None:
        payload["analysis_focus"] = list(analysis_focus)
    if focus_summary:
        payload["focus_summary"] = focus_summary
    if data_status:
        payload["data_status"] = data_status
    return payload


def render_prompt(template: str, payload: dict) -> str:
    """{payload_json} 자리에 payload JSON을 넣는다. 템플릿에 리터럴 중괄호가 많아 str.replace를 쓴다."""
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
    return template.replace(_PAYLOAD_PLACEHOLDER, payload_json)


def generate(client: LlmClient, *, template: str, payload: dict) -> dict:
    """단일 LLM 호출: 렌더 → 호출 → 파싱. 재생성 루프가 아니다(1회 호출)."""
    prompt = render_prompt(template, payload)
    return parse_llm_output(client.complete(prompt))


def parse_llm_output(raw: str) -> dict:
    """LLM 원문 → dict. 코드펜스(```json)를 벗기고 json.loads. 허용 key 외는 거부(extra 차단)."""
    text = _strip_code_fence(raw)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise LlmOutputParseError(f"LLM 응답을 JSON으로 파싱하지 못했습니다: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LlmOutputParseError(f"LLM 응답 최상위는 object여야 합니다: {type(parsed).__name__}")

    extra_top = set(parsed) - _ALLOWED_TOP_KEYS
    if extra_top:
        raise LlmOutputParseError(f"허용되지 않은 최상위 key: {sorted(extra_top)}")

    # 구조화 섹션 타입 검증: 문자열 섹션은 str, 배열 섹션은 str 리스트여야 한다.
    for key in _STR_SECTION_KEYS:
        if key in parsed and not isinstance(parsed[key], str):
            raise LlmOutputParseError(f"{key}는 문자열이어야 합니다")
    for key in _LIST_SECTION_KEYS:
        if key in parsed:
            val = parsed[key]
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                raise LlmOutputParseError(f"{key}는 문자열 배열이어야 합니다")

    details = parsed.get("details")
    if details is not None:
        if not isinstance(details, list):
            raise LlmOutputParseError("details는 배열이어야 합니다")
        for entry in details:
            if not isinstance(entry, dict):
                raise LlmOutputParseError("details 항목은 object여야 합니다")
            extra_detail = set(entry) - _ALLOWED_DETAIL_KEYS
            if extra_detail:
                raise LlmOutputParseError(f"details 항목에 허용되지 않은 key: {sorted(extra_detail)}")
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
    risks: Sequence[RiskItem] = (),
) -> trajectory_eval.EvalResult:
    """검증 ③ 호출. 라벨·신호에 더해 confidence_level·risk flag까지 확정값을 넘긴다."""
    return trajectory_eval.evaluate(
        llm_output,
        final_regime=regime.final_regime,
        consensus=signal.consensus,
        alignment_flag=regime.alignment_flag,
        signals=[(s.indicator, s.signal) for s in signals],
        confidence_level=signal.confidence_level,
        risk_flags=[r.flag for r in risks],
    )


# ─────────────────────────────────────────────────────────────────────────────
# 결정론 섹션 파생 (확정값만으로 구조화 섹션 생성 — fallback·LLM 누락 필드 기본값 공용)
# ─────────────────────────────────────────────────────────────────────────────
def bias_from_consensus(consensus: Consensus) -> DirectionalBias:
    """directional_bias 를 consensus 에서 결정론 파생(LLM 재판정 아님)."""
    return _BIAS_FROM_CONSENSUS.get(consensus, DirectionalBias.NEUTRAL)


def _one_line(regime: RegimeResult, signal: SignalSummary) -> str:
    return (
        f"{REGIME_LABELS[regime.final_regime]} · 종합신호 {CONSENSUS_LABELS[signal.consensus]}"
        f"({CONFIDENCE_LABELS[signal.confidence_level]} 신뢰도)"
    )


def _trend_text(regime: RegimeResult) -> str:
    return (
        f"현재 국면은 {REGIME_LABELS[regime.final_regime]}로 분류됩니다"
        f"(일봉 {REGIME_LABELS[regime.daily_regime]})."
    )


def _signal_text(signal: SignalSummary) -> str:
    return (
        f"종합 신호는 {CONSENSUS_LABELS[signal.consensus]}이며 신뢰도는 "
        f"{CONFIDENCE_LABELS[signal.confidence_level]} 수준입니다."
    )


def _risk_text(risks: Sequence[RiskItem]) -> str:
    if not risks:
        return "특이 위험 요인은 확인되지 않았습니다."
    return "위험 요인으로 " + "·".join(RISK_LABELS[r.flag] for r in risks) + "이(가) 확인됩니다."


def _timeframe_text(regime: RegimeResult) -> str:
    wk, mo = _TREND_LABELS[regime.weekly_trend], _TREND_LABELS[regime.monthly_trend]
    if regime.alignment_flag == AlignmentFlag.ALIGNED:
        return f"상위 추세(주봉 {wk}·월봉 {mo})와 단기 흐름이 대체로 정합합니다."
    if regime.alignment_flag == AlignmentFlag.COUNTER_TREND:
        return f"단기 흐름이 상위 추세(주봉 {wk}·월봉 {mo})와 엇갈립니다(역행)."
    return f"주봉 {wk}·월봉 {mo}로 타임프레임 간 방향 신호가 뚜렷하지 않습니다."


def _key_drivers(
    regime: RegimeResult, signal: SignalSummary, signals: Sequence[IndicatorSignalResult] = ()
) -> list[str]:
    drivers = [
        f"{INDICATOR_LABELS[s.indicator]} {SIGNAL_LABELS[s.signal]}"
        for s in signals if s.signal != Signal.NEUTRAL
    ]
    if not drivers:
        drivers.append(f"{REGIME_LABELS[regime.final_regime]} 국면·종합신호 {CONSENSUS_LABELS[signal.consensus]}")
    return drivers[:4]


def _what_to_watch(regime: RegimeResult, risks: Sequence[RiskItem]) -> str:
    if regime.alignment_flag == AlignmentFlag.COUNTER_TREND:
        return "상위 추세와 단기 흐름의 정합 회복 여부"
    if risks:
        return f"확인된 위험({RISK_LABELS[risks[0].flag]})의 해소 여부와 거래량 동반"
    return "현재 국면 유지 여부와 거래량 동반"


def _invalidation() -> str:
    return (
        "상위 추세가 반대로 전환되거나 분석 데이터가 부족해지면 현재 해석은 유효하지 않을 수 있습니다"
        "(위험 요인과는 별개의 무효화 조건)."
    )


# ─────────────────────────────────────────────────────────────────────────────
# 병합 (LLM 문장을 확정값 옆에 얹음 — 확정값은 건드리지 않음)
# ─────────────────────────────────────────────────────────────────────────────
def interpretation_from_llm(
    llm_output: dict,
    *,
    source: GenerationSource,
    regime: RegimeResult,
    signal: SignalSummary,
    signals: Sequence[IndicatorSignalResult] = (),
    risks: Sequence[RiskItem] = (),
) -> InterpretationResult:
    """검증 통과 LLM 해석을 구조화 InterpretationResult로. 섹션은 LLM 값 우선, 누락 시 결정론 기본값으로 채운다.

    `text`(하위호환)·문자열 섹션은 LLM 출력에서 가져오되 비면 확정값 파생으로 대체한다. `directional_bias`는
    **항상 코드가 consensus에서 파생**한다(LLM이 방향을 뒤집지 못하게). source는 호출자(supervisor)가 결정."""
    text = str(llm_output.get("interpretation_text", "")).strip()

    def _s(key: str, default: str) -> str:
        v = str(llm_output.get(key, "")).strip()
        return v or default

    def _l(key: str, default: list[str]) -> list[str]:
        v = llm_output.get(key)
        items = [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []
        return items or default

    return InterpretationResult(
        text=text or _one_line(regime, signal),
        source=source,
        one_line_summary=_s("one_line_summary", _one_line(regime, signal)),
        directional_bias=bias_from_consensus(signal.consensus),
        trend_interpretation=_s("trend_interpretation", _trend_text(regime)),
        signal_interpretation=_s("signal_interpretation", _signal_text(signal)),
        risk_interpretation=_s("risk_interpretation", _risk_text(risks)),
        timeframe_alignment=_s("timeframe_alignment", _timeframe_text(regime)),
        key_drivers=_l("key_drivers", _key_drivers(regime, signal, signals)),
        warning_points=_l("warning_points", [RISK_LABELS[r.flag] for r in risks]),
        what_to_watch_next=_s("what_to_watch_next", _what_to_watch(regime, risks)),
        invalidation_or_caution=_s("invalidation_or_caution", _invalidation()),
    )


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
    signals: Sequence[IndicatorSignalResult] = (),
) -> InterpretationResult:
    """검증·재생성 실패 시 종합 해석 폴백 — **구조화 섹션을 deterministic 하게 전부 채운다**(빈약 착지 방지).

    확정값(final_regime·consensus·confidence_level·risk flags·timeframe·signals)만 문장화한다. 새 판단 없음.
    LLM 이 죽어도 프론트가 같은 섹션 구조로 렌더할 수 있게 한다(확정 5)."""
    parts = [
        f"현재 기술적 상태는 {REGIME_LABELS[regime.final_regime]}로 분류됩니다.",
        _signal_text(signal),
        _timeframe_text(regime),
    ]
    if risks:
        parts.append(_risk_text(risks))
    parts.append("이 내용은 투자 판단을 대신하지 않으며, 기술적 지표 기반 참고 정보입니다.")
    return InterpretationResult(
        text=" ".join(parts),
        source=GenerationSource.TEMPLATE_FALLBACK,
        one_line_summary=_one_line(regime, signal),
        directional_bias=bias_from_consensus(signal.consensus),
        trend_interpretation=_trend_text(regime),
        signal_interpretation=_signal_text(signal),
        risk_interpretation=_risk_text(risks),
        timeframe_alignment=_timeframe_text(regime),
        key_drivers=_key_drivers(regime, signal, signals),
        warning_points=[RISK_LABELS[r.flag] for r in risks],
        what_to_watch_next=_what_to_watch(regime, risks),
        invalidation_or_caution=_invalidation(),
    )


def unavailable_interpretation() -> InterpretationResult:
    """regime 판단 불가(데이터 부족) 시 고정 폴백(contracts.md §4). 종합·신뢰도가 없을 때 — 과장 없이 착지."""
    limited = "분석 가능한 데이터가 부족해 국면을 판정하지 않습니다."
    return InterpretationResult(
        text=f"{limited} 기술적 지표 기반 참고 정보입니다.",
        source=GenerationSource.TEMPLATE_FALLBACK,
        one_line_summary="데이터 부족 — 국면 판정 보류",
        directional_bias=DirectionalBias.NEUTRAL,
        trend_interpretation=limited,
        signal_interpretation="신호를 종합할 만큼 데이터가 확보되지 않았습니다.",
        risk_interpretation="데이터 부족으로 위험 요인도 신뢰 있게 판정하기 어렵습니다.",
        timeframe_alignment="타임프레임 정합 여부를 판정할 데이터가 부족합니다.",
        key_drivers=[],
        warning_points=["데이터 부족"],
        what_to_watch_next="데이터 확보 후 재분석 필요",
        invalidation_or_caution="데이터가 제한적이므로 어떤 방향도 단정하지 않습니다.",
    )


def fallback_detail(indicator: IndicatorType, signal: Signal, metrics: Sequence[str]) -> DetailResult:
    """지표별 detail 폴백. 확정 signal·metrics만 문장화하고 매수/매도·미래 단정을 쓰지 않는다."""
    indicator_label = INDICATOR_LABELS[indicator]
    signal_label = SIGNAL_LABELS[signal]
    text = f"{indicator_label} 지표는 {signal_label} 신호로 확인됩니다."
    if metrics:
        text += f" ({', '.join(metrics)})"
    return DetailResult(indicator.value, text, GenerationSource.TEMPLATE_FALLBACK)
