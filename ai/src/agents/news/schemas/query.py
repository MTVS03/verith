# schemas/query.py — 질의측 전용 스키마(신규, TASK 09 소유)
"""① 질문 파싱 결과 + ④ 답변 구조. LLM 출력은 반드시 이 모델로 파싱·검증한다(CLAUDE.md §2-3).

질의 흐름(자유 질문형 B) 전용이며 TASK 01(배치측 report/response 스키마)과 독립이다(관심사 분리).
- QueryUnderstanding: ① 질문이해 산출(companies·period·intent, query_spec §2-①).
- Answer: ④ 답변 그 자체(뉴스 흐름 요약 본문 + 근거 news_id/event_id, §0.2). 근거 없는 값을 지어내지 않는다.
- QueryResult: (선택) 흐름 번들. state 대신 타입 안전하게 넘기고 싶을 때.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from src.agents.news.schemas.response import SubjectQueryResponse


class QueryIntent(str, Enum):
    """질문 의도. '뉴스 흐름 요약' 섹션의 초점·분량을 결정(별도 텍스트 채널 on/off 가 아님, query_spec §2-①)."""
    RELATION = "관계"
    REASON = "이유"
    SUMMARY = "요약"
    STATUS = "현황"


class QueryUnderstanding(BaseModel):
    """① 질문이해 결과. companies·period·intent(query_spec §2-①). 감성 필드는 없다(절대규칙 4)."""
    companies: list[str] = Field(default_factory=list)
    period_days: int = 7                       # 기본 QUERY_DEFAULT_PERIOD_DAYS(노드/서비스가 config로 주입)
    intent: QueryIntent = QueryIntent.SUMMARY
    is_preset: bool = False                    # 종목 선택(A) 프리셋 여부
    # 사전·LLM에서 회사로 확정 못 해 버린 토큰(억지 매핑·환각 방지 후 관측·사전 보강용, query_spec §①-1·§4).
    dropped_tokens: list[str] = Field(default_factory=list)
    original_question: str | None = None       # 사용자 원문 질문(raw llm output/json과 혼동 방지해 original_)


class Answer(BaseModel):
    """④ 답변. text = 뉴스 흐름 요약 본문 그 자체. 모든 주장에 근거 news_id 를 부착(§0.2)."""
    text: str
    # 근거 news_id(= Article.id, 정수). backend가 부여한 실제 값만 담는다(지어내지 않음, 환각 금지).
    evidence_news_ids: list[int] = Field(default_factory=list)
    # 근거 이슈 칩이 링크할 이벤트 canonical_id. 본문이 실제 언급한 이벤트만.
    cited_event_ids: list[str] = Field(default_factory=list)
    data_limited: bool = False                 # 근거 부족 시 True("데이터 제한" 표기, 절대규칙 5)


class QueryResult(BaseModel):
    """(선택) 흐름 번들 — understanding·response·answer 를 한 객체로. 없어도 노드가 state 키로 전달 가능."""
    understanding: QueryUnderstanding
    response: SubjectQueryResponse
    answer: Answer
