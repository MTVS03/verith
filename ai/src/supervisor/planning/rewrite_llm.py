"""agent 별 지시(rewritten_query)를 LLM 으로 성형 — 주입식, 실패 시 결정론 템플릿으로 fallback.

설계(supervisor 고도화): supervisor 는 사용자 원문을 5개 에이전트에 '맞춤 지시'로 성형해 보낸다.
- 자연어형(news/industry): 사용자 원문의 주제·구체 표현을 **보존**(좁히거나 버리지 않음).
- 코드형(technical/fundamental/flow): 사용자 의도 중 **그 관점 축으로 초점**을 좁힘.

**절대 안전선**: LLM 은 '지시(자연어)'만 만든다. 종목코드(stock_code)는 resolver 결과에서만 오며
`TaskEnvelope.context` 로 별도 부착된다 — LLM 출력은 `rewritten_query`(자연어)만 채운다. 그래서
LLM 이 코드를 지어내도 봉투의 구조 필드(stock_code)로는 절대 흘러들어가지 않는다(구조적 차단).

결정론 우선: LLM 은 주입식이다. 미주입이면 `TemplateRewriter`(기존 결정론 템플릿)를 쓴다.
`LlmRewriter` 도 호출·파싱·검증 실패 시 **에이전트별로** 템플릿으로 안전 착지한다
(technical 의 StructuredOutput + template_fallback 과 같은 철학).
"""

from __future__ import annotations

import json
from typing import Protocol

from src.supervisor.planning.rewrite import rewrite
from src.supervisor.schemas import AGENT_ORDER, AgentType, StockContext


class RewriteLlm(Protocol):
    """최소 LLM 경계(주입식). prompt → completion 문자열. technical LlmClient 와 구조 호환."""

    def complete(self, prompt: str) -> str: ...


class QueryRewriter(Protocol):
    """사용자 원문 + 종목 context → 에이전트별 rewritten_query dict(5개 전부)."""

    def rewrite_all(self, original_query: str, context: StockContext) -> dict[AgentType, str]: ...


class TemplateRewriter:
    """결정론 템플릿 rewriter(기본·fallback). 기존 rewrite() 를 에이전트별로 호출한다."""

    def rewrite_all(self, original_query: str, context: StockContext) -> dict[AgentType, str]:
        return {a: rewrite(a, context, original_query) for a in AGENT_ORDER}


# 각 에이전트가 보는 관점(프롬프트 카드). **카드가 곧 계약** — 에이전트 입력 계약이 바뀌면 여기도 갱신.
_AGENT_CARDS: dict[AgentType, str] = {
    "technical": "주가·거래량·이동평균·지지/저항·추세 등 기술적 상태. 사용자 의도 중 '가격/차트' 축으로 초점.",
    "fundamental": "실적·수익성·안정성·성장·밸류에이션 등 재무 상태. '재무' 축으로 초점(키워드 예: 수익성/부채/성장/밸류).",
    "flow": "외국인·기관·개인 수급 흐름. '수급' 축으로 초점.",
    "news": "관련 최근 뉴스·주요 이벤트·시장 심리. 사용자 원문의 주제·구체 표현을 그대로 보존.",
    "industry": "산업 구조·경쟁 구도·업황·정책/거시. 사용자 원문의 주제를 그대로 보존.",
}

_PROMPT = """당신은 사용자의 투자 관련 질문을 5개 분석 에이전트에 맞는 '지시'로 재작성한다.
각 에이전트의 관점(카드)에 맞춰 사용자의 실제 의도를 담은 지시를 한국어 1~2문장으로 쓴다.

절대 규칙:
- 종목코드/ticker(6자리 숫자)를 만들어 넣지 마라. 종목은 별도로 부착된다.
- news, industry: 사용자 원문의 주제·구체 표현을 그대로 보존하라(좁히거나 버리지 마라).
- technical, fundamental, flow: 사용자 의도 중 그 관점 축으로 초점을 좁혀라.

종목 컨텍스트: {stock_line}
사용자 질문: {query}

에이전트 카드:
{cards}

출력: 아래 5개 키를 모두 가진 JSON 객체 하나만. 코드블록·설명 금지.
{{"fundamental": "...", "technical": "...", "news": "...", "flow": "...", "industry": "..."}}"""


def _stock_line(context: StockContext) -> str:
    return f"확정: {context.stock_name}" if context.stock_name else "미확정(특정 종목 없음)"


def build_prompt(original_query: str, context: StockContext) -> str:
    """LLM 프롬프트 조립(테스트에서 검증 가능하도록 공개)."""
    cards = "\n".join(f"- {a}: {_AGENT_CARDS[a]}" for a in AGENT_ORDER)
    return _PROMPT.format(stock_line=_stock_line(context), query=original_query, cards=cards)


def _parse(raw: str) -> dict:
    """completion 문자열에서 JSON 객체 하나를 관대하게 추출·파싱. 실패는 예외."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("JSON 객체를 찾지 못함")
    return json.loads(raw[start : end + 1])


class LlmRewriter:
    """LLM 성형 rewriter. 1회 호출로 5개 지시 생성, 실패는 **에이전트별** 템플릿 fallback.

    llm 은 주입식(RewriteLlm). fallback 은 결정론 TemplateRewriter(미지정 시 기본 생성). LLM 출력은
    rewritten_query(자연어)만 채운다 — 종목코드는 봉투 조립 시 resolver context 에서 온다(구조적 분리).
    """

    def __init__(self, llm: RewriteLlm, *, fallback: QueryRewriter | None = None) -> None:
        self._llm = llm
        self._fallback = fallback or TemplateRewriter()

    def rewrite_all(self, original_query: str, context: StockContext) -> dict[AgentType, str]:
        template = self._fallback.rewrite_all(original_query, context)
        try:
            raw = self._llm.complete(build_prompt(original_query, context))
            parsed = _parse(raw)
        except Exception:  # noqa: BLE001 - LLM/파싱 실패 → 전부 템플릿으로 안전 착지(비차단)
            return template
        out: dict[AgentType, str] = {}
        for a in AGENT_ORDER:
            v = parsed.get(a)
            # 값이 유효한 문자열이면 그 지시, 아니면 해당 에이전트만 템플릿으로 fallback.
            out[a] = v.strip() if isinstance(v, str) and v.strip() else template[a]
        return out
