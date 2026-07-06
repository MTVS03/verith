"""노드 2 — 분석 포커스 정리 (LLM). 정본: docs/prompts.md §1·§3.

정규화된 질문에서 **설명 강조 관점(analysis_focus)**을 정리한다. 지표 선택이 아니다(5개 지표는
코드가 항상 계산). 출력은 `analysis_focus[]` + `focus_summary`.

안전 가드(prompts.md): 이 노드는 **원본 query를 받지 않는다** — `normalized_question`만 입력받는다.
함수 시그니처에 query가 없는 것으로 이 가드를 구조적으로 보장한다.

책임(순수 함수): payload 구성 → 프롬프트 로드·렌더 → LLM 1회 호출 → 허용 키/허용값/금지어 검증 →
실패 시 재생성 없이 template fallback(정본 5종 focus). 계산값·regime·signal은 만들지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas.enums import GenerationSource
from ._llm_utils import (
    LlmClient,
    LlmOutputParseError,
    load_prompt,
    parse_json_object,
    render_prompt,
    unsafe_terms,
)

FOCUS_PROMPT = "focus_analysis.md"
_ALLOWED_KEYS = frozenset({"analysis_focus", "focus_summary"})

# 설명 강조 관점 허용 어휘 (prompts.md §3). IndicatorType(지표명)과 다른 어휘다.
ALLOWED_ANALYSIS_FOCUS = frozenset({"trend", "momentum", "volume", "support_resistance", "risk"})

_FALLBACK_FOCUS = ["trend", "momentum", "volume", "support_resistance", "risk"]
_FALLBACK_SUMMARY = "추세·모멘텀·거래량·지지저항·리스크 관찰점을 함께 확인합니다."


@dataclass(frozen=True)
class FocusResult:
    """노드 2 결과. source는 llm 또는 template_fallback."""
    analysis_focus: list[str]
    focus_summary: str
    source: GenerationSource


def build_payload(*, ticker: str, normalized_question: str) -> dict:
    """프롬프트 입력(prompts.md §3). 원본 query는 넣지 않는다(안전 가드)."""
    return {"ticker": ticker, "normalized_question": normalized_question}


def run_focus_analysis(
    client: LlmClient,
    *,
    ticker: str,
    normalized_question: str,
) -> FocusResult:
    """정규화 질문에서 설명 강조 관점을 정리한다. 실패 시 정본 5종 focus로 fallback."""
    if not normalized_question:
        raise ValueError("normalized_question is required for focus_analysis")

    prompt = render_prompt(load_prompt(FOCUS_PROMPT),
                           build_payload(ticker=ticker, normalized_question=normalized_question))
    # LLM 호출 자체의 예외(TimeoutError 등)는 삼키지 않고 전파한다(supervisor 책임, M3).
    raw = client.complete(prompt)
    try:
        parsed = parse_json_object(raw, allowed_keys=_ALLOWED_KEYS)
    except LlmOutputParseError:
        return _fallback()

    focus = parsed.get("analysis_focus")
    summary = parsed.get("focus_summary")
    if not _is_valid_focus(focus):                                    # H2: 예외 없이 검증 실패
        return _fallback()
    if not isinstance(summary, str) or not summary.strip():           # H1: str 강제 변환 없음
        return _fallback()
    if unsafe_terms(summary.strip()):                                 # H3: 공유+전처리 금지어 백스톱
        return _fallback()
    return FocusResult(list(focus), summary.strip(), GenerationSource.LLM)


def _is_valid_focus(focus: object) -> bool:
    """검사 순서: list → 비어있지 않음 → 각 원소 str → 허용값 → 중복 없음(H2).

    잘못된 값은 예외를 던지지 않고 False(검증 실패 → fallback). 원소 타입 확인 전에 set()을
    호출하지 않는다(중첩 리스트 unhashable TypeError 방지).
    """
    if not isinstance(focus, list) or not focus:
        return False
    if not all(isinstance(f, str) for f in focus):
        return False
    if any(f not in ALLOWED_ANALYSIS_FOCUS for f in focus):
        return False
    return len(focus) == len(set(focus))


def _fallback() -> FocusResult:
    """정본 허용값 5종 전체 + 관찰 톤 요약(새 판단·계산 없음)."""
    return FocusResult(list(_FALLBACK_FOCUS), _FALLBACK_SUMMARY, GenerationSource.TEMPLATE_FALLBACK)
