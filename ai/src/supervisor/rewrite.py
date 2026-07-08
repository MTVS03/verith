"""agent 별 rewritten_query 생성 (결정론 템플릿).

Supervisor 는 자연어 query 와 공통 stock context 까지만 책임진다. rewritten_query 는 LLM 없이
agent 관점별 고정 템플릿으로 만든다(테스트 가능·결합 최소). 두 형태:
- 종목 확정: 종목명을 주어로 하는 관점 템플릿.
- 종목 미확정: 종목 의존 agent 는 일반형(실행 불가지만 봉투는 유지), news/industry 는 원문 질문을
  담아 주제(예: "2차전지")를 보존한다.

여기서 corp_code/ticker 를 만들지 않는다 — context 의 stock_code 는 resolver 결과에서만 온다.
"""

from __future__ import annotations

from src.supervisor.schemas import AgentType, StockContext

# 종목 확정 시: "{name}" 슬롯.
_STOCK_TEMPLATES: dict[AgentType, str] = {
    "fundamental": "{name}의 최근 실적, 수익성, 안정성, 밸류에이션 관점에서 재무 상태를 분석해줘.",
    "technical": "{name}의 최근 주가 흐름, 거래량, 이동평균, 지지선/저항선 기준으로 기술적 상태를 분석해줘.",
    "news": "{name} 관련 최근 뉴스와 주요 이벤트, 시장 심리를 정리해줘.",
    "flow": "{name}의 최근 외국인·기관·개인 수급 흐름을 분석해줘.",
    "industry": "{name}이 속한 산업의 경쟁 구도, 업황, 정책/거시 환경을 분석해줘.",
}

# 종목 미확정 + 종목 의존 agent: 일반형(§9 예시 형태). 실행 불가지만 봉투는 유지.
_NO_STOCK_DEPENDENT: dict[AgentType, str] = {
    "fundamental": "사용자 질문을 재무(실적·수익성·안정성·밸류에이션) 관점에서 분석해줘.",
    "technical": "사용자 질문을 기술적(주가·거래량·추세) 관점에서 분석해줘.",
    "flow": "사용자 질문을 수급(외국인·기관·개인) 관점에서 분석해줘.",
}

# 종목 미확정 + 종목 선택 agent(news/industry): 원문 질문을 담아 주제를 보존한다.
_NO_STOCK_OPTIONAL: dict[AgentType, str] = {
    "news": "다음 질문과 관련된 최근 뉴스·주요 이벤트·시장 심리를 정리해줘: {query}",
    "industry": "다음 질문을 산업 구조·경쟁 구도·업황·정책/거시 관점에서 분석해줘: {query}",
}


def rewrite(agent_type: AgentType, context: StockContext, original_query: str) -> str:
    """agent 관점의 rewritten_query. 종목명이 있으면 종목형, 없으면 미확정형."""
    if context.stock_name:
        return _STOCK_TEMPLATES[agent_type].format(name=context.stock_name)
    if agent_type in _NO_STOCK_OPTIONAL:
        return _NO_STOCK_OPTIONAL[agent_type].format(query=original_query)
    return _NO_STOCK_DEPENDENT[agent_type]
