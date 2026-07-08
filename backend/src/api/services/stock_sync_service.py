"""KIS 종목마스터 → stocks 동기화 (단일 트랜잭션).

정책: 신규 INSERT / 이름·시장 실제 변경 시 UPDATE / **누락 종목 삭제·비활성화 안 함**.
두 시장(KOSPI/KOSDAQ) 모두 fetch·파싱·검증이 끝난 뒤 한 트랜잭션으로 반영한다. commit 여부는
호출자(script)가 결정한다(기본 dry-run, --apply 에서만 commit). AI 패키지 import 없음.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.common.stock import Stock
from src.api.constants.kis_master import MARKET_KOSDAQ, MARKET_KOSPI
from src.api.services.stock_master_parser import parse_master

# 보수적 하한(fail-fast 안전장치) — 실제 규모(대략 KOSPI 2,5xx / KOSDAQ 1,8xx)보다 훨씬 낮게 두어
# 손상·빈 응답만 잡는다. 정확한 하한은 실데이터 dry-run 검산 후 확정한다(코드에 실수 고정 금지).
_DEFAULT_MIN = {MARKET_KOSPI: 500, MARKET_KOSDAQ: 500}


class StockSyncError(RuntimeError):
    """검증 실패(빈 시장·하한 미만·시장 간 코드 중복 등) — 부분 반영 대신 중단."""


@dataclass
class SyncSummary:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: int = 0                       # 마스터에 없지만 DB에 남는 종목(삭제 안 함)
    total_desired: int = 0
    excluded: dict[str, dict[str, int]] = field(default_factory=dict)  # market -> 제외 사유별 count
    per_market: dict[str, int] = field(default_factory=dict)           # market -> 포함 종목수


async def sync_stocks(
    session: AsyncSession,
    *,
    fetch_mst: Callable[[str], bytes],
    min_counts: dict[str, int] | None = None,
) -> SyncSummary:
    """fetch_mst(market)->raw .mst bytes 로 두 시장을 받아 stocks 를 동기화. commit 은 호출자."""
    mins = min_counts or _DEFAULT_MIN

    # 1) 두 시장 fetch + parse (검증 전 apply 금지).
    parsed = {m: parse_master(fetch_mst(m), m) for m in (MARKET_KOSPI, MARKET_KOSDAQ)}

    # 2) 검증(fail-fast). 빈 시장/하한 미만/시장 간 코드 중복.
    seen: dict[str, str] = {}
    for market, pr in parsed.items():
        if not pr.records:
            raise StockSyncError(f"{market} 파싱 결과 0건 — 중단")
        if len(pr.records) < mins.get(market, 0):
            raise StockSyncError(f"{market} 종목수 {len(pr.records)} < 하한 {mins.get(market)} — 중단")
        for r in pr.records:
            if r.stock_code in seen and seen[r.stock_code] != market:
                raise StockSyncError(f"시장 간 stock_code 중복: {r.stock_code} — 중단")
            seen[r.stock_code] = market

    desired = {r.stock_code: r for pr in parsed.values() for r in pr.records}

    # 3) 단일 트랜잭션 반영(삭제 없음). commit 은 호출자.
    existing = {s.stock_code: s for s in (await session.execute(select(Stock))).scalars()}
    summary = SyncSummary(
        total_desired=len(desired),
        excluded={m: pr.excluded for m, pr in parsed.items()},
        per_market={m: len(pr.records) for m, pr in parsed.items()},
    )
    now = datetime.now(UTC)
    for code, rec in desired.items():
        cur = existing.get(code)
        if cur is None:
            session.add(Stock(stock_code=code, stock_name=rec.stock_name, market=rec.market))
            summary.inserted += 1
        elif cur.stock_name != rec.stock_name or cur.market != rec.market:
            cur.stock_name = rec.stock_name
            cur.market = rec.market
            cur.updated_at = now            # 실제 변경 시에만 갱신
            summary.updated += 1
        else:
            summary.unchanged += 1

    summary.missing = sum(1 for code in existing if code not in desired)  # 삭제하지 않음(가시성만)
    await session.flush()
    return summary
