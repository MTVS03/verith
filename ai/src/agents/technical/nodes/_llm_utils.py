"""LLM 전처리 노드(1·2) 공용 최소 플러밍.

`nodes/normalize_question.py`·`nodes/focus_analysis.py`가 공유한다. `interpret_report.py`(노드 10)에
의존하지 않는다 — node 간 의존 방향을 깔끔히 두기 위해 동일 성격의 최소 유틸을 별도로 둔다.
(interpret_report에도 유사 플러밍이 있으나 노드 10 전용 검증과 얽혀 있어 재사용하지 않는다.)

실제 LLM API를 호출하지 않는다. `LlmClient` Protocol로 주입받고, 테스트는 fake로 대체한다.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from ..observability.trajectory_eval import contains_forbidden_terms

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
_PAYLOAD_PLACEHOLDER = "{payload_json}"

# 전처리 노드(1·2) 전용 금지 표현. keyword_rules.FORBIDDEN_TERMS(노드 10 리포트 문장용)가
# 못 잡는 구어체 매수/매도 지시·미래 단정을 보강한다. keyword_rules.py는 수정하지 않는다.
# 이 세트는 완전 차단이 아니라 **결정론 백스톱**이다(모든 패러프레이즈를 잡는다고 과장하지 않음).
PREPROCESS_FORBIDDEN_TERMS: tuple[str, ...] = (
    "사세요", "사라", "매수하세요", "매수해", "매도하세요", "파세요", "팔아라",
    "지금 사", "지금 팔", "지금 들어가", "들어가세요",
    "손절하세요", "손절해", "익절하세요", "익절해",
    "오를 것입니다", "오를 겁니다", "오릅니다",
    "내릴 것입니다", "내릴 겁니다", "떨어질 것입니다", "떨어질 겁니다",
    "급등합니다", "급락합니다", "수익 납니다", "수익 보장",
    "확실히 오릅니다", "확실히 내립니다",
)


def unsafe_terms(text: str) -> list[str]:
    """전처리 노드용 안전 백스톱: 공유 금지어(keyword_rules) + 전처리 전용 금지어 히트 목록."""
    hits = list(contains_forbidden_terms(text))
    hits.extend(t for t in PREPROCESS_FORBIDDEN_TERMS if t in text)
    return hits


class LlmClient(Protocol):
    """LLM 호출 경계. 실제 구현(네트워크)은 이 단계 범위 밖 — 테스트는 fake로 주입한다."""

    def complete(self, prompt: str) -> str: ...


class LlmOutputParseError(ValueError):
    """LLM 응답을 계약(허용 키 object)으로 파싱하지 못함(조용히 삼키지 않고 명시적 실패)."""


def load_prompt(name: str) -> str:
    """prompts/<name>을 읽어 반환. 로컬 텍스트 자원이며 외부 호출이 아니다."""
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def render_prompt(template: str, payload: dict) -> str:
    """{payload_json} 자리에 payload JSON을 넣는다. 템플릿에 리터럴 중괄호가 많아 str.replace를 쓴다."""
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
    return template.replace(_PAYLOAD_PLACEHOLDER, payload_json)


def parse_json_object(raw: str, *, allowed_keys: Iterable[str]) -> dict:
    """LLM 원문 → dict. 코드펜스 제거 → json.loads → object 확인 → 허용 키 외 거부(extra 차단).

    허용 키만 통과시키므로, 계약 밖 필드(safety_notes·time_horizon·signal_score 등)는 여기서 실패한다.
    """
    allowed = frozenset(allowed_keys)
    text = _strip_code_fence(raw)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise LlmOutputParseError(f"LLM 응답을 JSON으로 파싱하지 못했습니다: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LlmOutputParseError(f"LLM 응답 최상위는 object여야 합니다: {type(parsed).__name__}")
    extra = set(parsed) - allowed
    if extra:
        raise LlmOutputParseError(f"허용되지 않은 키: {sorted(extra)} (허용: {sorted(allowed)})")
    return parsed


def _strip_code_fence(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        first_newline = s.find("\n")
        s = s[first_newline + 1:] if first_newline != -1 else s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()
