"""Stock Resolver — 자연어 질의에서 종목 식별 (단일 종목 확정까지만).

판정 규칙(확정):
- 매칭 소스: 6자리 코드(원문, stocks 존재분만) + 공식 이름(stocks.stock_name) + 별칭(stock_aliases).
- longest-match: 정규화 질의에서 부분문자열 출현을 찾되, 더 긴 출현에 완전히 포함된 짧은 출현은 제거
  (에코프로 ⊂ 에코프로비엠, LG ⊂ LG에너지솔루션).
- dedup: stock_code 1회, 최고 우선순위(stock_code > stock_name > alias > ambiguous_group) 보존.
- status:
    원문에 stocks 에 없는 6자리 코드 존재  → ambiguous / unknown_identifier (조용히 무시 금지)
    후보 0                                   → not_found / no_match
    후보 1                                   → resolved / exact_match
    후보 2+:
      코드 매칭 종목과 이름/별칭 매칭 종목이 공존(→ 다른 종목)  → conflicting_identifiers
      전부 ambiguous_group 에서만 파생                          → ambiguous_alias
      그 외 명시적 복수                                        → multiple_stocks
- ambiguous_group 은 절대 단일 자동확정하지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.repositories import stock_repository as repo
from src.api.schemas.stock_resolve import (
    ResolvedStock,
    StockCandidate,
    StockResolveResponse,
)
from src.api.text_normalize import normalize_stock_text

_CODE_RE = re.compile(r"\d{6}")
_MATCH_PRIORITY = {"stock_code": 0, "stock_name": 1, "alias": 2, "ambiguous_group": 3}
_MAX_CANDIDATES = 10


class EmptyQueryError(ValueError):
    """정규화 결과가 빈 문자열 — 422 로 매핑."""


@dataclass
class _Entry:
    normalized: str
    original: str
    stock_code: str
    match_type: str  # stock_name | alias | ambiguous_group


@dataclass
class _Occ:
    start: int
    end: int
    entry: _Entry


@dataclass
class _Cand:
    stock_code: str
    match_type: str
    matched_text: str
    match_len: int


class StockResolverService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(self, query: str) -> StockResolveResponse:
        norm = normalize_stock_text(query)
        if not norm:
            raise EmptyQueryError("정규화 결과가 비어 있습니다")

        stocks = await repo.get_all_stocks(self._session)
        aliases = await repo.get_all_aliases(self._session)
        stock_by_code = {s.stock_code: s for s in stocks}

        # 1) 원문 6자리 코드 → 존재/미존재 분리.
        codes = _CODE_RE.findall(query)
        known_codes = [c for c in codes if c in stock_by_code]
        unknown_codes = [c for c in codes if c not in stock_by_code]

        # 2) 검색 엔트리: 공식 이름(stock_name) + 별칭.
        entries: list[_Entry] = []
        for s in stocks:
            nt = normalize_stock_text(s.stock_name)
            if nt:
                entries.append(_Entry(nt, s.stock_name, s.stock_code, "stock_name"))
        for a in aliases:
            mt = "ambiguous_group" if a.alias_type == "ambiguous_group" else "alias"
            entries.append(_Entry(a.normalized_alias, a.alias, a.stock_code, mt))

        # 3) 정규화 질의 안의 부분문자열 출현 수집.
        occs: list[_Occ] = []
        for e in entries:
            if not e.normalized:
                continue
            i = norm.find(e.normalized)
            while i != -1:
                occs.append(_Occ(i, i + len(e.normalized), e))
                i = norm.find(e.normalized, i + 1)

        # 4) longest-match: 더 긴 출현에 완전히 포함된 짧은 출현 제거.
        kept = [
            o
            for o in occs
            if not any(
                other.start <= o.start
                and other.end >= o.end
                and (other.end - other.start) > (o.end - o.start)
                for other in occs
            )
        ]

        # 5) 후보 dedup(stock_code 1회, 최고 우선순위·최장 매칭 보존).
        best: dict[str, _Cand] = {}

        def consider(code: str, mt: str, text: str, length: int) -> None:
            key = (_MATCH_PRIORITY[mt], -length)
            cur = best.get(code)
            if cur is None or key < (_MATCH_PRIORITY[cur.match_type], -cur.match_len):
                best[code] = _Cand(code, mt, text, length)

        for c in known_codes:
            consider(c, "stock_code", c, len(c))
        for o in kept:
            consider(o.entry.stock_code, o.entry.match_type, o.entry.original, o.end - o.start)

        candidates = self._sorted_candidates(best, stock_by_code)

        # 6) status 판정.
        code_stocks = set(known_codes)
        name_alias_stocks = {c.stock_code for c in best.values() if c.match_type in ("stock_name", "alias")}

        if unknown_codes:
            return StockResolveResponse(status="ambiguous", reason="unknown_identifier", candidates=candidates)
        if not best:
            return StockResolveResponse(status="not_found", reason="no_match")
        if len(best) == 1:
            only = next(iter(best.values()))
            s = stock_by_code[only.stock_code]
            return StockResolveResponse(
                status="resolved",
                reason="exact_match",
                stock=ResolvedStock(stock_code=s.stock_code, stock_name=s.stock_name, market=s.market),
            )
        # 후보 2+
        if code_stocks and name_alias_stocks:
            reason = "conflicting_identifiers"
        elif not code_stocks and not name_alias_stocks:
            reason = "ambiguous_alias"  # 전부 ambiguous_group
        else:
            reason = "multiple_stocks"
        return StockResolveResponse(status="ambiguous", reason=reason, candidates=candidates)

    def _sorted_candidates(self, best: dict[str, _Cand], stock_by_code) -> list[StockCandidate]:
        # 정렬: match 우선순위 → matched_text(정규화 매칭) 길이 desc → stock_code asc.
        ordered = sorted(
            best.values(),
            key=lambda c: (_MATCH_PRIORITY[c.match_type], -c.match_len, c.stock_code),
        )
        out: list[StockCandidate] = []
        for c in ordered[:_MAX_CANDIDATES]:
            s = stock_by_code[c.stock_code]
            out.append(
                StockCandidate(
                    stock_code=s.stock_code,
                    stock_name=s.stock_name,
                    market=s.market,
                    matched_text=c.matched_text,
                    match_type=c.match_type,
                )
            )
        return out
