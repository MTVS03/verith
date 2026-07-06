"""노드 1 — 질문 안전 정규화 (LLM). 정본: docs/prompts.md §1·§2.

사용자 원문(query)을 안전한 기술적 분석 질의로 정규화하는 가드. 출력은 `normalized_question`
문장 하나(prompts.md: 죽은 필드 금지). 원본 query는 이 노드까지만 존재한다 — 노드 2에는 정규화
문장만 흐른다.

책임(순수 함수, 얇은 어댑터):
  - 입력으로 프롬프트 payload 구성 → prompts/normalize_question.md 로드·렌더 → LLM 1회 호출.
  - 출력 JSON을 허용 키(`normalized_question`)로 파싱, 금지어 검증.
  - 실패(파싱·추가 키·빈 문장·금지어) 시 재생성 없이 template fallback(BATTERY_TICKERS 종목명).

경계: 실제 LLM/KIS 호출 없음(LlmClient 주입). contracts/enums 조립·전역 state 없음(supervisor 몫).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import BATTERY_TICKERS
from ..schemas.enums import GenerationSource
from ._llm_utils import (
    LlmClient,
    LlmOutputParseError,
    load_prompt,
    parse_json_object,
    render_prompt,
    unsafe_terms,
)

NORMALIZE_PROMPT = "normalize_question.md"
_ALLOWED_KEYS = frozenset({"normalized_question"})

# 기술적 분석 앵커 단어(최소 1개 이상 포함해야 함). 완전한 의미 판별이 아니라 최소 백스톱.
_TECHNICAL_ANCHORS = frozenset({
    "기술적", "시세", "차트", "추세", "모멘텀", "거래량", "거래대금",
    "지지", "저항", "리스크", "국면", "신호", "흐름", "이동평균", "RSI", "패턴",
})


@dataclass(frozen=True)
class NormalizeResult:
    """노드 1 결과. source는 llm(검증 통과) 또는 template_fallback. 재생성은 노드 1에 없다."""
    normalized_question: str
    source: GenerationSource


def build_payload(*, ticker: str, query: str, as_of: object) -> dict:
    """프롬프트 입력(prompts.md §2). as_of는 문자열로 직렬화한다."""
    return {"ticker": ticker, "query": query, "as_of": str(as_of)}


def run_normalize_question(
    client: LlmClient,
    *,
    ticker: str,
    query: str,
    as_of: object,
) -> NormalizeResult:
    """원문 질문을 안전한 기술적 분석 질의로 정규화한다. 실패 시 보수적 template fallback."""
    if not ticker:
        raise ValueError("ticker is required for normalize_question")
    if not query:
        raise ValueError("query is required for normalize_question")

    prompt = render_prompt(load_prompt(NORMALIZE_PROMPT),
                           build_payload(ticker=ticker, query=query, as_of=as_of))
    # LLM 호출 자체의 예외(TimeoutError 등)는 삼키지 않고 전파한다(supervisor 책임, M3).
    raw = client.complete(prompt)
    try:
        parsed = parse_json_object(raw, allowed_keys=_ALLOWED_KEYS)
    except LlmOutputParseError:
        return _fallback(ticker)

    value = parsed.get("normalized_question")
    if not isinstance(value, str) or not value.strip():  # H1: str 강제 변환 없음
        return _fallback(ticker)
    text = value.strip()
    if unsafe_terms(text):                                 # H3: 공유+전처리 금지어 백스톱
        return _fallback(ticker)
    if not _preserves_ticker(ticker, text):                # M1: 종목명 보존
        return _fallback(ticker)
    if not _has_technical_anchor(text):                    # M1: 기술 앵커
        return _fallback(ticker)
    return NormalizeResult(text, GenerationSource.LLM)


def _preserves_ticker(ticker: str, text: str) -> bool:
    """allowlist 종목이면 표준 종목명이 문장에 있어야 한다. 밖의 ticker는 이 노드에서 판정하지 않음."""
    name = BATTERY_TICKERS.get(ticker)
    if name is None:
        return True
    return name in text


def _has_technical_anchor(text: str) -> bool:
    return any(anchor in text for anchor in _TECHNICAL_ANCHORS)


def _fallback(ticker: str) -> NormalizeResult:
    """보수적 template fallback. allowlist 종목명을 쓰되, 밖의 ticker는 코드 그대로(확장은 상위 책임)."""
    name = BATTERY_TICKERS.get(ticker, ticker)
    text = (f"{name}의 최근 시세와 기술적 신호를 중심으로 현재 차트 국면과 "
            f"리스크 관찰점을 분석합니다.")
    return NormalizeResult(text, GenerationSource.TEMPLATE_FALLBACK)
