"""운영형 fallback source + composite — canonical not_found 일 때 쓰는 **결정론** 보조 조회.

절대 원칙(상위 §fallback): ephemeral only. 이 계층은 이번 요청에 한해 종목을 더 찾아볼 뿐, canonical
정본(`stocks`/`stock_aliases`/`stock_corp_codes`)을 절대 write 하지 않는다. persisted 표기는 planner 가
최종 부여한다(여기 stock 은 원자료만 담는다).

설계:
- `FallbackSource` = 하나의 근거 있는 source(주입식). `find(query)` 로 **원시 hit 목록**을 돌려준다.
  도구 장애면 `FallbackLookupError`(fallback_lookup.py)를 던진다.
- `CuratedFallbackSource` = 사람이 리뷰한 **결정론 curated 매핑**(code/name/alias exact). fuzzy·edit-distance·
  LLM 보정·벡터검색 **없음**. 이번 브랜치의 1차 운영 source.
- `CompositeFallbackLookup` = 여러 source 를 합쳐 하나의 `FallbackResult` 로 판정(`FallbackLookupProtocol`).
  서로 다른 source 가 같은 stock_code → dedup(단일), 다른 stock_code → ambiguous(자동선택 금지).
- 확장점: KIS master/DART 기반 source 를 나중에 같은 `FallbackSource` 로 추가 주입하면 된다(네트워크 client 는
  후속). import 시 네트워크 호출 없음.

매칭 규칙(결정론):
- **code exact 최우선**: 질의에 6자리 토큰이 있고 그게 curated code 면 최우선.
- 그다음 **정규화 name/alias 매칭**. latin alias 는 **토큰 word-boundary**(부분단어 오탐 방지: "kia" ⊄ "nikita"),
  한글 포함 alias 는 **정규화 substring**(한글은 붙여쓰기 흔함: "카카오" ⊂ "카카오주가어때").
- 같은 질의에서 서로 다른 stock_code 2개↑ → ambiguous. 단일이면 resolved. 없으면 not_found.
- 애매하면 임의 선택하지 않는다(ambiguous 우선).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

from src.supervisor.planning.fallback_lookup import FallbackResolveMeta, FallbackResult
from src.supervisor.schemas import StockCandidate, StockContext

# hit 이 어떤 근거로 잡혔는지(왜 resolved/ambiguous 인지 설명 가능하게). 우선순위 랭크에도 쓴다.
MatchReason = Literal["code_exact", "name_exact", "alias_exact"]
_MATCH_RANK: dict[MatchReason, int] = {"code_exact": 3, "name_exact": 2, "alias_exact": 1}

# 토큰 = 소문자 latin/숫자 런 또는 한글 음절 런. 공백/구두점/스크립트 경계에서 끊는다.
_TOKEN_RE = re.compile(r"[a-z0-9]+|[가-힣]+")
_CODE_RE = re.compile(r"^\d{6}$")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _is_sublist(sub: list[str], seq: list[str]) -> bool:
    """sub 가 seq 의 **연속 부분열**인지(단어 경계 매칭)."""
    n, m = len(sub), len(seq)
    if n == 0 or n > m:
        return False
    return any(seq[i : i + n] == sub for i in range(m - n + 1))


def _matches(needle: str, q_tokens: list[str], q_norm: str) -> bool:
    """needle(name/alias)이 질의에 결정론적으로 매칭되는지. latin=단어경계, 한글포함=정규화 substring."""
    n_tokens = _tokens(needle)
    if not n_tokens:
        return False
    if all(t.isascii() for t in n_tokens):     # 순수 latin/숫자 → 단어 경계(부분단어 오탐 방지)
        return _is_sublist(n_tokens, q_tokens)
    return "".join(n_tokens) in q_norm         # 한글 포함 → 붙여쓰기 친화 substring


@dataclass(frozen=True)
class FallbackEntry:
    """curated 종목 레코드. aliases 는 canonical 이 흔히 놓치는 표기(영문/로마자/약칭 등)."""

    stock_code: str
    stock_name: str
    market: str | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceHit:
    stock_code: str
    stock_name: str
    market: str | None
    match: MatchReason
    source: str


class FallbackSource(Protocol):
    """근거 있는 단일 source 경계. find 는 원시 hit 을 돌려주고, 도구 장애면 FallbackLookupError."""

    name: str

    def find(self, query: str) -> list[SourceHit]:
        ...


class CuratedFallbackSource:
    """사람이 리뷰한 결정론 curated 매핑 source(code/name/alias exact). fuzzy 아님."""

    def __init__(self, entries: tuple[FallbackEntry, ...] | list[FallbackEntry], *, name: str = "curated") -> None:
        self.name = name
        self._entries = tuple(entries)
        self._by_code = {e.stock_code: e for e in self._entries}

    def find(self, query: str) -> list[SourceHit]:
        q_tokens = _tokens(query)
        q_norm = "".join(q_tokens)
        hits: list[SourceHit] = []
        # 1) code exact — 질의의 6자리 토큰이 curated code 와 정확히 일치.
        for tok in q_tokens:
            if _CODE_RE.match(tok) and tok in self._by_code:
                e = self._by_code[tok]
                hits.append(SourceHit(e.stock_code, e.stock_name, e.market, "code_exact", self.name))
        # 2) name / alias 매칭(결정론 토큰 매칭).
        for e in self._entries:
            if _matches(e.stock_name, q_tokens, q_norm):
                hits.append(SourceHit(e.stock_code, e.stock_name, e.market, "name_exact", self.name))
            for alias in e.aliases:
                if _matches(alias, q_tokens, q_norm):
                    hits.append(SourceHit(e.stock_code, e.stock_name, e.market, "alias_exact", self.name))
        return hits


def _resolved(hit: SourceHit, source_hits: dict[str, int], match_types: list[str]) -> FallbackResult:
    return FallbackResult(
        status="resolved",
        stock=StockContext(stock_code=hit.stock_code, stock_name=hit.stock_name, market=hit.market),
        meta=FallbackResolveMeta(final_source=hit.source, source_hits=source_hits, match_types=match_types),
    )


def _ambiguous(hits: list[SourceHit], source_hits: dict[str, int], match_types: list[str]) -> FallbackResult:
    cands = [
        StockCandidate(stock_code=h.stock_code, stock_name=h.stock_name, market=h.market) for h in hits
    ]
    cands.sort(key=lambda c: c.stock_code)   # 결정론 순서
    return FallbackResult(
        status="ambiguous",
        candidates=cands,
        meta=FallbackResolveMeta(final_source=None, source_hits=source_hits, match_types=match_types),
    )


class CompositeFallbackLookup:
    """여러 FallbackSource 를 합쳐 판정하는 운영형 lookup(FallbackLookupProtocol).

    source 들의 hit 을 stock_code 로 dedup(가장 강한 match 유지)한 뒤:
    - code_exact 가 정확히 1개 → resolved(최우선). 2개↑ → ambiguous.
    - code_exact 없음: 서로 다른 stock_code 가 1개 → resolved, 2개↑ → ambiguous.
    - hit 없음 → not_found. 어떤 source 든 FallbackLookupError 는 그대로 전파(planner 가 not_found 로 흡수).
    """

    def __init__(self, sources: list[FallbackSource]) -> None:
        self._sources = tuple(sources)

    def lookup(self, query: str) -> FallbackResult:
        hits: list[SourceHit] = []
        for src in self._sources:
            hits.extend(src.find(query))   # FallbackLookupError 전파(도구 장애)
        # 관측용 source 별 hit 수(dedup 전 원시 집계).
        source_hits: dict[str, int] = {}
        for h in hits:
            source_hits[h.source] = source_hits.get(h.source, 0) + 1
        if not hits:
            return FallbackResult(
                status="not_found", meta=FallbackResolveMeta(source_hits=source_hits)
            )

        # stock_code 기준 dedup — 같은 종목을 여러 source/경로가 가리켜도 1개(가장 강한 match 유지).
        best: dict[str, SourceHit] = {}
        for h in hits:
            cur = best.get(h.stock_code)
            if cur is None or _MATCH_RANK[h.match] > _MATCH_RANK[cur.match]:
                best[h.stock_code] = h
        distinct = list(best.values())
        match_types = sorted({h.match for h in distinct})

        code_exacts = [h for h in distinct if h.match == "code_exact"]
        if len(code_exacts) == 1:
            return _resolved(code_exacts[0], source_hits, match_types)
        if len(code_exacts) >= 2:
            return _ambiguous(code_exacts, source_hits, match_types)
        if len(distinct) == 1:
            return _resolved(distinct[0], source_hits, match_types)
        return _ambiguous(distinct, source_hits, match_types)


# 사람이 리뷰한 curated seed — canonical(한글 정본)이 흔히 놓치는 **영문/로마자 표기** 중심(공개 사실 기반,
# AI 추정 아님). 확장은 리뷰를 거쳐 여기 추가하거나, KIS/DART 기반 source 를 CompositeFallbackLookup 에
# 추가 주입한다. persisted 는 planner 가 False 로 부여하므로 여기엔 없다(정본 아님).
CURATED_FALLBACK_ENTRIES: tuple[FallbackEntry, ...] = (
    FallbackEntry("005930", "삼성전자", "KOSPI", ("Samsung Electronics", "Samsung Elec")),
    FallbackEntry("000660", "SK하이닉스", "KOSPI", ("SK Hynix",)),
    FallbackEntry("035420", "NAVER", "KOSPI", ("Naver",)),
    FallbackEntry("035720", "카카오", "KOSPI", ("Kakao",)),
    FallbackEntry("051910", "LG화학", "KOSPI", ("LG Chem",)),
    FallbackEntry("373220", "LG에너지솔루션", "KOSPI", ("LG Energy Solution", "LGES")),
    FallbackEntry("068270", "셀트리온", "KOSPI", ("Celltrion",)),
    FallbackEntry("005380", "현대차", "KOSPI", ("Hyundai Motor",)),
    FallbackEntry("000270", "기아", "KOSPI", ("Kia Motors",)),
    FallbackEntry("005490", "POSCO홀딩스", "KOSPI", ("POSCO Holdings",)),
)


def default_fallback_lookup() -> CompositeFallbackLookup:
    """운영 기본 fallback — 정밀도순 composite: curated(고확신 소량) + DART 공시명 스냅샷(canonical 이 못 잡는
    공시 표기). 둘 다 결정론·read-only·네트워크 없음. KIS master source 는 canonical(stocks=전체 KIS ST 주권)과
    중복이 커 이번 조합에서 제외한다(필요 시 별도 source 로 추가 주입). composite 규칙(dedup/ambiguous)은 일관."""
    # 지연 import — data 스냅샷 로드는 source.find() 시점(모듈 import 시 파일 I/O·네트워크 없음).
    from src.supervisor.planning.fallback_source_dart import DartSnapshotFallbackSource

    return CompositeFallbackLookup(
        [CuratedFallbackSource(CURATED_FALLBACK_ENTRIES), DartSnapshotFallbackSource()]
    )
