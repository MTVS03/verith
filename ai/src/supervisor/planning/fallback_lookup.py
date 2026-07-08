"""fallback 종목 lookup 경계 — canonical resolver 가 not_found 일 때만 쓰는 보조 조회.

**절대 원칙: ephemeral resolve 허용 / persistent write 금지.** 이 계층은 이번 요청에 한해 종목을 한 번 더
찾아볼 뿐, `stocks`/`stock_aliases`/`stock_corp_codes` 정본을 절대 수정하지 않는다. 결과는 항상
persisted=False 인 임시 context 로만 쓰인다(planner 가 그렇게 감싼다).

경계 규칙:
- canonical resolver 를 **대체하지 않고 보조**한다. planner 는 canonical `not_found` 일 때만 이걸 부른다.
- **ticker 를 상상하지 않는다.** 근거 없는 fuzzy correction 금지 — 확신 없으면 not_found 를 유지한다.
- 확신되는 **단일** 후보일 때만 resolved. 후보가 여럿이면 ambiguous(자동선택 금지).

source 경계(무엇을 fallback 으로 볼지): 이 계층은 **supervisor 내부 전용 lookup client** 로,
`FallbackLookupProtocol` 을 주입식으로 연다. 기본 구현 `StaticFallbackLookup` 은 **명시적으로 큐레이션된
정규화-별칭을 조회**한다(사람이 근거를 넣은 데이터 — AI 추정 아님). 운영에서 KIS master/DART 기반의 얇은
조회 client 로 교체하려면 같은 protocol 로 주입하면 된다. 저장/색인/seed/sync 는 이 계층이 아니라 별도
승인형 관리 플로우의 몫이다.

**매칭 정확도(중요):** `StaticFallbackLookup` 은 **정규화 substring containment** 다 — full-string exact
가 아니라, 정규화한 질의 안에 정규화한 key 가 부분문자열로 들어있으면 hit(예: key "카카오" ⊂ "카카오주가어때").
fuzzy·edit-distance·유사도 추정은 하지 않는다. 운영 client 로 교체할 때 이 매칭 성격(부분문자열 포함)을
팀이 알고 있어야 한다.

테스트는 실 네트워크 대신 `FakeFallback`(tests/_fakes.py) 또는 커스텀 entries 를 주입한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Protocol

from src.supervisor.schemas import StockCandidate, StockContext

# fallback 조회 도메인 결과. canonical resolver 의 ResolveResult 와 같은 3-상태 모델(대체가 아니라 대칭).
FallbackStatus = Literal["resolved", "ambiguous", "not_found"]

_NORMALIZE_STRIP = re.compile(r"[\s\-_.·&()]+")


def _normalize(text: str) -> str:
    """결정론 정규화 — 소문자 + 공백/구두점 제거. fuzzy(오탈자 교정·유사도) 는 하지 않는다."""
    return _NORMALIZE_STRIP.sub("", text.lower())


class FallbackLookupError(RuntimeError):
    """fallback lookup 도구 자체의 실패(연결·형식 등). planner 는 이걸 잡아 not_found 를 유지한다
    (canonical not_found 를 error 로 바꾸지 않는다 — fallback 은 어디까지나 보조)."""


@dataclass
class FallbackResult:
    status: FallbackStatus
    stock: StockContext | None = None
    candidates: list[StockCandidate] = field(default_factory=list)


class FallbackLookupProtocol(Protocol):
    """supervisor 가 의존하는 최소 경계. 도메인 결과 반환, 도구 장애면 FallbackLookupError."""

    def lookup(self, query: str) -> FallbackResult:
        ...


# 명시적으로 큐레이션된 fallback entries(정규화 key → 종목). **AI 추정이 아니라 사람이 근거를 넣은 데이터.**
# 기본은 비어 있다 — canonical 이 이미 broad universe(2,607)라 대부분 여기 오지 않으며, 근거 없는 매핑을
# 함부로 싣지 않는다. 운영에서 필요한 항목만 리뷰를 거쳐 추가하거나, KIS/DART 기반 client 로 교체 주입한다.
DEFAULT_FALLBACK_ENTRIES: dict[str, StockContext] = {}


class StaticFallbackLookup:
    """큐레이션된 정규화-별칭을 **정규화 substring containment** 로 조회하는 얇은 기본 구현(fuzzy 아님).

    정규화한 query 안에 정규화한 큐레이션 key 가 **부분문자열로** 들어있으면 후보로 본다(full-string exact
    아님 — edit-distance/유사도도 아님). 서로 다른 stock_code 가 2개 이상이면 ambiguous(자동선택 금지),
    하나면 resolved, 없으면 not_found. persisted 표기는 planner 가 최종 부여하므로 여기 stock 은
    원자료(code/name/market)만 담는다."""

    def __init__(self, entries: dict[str, StockContext] | None = None) -> None:
        self._entries = entries if entries is not None else DEFAULT_FALLBACK_ENTRIES

    def lookup(self, query: str) -> FallbackResult:
        norm_query = _normalize(query)
        if not norm_query:
            return FallbackResult(status="not_found")
        hits: dict[str, StockContext] = {}  # stock_code → context(중복 stock_code 는 1회)
        for key, ctx in self._entries.items():
            if ctx.stock_code and _normalize(key) and _normalize(key) in norm_query:
                hits.setdefault(ctx.stock_code, ctx)
        if len(hits) == 1:
            (ctx,) = hits.values()
            return FallbackResult(status="resolved", stock=ctx)
        if len(hits) >= 2:
            cands = [
                StockCandidate(stock_code=c.stock_code, stock_name=c.stock_name or "", market=c.market)
                for c in hits.values()
            ]
            cands.sort(key=lambda c: c.stock_code)  # 결정론 순서
            return FallbackResult(status="ambiguous", candidates=cands)
        return FallbackResult(status="not_found")
