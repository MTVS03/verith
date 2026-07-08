"""Stock Resolver — 자연어 질의에서 종목 식별 (boundary-aware).

전체 종목으로 확장돼도 오탐하지 않도록, **무제한 substring 대신 원문 token 경계** 기준으로 매칭한다.
매칭 흐름(우선순위):
  1) 원문 6자리 stock code exact
  2) 전체 normalized query == 공식명/alias exact
  3) 독립 token 또는 연속 token 매칭 (경계 보존)
  4) token 끝의 **승인된 조사/문맥 suffix 하나만** 제거 후 exact (무공백 결합형: "카카오주가"→"카카오")
  5) 같은 span 은 longest-match
  6) stock_code 기준 dedup
짧은 이름(normalized 길이 ≤ 2)은 **전체 질의 완전 일치이거나 문맥 키워드가 있을 때만** 후보로 인정한다
(예: "대상 주가" 가능, "투자 대상을 알려줘" 금지). ambiguous_group 은 단일 자동확정하지 않는다.

동일 normalized 이름이 여러 stock_code 에 매칭되면 자동 선택하지 않고 ambiguous/multiple_stocks.
공식명은 stocks.stock_name, 별칭은 stock_aliases 에서 읽는다(둘 다 근거). AI import 없음.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.constants.stock_match import (
    CONTEXT_SUFFIXES,
    JOSA_SUFFIXES,
    SHORT_NAME_MAX_LEN,
)
from src.api.repositories import stock_repository as repo
from src.api.schemas.stock_resolve import (
    ResolvedStock,
    StockCandidate,
    StockResolveResponse,
)
from src.api.text_normalize import normalize_stock_text

_CODE_RE = re.compile(r"\d{6}")
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
_MAX_RUN = 5  # 연속 token 최대 결합 수(다어절 종목명 대비)
_MATCH_PRIORITY = {"stock_code": 0, "stock_name": 1, "alias": 2, "ambiguous_group": 3}
_MAX_CANDIDATES = 10

_CONTEXT_SET = frozenset(CONTEXT_SUFFIXES)
# 끝에서 제거할 접미(조사+문맥) — 긴 것 우선.
_STRIP_SUFFIXES = tuple(sorted(set(JOSA_SUFFIXES) | set(CONTEXT_SUFFIXES), key=len, reverse=True))


class EmptyQueryError(ValueError):
    """정규화 결과가 빈 문자열 — 422 로 매핑."""


@dataclass
class _Entry:
    normalized: str
    original: str
    stock_code: str
    match_type: str  # stock_name | alias | ambiguous_group


@dataclass
class _Match:
    start: int
    end: int  # token span [start, end] inclusive
    entry: _Entry
    via_context: bool  # 제거한 접미가 문맥 키워드였는지


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
        full_norm = normalize_stock_text(query)
        if not full_norm:
            raise EmptyQueryError("정규화 결과가 비어 있습니다")

        stocks = await repo.get_all_stocks(self._session)
        aliases = await repo.get_all_aliases(self._session)
        stock_by_code = {s.stock_code: s for s in stocks}

        codes = _CODE_RE.findall(query)
        known_codes = [c for c in codes if c in stock_by_code]
        unknown_codes = [c for c in codes if c not in stock_by_code]

        # 검색 엔트리(공식명 + 별칭). normalized 로 색인.
        entries_by_norm: dict[str, list[_Entry]] = defaultdict(list)
        for s in stocks:
            nt = normalize_stock_text(s.stock_name)
            if nt:
                entries_by_norm[nt].append(_Entry(nt, s.stock_name, s.stock_code, "stock_name"))
        for a in aliases:
            mt = "ambiguous_group" if a.alias_type == "ambiguous_group" else "alias"
            entries_by_norm[a.normalized_alias].append(
                _Entry(a.normalized_alias, a.alias, a.stock_code, mt)
            )

        tokens = [t for t in (normalize_stock_text(x) for x in _TOKEN_RE.findall(
            unicodedata.normalize("NFKC", query))) if t]
        context_present = any(t in _CONTEXT_SET for t in tokens)

        matches = self._collect_matches(tokens, entries_by_norm)

        # 후보 dedup(stock_code 1회, 최고 우선순위·최장 이름 보존).
        best: dict[str, _Cand] = {}

        def consider(code: str, mt: str, text: str, length: int) -> None:
            key = (_MATCH_PRIORITY[mt], -length)
            cur = best.get(code)
            if cur is None or key < (_MATCH_PRIORITY[cur.match_type], -cur.match_len):
                best[code] = _Cand(code, mt, text, length)

        for c in known_codes:
            consider(c, "stock_code", c, len(c))
        for m in matches:
            e = m.entry
            # 짧은 이름 보수 규칙.
            if len(e.normalized) <= SHORT_NAME_MAX_LEN:
                if not (full_norm == e.normalized or m.via_context or context_present):
                    continue
            consider(e.stock_code, e.match_type, e.original, len(e.normalized))

        candidates = self._sorted_candidates(best, stock_by_code)

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
        if code_stocks and name_alias_stocks:
            reason = "conflicting_identifiers"
        elif not code_stocks and not name_alias_stocks:
            reason = "ambiguous_alias"
        else:
            reason = "multiple_stocks"
        return StockResolveResponse(status="ambiguous", reason=reason, candidates=candidates)

    def _collect_matches(
        self, tokens: list[str], entries_by_norm: dict[str, list[_Entry]]
    ) -> list[_Match]:
        """token 경계 기준 매칭 + 접미 1개 제거 + 같은 span longest-match."""
        raw: list[_Match] = []
        n = len(tokens)
        for i in range(n):
            concat = ""
            for j in range(i, min(i + _MAX_RUN, n)):
                concat += tokens[j]
                for e in entries_by_norm.get(concat, ()):
                    raw.append(_Match(i, j, e, via_context=False))
                # 끝에서 승인된 접미 1개(가장 긴 것)만 제거 후 exact.
                for suf in _STRIP_SUFFIXES:
                    if len(concat) > len(suf) and concat.endswith(suf):
                        stripped = concat[: -len(suf)]
                        for e in entries_by_norm.get(stripped, ()):
                            raw.append(_Match(i, j, e, via_context=(suf in _CONTEXT_SET)))
                        break

        # longest-match: 더 넓은 token span 에 완전히 포함된 짧은 매칭 제거.
        kept = [
            m
            for m in raw
            if not any(
                o.start <= m.start and o.end >= m.end and (o.end - o.start) > (m.end - m.start)
                for o in raw
            )
        ]
        return kept

    def _sorted_candidates(self, best: dict[str, _Cand], stock_by_code) -> list[StockCandidate]:
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
