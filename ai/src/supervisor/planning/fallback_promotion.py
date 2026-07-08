"""fallback 승격(promotion) 후보 모델 + 집계 — **오프라인** 관리용(질문 처리 경로 아님).

목적: 질문 중 fallback 으로 반복 resolve 되는 표현을, 나중에 사람이 검토해 canonical(stocks/stock_aliases)로
**승인 후** 올릴 수 있도록 후보를 집계한다. 이 모듈은 **canonical 을 절대 write 하지 않는다** — 후보 관측·
제안까지만(collect → review → approve → apply 중 collect 단계). 실시간 자동 승격 없음.

경계:
- 후보화 대상은 **fallback resolved(단일 종목)** 뿐. ambiguous/not_found 는 후보가 아니다(자동선택 금지 원칙).
- raw query 전문은 담지 않는다 — `normalized_query`(정책상 허용)만. 예시도 normalized 기준.
- 대부분은 **alias_addition**(canonical stocks 에 종목은 있고 표현만 없음 — universe=2,607 전체 주권). 종목
  자체 부재(stock_addition)는 canonical 재확인이 필요하다(hint 만 기록, 최종 판정은 사람).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Iterable, Literal

CandidateType = Literal["alias_addition", "stock_addition"]
PromotionStatus = Literal["pending", "approved", "rejected"]

# 짧은 표현은 오탐 위험 — 후보에서 제외하는 하한(정규화 길이).
_MIN_NORM_LEN = 3
# 후보로 인정하는 fallback source(관측된 final_source).
_KNOWN_SOURCES = frozenset({"curated", "dart"})


@dataclass(frozen=True)
class PromotionInput:
    """한 번의 fallback resolved 관측(capture 1줄). request 경로 밖에서 수집된다.

    raw query 는 담지 않는다 — normalized_query 만. seen_at 은 capture 시각(ISO8601 문자열, 주입식)."""

    normalized_query: str
    stock_code: str
    final_source: str
    seen_at: str
    stock_name: str | None = None
    market: str | None = None
    match_types: tuple[str, ...] = ()
    final_status: str = "resolved"


@dataclass
class PromotionCandidate:
    """승격 검토 후보(집계 결과). promotion_status 는 사람이 편집(pending→approved/rejected)."""

    normalized_query: str
    stock_code: str
    stock_name: str | None
    market: str | None
    final_source: str                 # 대표 source(dart 우선), 여러 source 면 관측된 것 중 하나
    sources: list[str]                # 관측된 모든 source
    match_types: list[str]
    observed_count: int
    first_seen_at: str
    last_seen_at: str
    candidate_type: CandidateType
    needs_canonical_check: bool        # True 면 stock_addition 가능성 — 사람이 canonical 확인 필요
    ephemeral_reason: str = "persisted=false (source=fallback_lookup)"
    observed_query_example: str = ""   # normalized 기준 예시(raw 아님)
    promotion_status: PromotionStatus = "pending"


def is_candidate(rec: PromotionInput) -> bool:
    """후보 인정 여부 — fallback resolved · 단일 stock_code · 알려진 source · 정규화 길이 충족만."""
    return (
        rec.final_status == "resolved"
        and bool(rec.stock_code)
        and len(rec.normalized_query) >= _MIN_NORM_LEN
        and rec.final_source in _KNOWN_SOURCES
    )


def classify(final_source: str) -> tuple[CandidateType, bool]:
    """(candidate_type, needs_canonical_check).

    - dart: 스냅샷이 stocks JOIN 산물이라 종목 존재가 확정 → alias_addition, canonical 재확인 불필요.
    - 그 외(curated 등): 대개 실존 종목(alias_addition)이지만 canonical 미존재면 stock_addition →
      재확인 플래그. 최종 분류는 사람 리뷰."""
    if final_source == "dart":
        return "alias_addition", False
    return "alias_addition", True


def aggregate(records: Iterable[PromotionInput]) -> list[PromotionCandidate]:
    """capture 레코드들을 (normalized_query, stock_code) 로 dedup·집계해 후보 목록을 만든다(결정론 정렬).

    canonical write 없음 — 순수 집계. 후보 아닌 레코드는 건너뛴다."""
    groups: dict[tuple[str, str], list[PromotionInput]] = defaultdict(list)
    for rec in records:
        if is_candidate(rec):
            groups[(rec.normalized_query, rec.stock_code)].append(rec)

    out: list[PromotionCandidate] = []
    for (norm_q, code), recs in groups.items():
        sources = sorted({r.final_source for r in recs})
        match_types = sorted({m for r in recs for m in r.match_types})
        seens = sorted(r.seen_at for r in recs)
        # dart 가 있으면 대표 source 로(canonical 존재 확정 쪽 우선).
        rep_source = "dart" if "dart" in sources else sources[0]
        cand_type, needs_check = classify(rep_source)
        name = next((r.stock_name for r in recs if r.stock_name), None)
        market = next((r.market for r in recs if r.market), None)
        out.append(
            PromotionCandidate(
                normalized_query=norm_q,
                stock_code=code,
                stock_name=name,
                market=market,
                final_source=rep_source,
                sources=sources,
                match_types=match_types,
                observed_count=len(recs),
                first_seen_at=seens[0],
                last_seen_at=seens[-1],
                candidate_type=cand_type,
                needs_canonical_check=needs_check,
                observed_query_example=norm_q,
                promotion_status="pending",
            )
        )
    # 결정론 정렬: 관측 많은 순 → stock_code → query.
    out.sort(key=lambda c: (-c.observed_count, c.stock_code, c.normalized_query))
    return out


def candidate_to_dict(c: PromotionCandidate) -> dict:
    """JSONL 직렬화용 dict."""
    return asdict(c)
