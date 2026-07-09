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
    ALIGNMENT_RULES,
    CONFIDENCE_LABELS,
    CONFIDENCE_RULES,
    CONSENSUS_LABELS,
    CONSENSUS_RULES,
    INDICATOR_LABELS,
    REGIME_LABELS,
    REGIME_RULES,
    RISK_LABELS,
    RISK_MENTION_TERMS,
    SIGNAL_LABELS,
    SIGNAL_RULES,
)
from ..schemas.contracts import InterpretationResult, RegimeResult, RiskItem, SignalSummary
from ..schemas.enums import (
    AlignmentFlag,
    Consensus,
    DirectionalBias,
    GenerationSource,
    IndicatorType,
    RiskFlag,
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
_ALLOWED_DETAIL_KEYS = frozenset(
    {"indicator", "detail", "detail_reason", "detail_caution", "detail_watchpoint"}
)

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
    """한 지표의 최종 설명 문장 + 출처. signal·value·weight는 여기에 없다(코드 확정값 불변).

    detail_reason/caution/watchpoint 는 additive 설명 필드 — 프론트 카드가 "왜/주의/관찰"을 구조적으로
    보여주기 위한 부가 서술이며, 재판정이 아니다(확정값 불변). LLM 성공 시 LLM 값, 누락/폴백 시 결정론 값.
    """
    indicator: str
    detail: str
    detail_source: GenerationSource
    detail_reason: str | None = None
    detail_caution: str | None = None
    detail_watchpoint: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# 프롬프트 자원 로드·렌더 (LLM에 넘길 텍스트)
# ─────────────────────────────────────────────────────────────────────────────
def load_prompt(name: str) -> str:
    """prompts/<name>을 읽어 반환. 로컬 텍스트 자원이며 외부 호출이 아니다."""
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _verify_expressions(
    regime: RegimeResult,
    signal: SignalSummary,
    signals: Sequence[IndicatorSignalResult],
    risks: Sequence[RiskItem],
) -> dict:
    """검증(③)이 요구하는 **한글 대표 표현**을 확정 라벨에서 뽑아 프롬프트에 명시(단일 출처 = keyword_rules).

    LLM 이 영문 enum(strong_negative 등)이나 동의어를 써서 verify 를 통과 못 하던 문제를 막는다 — 여기서 준
    표현을 그대로 포함하고, avoid 표현은 쓰지 않게 한다. require_representative=False(중립 등)는 must_include
    에서 제외하고 avoid 만 싣는다."""
    def _req(rule) -> list[str]:
        return list(rule.required_any) if (rule and rule.require_representative and rule.required_any) else []

    must_include: dict = {}
    reg = _req(REGIME_RULES.get(regime.final_regime))
    if reg:
        must_include["regime"] = reg
    con = _req(CONSENSUS_RULES.get(signal.consensus))
    if con:
        must_include["consensus"] = con
    # alignment 은 require_representative=False(중립) 여도, 안전한 서술 표현을 지정한다 — 그래야 모델이
    # "정합"/"역행" 단독어(중립에선 conflict)를 쓰지 않고 지정 표현(예: "방향성 판정 없음")으로 서술한다.
    align_rule = ALIGNMENT_RULES.get(regime.alignment_flag)
    if align_rule and align_rule.required_any:
        must_include["alignment"] = list(align_rule.required_any)
    detail_by_indicator = {
        s.indicator.value: list(SIGNAL_RULES[s.signal].required_any)
        for s in signals if s.signal in SIGNAL_RULES and SIGNAL_RULES[s.signal].required_any
    }

    avoid: set[str] = set()
    for rule in (
        REGIME_RULES.get(regime.final_regime), CONSENSUS_RULES.get(signal.consensus),
        ALIGNMENT_RULES.get(regime.alignment_flag), CONFIDENCE_RULES.get(signal.confidence_level),
    ):
        if rule:
            avoid.update(rule.conflict_any)

    risk_mention_any = sorted({
        t for r in risks for t in RISK_MENTION_TERMS.get(r.flag, ())
    })

    return {
        "interpretation_must_include_any": must_include,   # 각 키: 이 중 1개 이상을 그대로 포함
        "detail_must_include_any_by_indicator": detail_by_indicator,  # 지표별 detail 에 signal 표현 포함
        "must_mention_risk_any": risk_mention_any,         # risk 있으면 이 중 1개 이상 언급
        "must_avoid": sorted(avoid),                       # 반대·모순 표현 금지
        "do_not_use_english_enum": True,                   # strong_negative/downtrend 등 영문 enum 서술 금지
    }


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
        # risk_interpretation 을 '나열'이 아니라 '맥락 있는 해설'로 쓰도록 하는 설명 힌트(additive·새 계산 아님).
        # label=사람 라벨, meaning=해석상 의미(왜 주의인지), watch=관찰 포인트. LLM 은 이 힌트로 조합을 설명한다.
        "risk_hints": [
            {
                "flag": r.flag.value,
                "label": RISK_LABELS[r.flag],
                "meaning": _RISK_MEANING.get(r.flag, RISK_LABELS[r.flag]),
                "watch": _RISK_WATCH.get(r.flag),
            }
            for r in risks
        ],
        # 검증 통과에 필요한 한글 대표 표현(단일 출처 keyword_rules) — 영문 enum·모순어로 인한 fallback 방지.
        "verify_expressions": _verify_expressions(regime, signal, signals, risks),
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


# flag별 "해석상 의미"(왜 주의 신호인지·오해 금지 포인트) — 단순 라벨 나열 대신 의미를 설명하기 위한
# 결정론 문구. 새 판정이 아니라 확정 flag 를 사람 언어로 풀어 쓰는 힌트다(prompt·fallback 공용).
_RISK_MEANING: dict[RiskFlag, str] = {
    RiskFlag.VOLUME_NOT_CONFIRMED: "거래량 확인이 약해 가격 움직임을 뒷받침할 근거가 부족한 점",
    RiskFlag.NEAR_SUPPORT: "지지 구간에 근접해 반등 가능성과 이탈 위험이 함께 열려 있는 점",
    RiskFlag.NEAR_RESISTANCE: "저항 구간에 근접해 추가 상승보다 저항 반응 확인이 필요한 점",
    RiskFlag.MIXED_SIGNALS: "지표 간 방향성이 엇갈려 단일 신호에 기대기 어려운 점",
    RiskFlag.OVERHEATED_MOMENTUM: "상승 해석과 별개로 단기 과열 부담이 남아 있는 점",
    RiskFlag.COUNTER_HIGHER_TREND: "단기 흐름이 상위 추세와 역행하는 점",
    RiskFlag.LOW_LIQUIDITY: "유동성이 낮아 신호 신뢰도가 떨어질 수 있는 점",
}
# flag별 관찰 포인트(무엇을 더 확인해야 하는지 — 행동 지시 아님).
_RISK_WATCH: dict[RiskFlag, str] = {
    RiskFlag.VOLUME_NOT_CONFIRMED: "거래량 동반 여부",
    RiskFlag.NEAR_SUPPORT: "지지선에서의 가격 반응",
    RiskFlag.NEAR_RESISTANCE: "저항 구간에서의 반응",
    RiskFlag.MIXED_SIGNALS: "지표 간 방향 정렬",
    RiskFlag.OVERHEATED_MOMENTUM: "과열 완화 여부",
    RiskFlag.COUNTER_HIGHER_TREND: "상위 추세와의 정합 회복",
    RiskFlag.LOW_LIQUIDITY: "거래 활성도",
}


def _risk_text(risks: Sequence[RiskItem]) -> str:
    """risk_interpretation 결정론 폴백 — flag 나열이 아니라 **의미 + 해석 제약 + 관찰 포인트** 2~3문장.

    확정 flag 만 근거로 하며(새 판정 없음), 매수/매도·목표가·확률 예측·과장 표현은 쓰지 않는다.
    LLM 이 죽어도 프론트 상단 '위험 해설'로 쓸 만한 문장이 되도록 한다."""
    if not risks:
        return "특이 위험 요인은 확인되지 않았습니다."
    meanings = [_RISK_MEANING.get(r.flag, RISK_LABELS[r.flag]) for r in risks]
    watches: list[str] = []
    for r in risks:
        w = _RISK_WATCH.get(r.flag)
        if w and w not in watches:
            watches.append(w)
    s1 = "현재는 " + ", ".join(meanings) + "이 함께 확인됩니다."
    s2 = ("이런 요인이 겹치면 개별 신호를 방향 전환의 근거로 단정하기보다, "
          "종합 해석의 확신이 제한되는 구간으로 보는 것이 안전합니다.")
    if watches:
        s3 = "이 구간에서는 " + "·".join(f"**{w}**" for w in watches) + " 등을 추가로 확인하는 것이 중요합니다."
        return f"{s1} {s2} {s3}"
    return f"{s1} {s2}"


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
    # 핵심 조건은 **bold**(프론트가 <strong> 로 렌더, verify 는 별표 제거 후 검사).
    if regime.alignment_flag == AlignmentFlag.COUNTER_TREND:
        return "상위 추세와 단기 흐름의 **정합 회복 여부**"
    if risks:
        return f"확인된 위험({RISK_LABELS[risks[0].flag]})의 **해소 여부**와 **거래량 동반**"
    return "**국면 유지 여부**와 **거래량 동반**"


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
    entry_map = {
        e["indicator"]: e
        for e in llm_output.get("details", []) or []
        if isinstance(e, dict) and "indicator" in e
    }
    results: list[DetailResult] = []
    for s in signals:
        code = s.indicator.value
        entry = entry_map.get(code)
        detail_txt = _entry_field(entry, "detail")
        # 결정론 폴백(4필드) — 실패/누락 시 대체, LLM 성공 시엔 누락 additive 필드만 백필.
        fb = fallback_detail(s.indicator, s.signal, s.metrics)
        if code in failed_indicators or not detail_txt:
            results.append(fb)
        else:
            results.append(DetailResult(
                code, detail_txt, source,
                detail_reason=_entry_field(entry, "detail_reason") or fb.detail_reason,
                detail_caution=_entry_field(entry, "detail_caution") or fb.detail_caution,
                detail_watchpoint=_entry_field(entry, "detail_watchpoint") or fb.detail_watchpoint,
            ))
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
    # 신호 흐름 요약 — 5구조(전체 판단/약세 근거/완충 신호/주의할 점/다음 관찰 기준)로 줄바꿈 분리.
    # 프론트가 whitespace-pre-wrap 로 렌더하므로 라벨+개행이 그대로 보인다(빈약한 한 줄 착지 방지).
    bearish = [INDICATOR_LABELS[s.indicator] for s in signals if s.signal == Signal.NEGATIVE]
    supportive = [INDICATOR_LABELS[s.indicator] for s in signals if s.signal == Signal.POSITIVE]
    lines = [
        f"전체 판단: 현재 기술적 상태는 {REGIME_LABELS[regime.final_regime]}로 분류됩니다. "
        f"{_signal_text(signal)} {_timeframe_text(regime)}",
    ]
    if bearish:
        lines.append(
            "약세 근거: " + "·".join(bearish)
            + "이(가) 약세 쪽으로 읽혀 추세 복원 신호가 아직 충분하지 않은 상태입니다."
        )
    if supportive:
        lines.append(
            "완충 신호: " + "·".join(supportive)
            + "이(가) 하락 압력을 다소 완화하지만, 방향 전환 확정으로 보기엔 이른 수준입니다."
        )
    lines.append(
        "주의할 점: " + (_risk_text(risks) if risks
                       else "두드러진 위험 요인은 없으나 단일 지표만으로 방향을 단정하는 것은 피하는 것이 안전합니다.")
    )
    lines.append("다음 관찰 기준: " + _what_to_watch(regime, risks))
    lines.append("이 내용은 투자 판단을 대신하지 않으며, 기술적 지표 기반 참고 정보입니다.")
    return InterpretationResult(
        text="\n".join(lines),
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


# 지표별 결정론 caution/watchpoint 템플릿(폴백·LLM 누락 백필). 새 판단 없이 지표 성격만 설명한다.
_FALLBACK_DETAIL_HINTS: dict[str, tuple[str, str]] = {
    "moving_average": (
        "이동평균은 후행 지표라 방향 전환을 늦게 반영합니다. 단독으로 진입·청산 근거로 쓰지 마세요.",
        "**5·20·60일선 배열 유지 여부**와 **골든/데드크로스** 발생을 확인하세요.",
    ),
    "rsi": (
        "RSI만으로 방향을 단정하기 어렵고, 과매수·과매도가 곧 반전을 뜻하지는 않습니다.",
        "**RSI 기준선 돌파 여부**와 **50선 안착 여부**를 확인하세요.",
    ),
    "volume": (
        "거래량은 방향이 아니라 강도 정보입니다. 가격 신호와 함께 봐야 의미가 있습니다.",
        "**가격 방향과 동반된 거래량 확장**이 이어지는지 확인하세요.",
    ),
    "support_resistance": (
        "지지·저항은 절대선이 아니라 구간이며, 돌파·이탈 시 역할이 뒤바뀔 수 있습니다.",
        "**지지·저항 반응**과 **거래량 동반 돌파·이탈** 여부를 확인하세요.",
    ),
    "pattern": (
        "패턴은 관찰용 후보이며 완성된 신호가 아닙니다. 방향 판정(신호 점수)에는 반영되지 않습니다.",
        "**패턴 완성·확정 여부**와 **거래량 확인**을 이어서 관찰하세요.",
    ),
}


# 지표별 "핵심 해석" 앞문장(결정론) — fallback reason 을 한 단계 더 설명적으로. 새 판정 없이 지표 성격만.
_FALLBACK_DETAIL_REASON: dict[str, str] = {
    "moving_average": "이동평균의 배열(정/역배열)과 현재가 위치가 추세 방향을 나타냅니다.",
    "rsi": "RSI 값이 과매수·과매도 기준선 대비 어디에 있는지가 모멘텀 상태를 나타냅니다.",
    "volume": "거래량이 가격 움직임을 확인해 주는 수준인지가 신호 강도를 좌우합니다.",
    "support_resistance": "현재가가 지지·저항 구간 중 어디에 가까운지가 가격 반응 여부를 좌우합니다.",
    "pattern": "최근 캔들 구조가 단기 방향의 힘을 나타내며, 패턴 후보는 관찰용입니다.",
}


def _entry_field(entry: dict | None, key: str) -> str:
    """LLM details 항목에서 문자열 필드를 안전하게 꺼낸다(없으면 빈 문자열)."""
    if not entry:
        return ""
    return str(entry.get(key, "") or "").strip()


def fallback_detail(indicator: IndicatorType, signal: Signal, metrics: Sequence[str]) -> DetailResult:
    """지표별 detail 폴백 — 확정 signal·metrics만 문장화하고 매수/매도·미래 단정을 쓰지 않는다.

    additive 설명 필드(reason/caution/watchpoint)도 **결정론적으로** 채운다 → LLM 이 죽어도 프론트
    카드가 비지 않는다(새 판단 없이 지표 성격만 설명)."""
    indicator_label = INDICATOR_LABELS[indicator]
    signal_label = SIGNAL_LABELS[signal]
    text = f"{indicator_label} 지표는 {signal_label} 신호로 확인됩니다."
    if metrics:
        text += f" ({', '.join(metrics)})"
    meaning = _FALLBACK_DETAIL_REASON.get(indicator.value)
    reason = (
        (meaning + " " if meaning else "")
        + f"코드가 확정한 {indicator_label} 수치를 기준으로 {signal_label} 신호로 확인됩니다."
    )
    if metrics:
        reason += f" ({', '.join(metrics)})"
    caution, watchpoint = _FALLBACK_DETAIL_HINTS.get(
        indicator.value,
        (
            f"{indicator_label} 단독으로 방향을 단정하기 어렵고 다른 지표와 함께 봐야 합니다.",
            f"{indicator_label} 수치 변화와 다른 지표의 정합 여부를 이어서 확인하세요.",
        ),
    )
    return DetailResult(
        indicator.value, text, GenerationSource.TEMPLATE_FALLBACK,
        detail_reason=reason, detail_caution=caution, detail_watchpoint=watchpoint,
    )
