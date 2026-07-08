"""질문 해석 + resolve-gate (deterministic 우선, LLM 주입식).

Supervisor 는 **모든 질문에 resolve 를 먼저 걸지 않는다**(§7.1). 여기서 질문이 특정 종목을 겨냥하는지
결정론 규칙으로 판단해 `should_resolve` 를 정한다. 산업/시장/일반형이면 resolve 를 시도하지 않는다.

정책상 애매하면 resolve 를 시도하는 쪽이 안전하다 — resolver 가 not_found(정상 200)를 돌려줄 뿐이고,
종목 의존 agent 는 그 결과로 can_run=false 를 받는다. 도구 장애와 not_found 는 별개로 취급된다.

LLM 분류는 `QueryClassifier` 주입으로 확장 가능하게 열어두되, 이번 브랜치 기본값은 결정론 휴리스틱이다
(모든 정책을 LLM 에 위임하지 않는다).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

QuestionKind = Literal["company", "industry", "market", "general"]

# 특정 종목을 겨냥하는 신호(가격/수급/재무 등 종목 축 액션). 영문은 소문자 비교.
_STOCK_ACTION_MARKERS = (
    "주가", "차트", "캔들", "이평", "이동평균", "지지", "저항", "거래량", "모멘텀",
    "수급", "외국인", "기관", "개인", "순매수", "순매도", "매수", "매도",
    "재무", "실적", "밸류", "밸류에이션", "배당", "목표주가", "종목",
    "per", "pbr", "roe", "eps",
)
# 산업/섹터형 신호(비특정 종목).
_INDUSTRY_MARKERS = ("산업", "업종", "섹터", "업황", "밸류체인", "공급망", "전방", "후방")
# 시장/거시형 신호(비특정 종목).
_MARKET_MARKERS = ("시장", "증시", "코스피", "코스닥", "지수", "시황", "분위기", "거시", "경기")

_SIX_DIGITS = re.compile(r"\d{6}")


@dataclass(frozen=True)
class Interpretation:
    question_kind: QuestionKind
    should_resolve: bool


class QueryClassifier(Protocol):
    """LLM 등 대체 분류기 주입점. 없으면 결정론 휴리스틱을 쓴다."""

    def classify(self, query: str) -> Interpretation:
        ...


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(m in text for m in markers)


def _heuristic(query: str) -> Interpretation:
    low = query.lower()
    # 1) 6자리 코드나 종목 축 액션이 있으면 특정 종목 질문으로 보고 resolve.
    if _SIX_DIGITS.search(query) or _has_any(low, _STOCK_ACTION_MARKERS):
        return Interpretation(question_kind="company", should_resolve=True)
    # 2) 산업/시장 신호만 있으면 비특정 → resolve 안 함.
    if _has_any(low, _INDUSTRY_MARKERS):
        return Interpretation(question_kind="industry", should_resolve=False)
    if _has_any(low, _MARKET_MARKERS):
        return Interpretation(question_kind="market", should_resolve=False)
    # 3) 신호 없음 — "삼성전자 어때?" 같은 bare 종목 질문일 수 있으므로 시도(안전).
    return Interpretation(question_kind="company", should_resolve=True)


def interpret(query: str, *, classifier: QueryClassifier | None = None) -> Interpretation:
    """질문 해석. classifier 를 주입하면 그것으로, 아니면 결정론 휴리스틱으로 판단한다."""
    if classifier is not None:
        return classifier.classify(query)
    return _heuristic(query)
