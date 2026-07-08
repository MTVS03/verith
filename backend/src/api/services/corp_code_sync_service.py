"""DART corpCode.xml → stock_corp_codes 동기화 (단일 트랜잭션).

정책: 신규 INSERT / (corp_code·corp_name_from_dart·modify_date) 실제 변경 시 UPDATE /
**누락 행 삭제·비활성화 안 함**. commit 여부는 호출자(script)가 결정한다(기본 dry-run,
--apply 에서만 commit). AI 패키지 import 없음. KIS `stocks` 는 건드리지 않는다(별도 계층).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.common.stock_corp_code import StockCorpCode
from src.api.services.dart_corp_code_parser import parse_corp_code

# 보수적 하한(fail-fast 안전장치) — 실제 상장 규모(대략 2,8xx)보다 훨씬 낮게 두어 손상·빈 응답만
# 잡는다. 정확한 하한은 실데이터 dry-run 검산 후 확정한다(코드에 실수 고정 금지).
_DEFAULT_MIN = 500


class CorpCodeSyncError(RuntimeError):
    """검증 실패(상장 record 0건·하한 미만 등) — 부분 반영 대신 중단."""


@dataclass
class CorpCodeSyncSummary:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: int = 0             # DART 에 없지만 DB에 남는 매핑(삭제 안 함)
    total_desired: int = 0       # DART 상장 record 수
    non_listed: int = 0          # 빈 stock_code(제외)
    invalid_modify_date: int = 0  # modify_date 형식 이상(NULL 처리)


async def sync_corp_codes(
    session: AsyncSession,
    *,
    fetch_corp_code: Callable[[], bytes],
    min_count: int = _DEFAULT_MIN,
) -> CorpCodeSyncSummary:
    """fetch_corp_code()->CORPCODE.xml bytes 로 stock_corp_codes 를 동기화. commit 은 호출자."""
    # 1) fetch + parse (검증 전 apply 금지). 파서가 중복/결측 이상치를 fail-fast.
    parsed = parse_corp_code(fetch_corp_code())

    # 2) 검증(fail-fast). 빈 결과/하한 미만.
    if not parsed.records:
        raise CorpCodeSyncError("상장 record 0건 — 중단")
    if len(parsed.records) < min_count:
        raise CorpCodeSyncError(f"상장 record {len(parsed.records)} < 하한 {min_count} — 중단")

    desired = {r.stock_code: r for r in parsed.records}

    # 3) 단일 트랜잭션 반영(삭제 없음). commit 은 호출자.
    existing = {
        s.stock_code: s for s in (await session.execute(select(StockCorpCode))).scalars()
    }
    summary = CorpCodeSyncSummary(
        total_desired=len(desired),
        non_listed=parsed.non_listed,
        invalid_modify_date=parsed.invalid_modify_date,
    )
    now = datetime.now(UTC)
    for code, rec in desired.items():
        cur = existing.get(code)
        if cur is None:
            session.add(
                StockCorpCode(
                    stock_code=code,
                    corp_code=rec.corp_code,
                    corp_name_from_dart=rec.corp_name_from_dart,
                    modify_date=rec.modify_date,
                )
            )
            summary.inserted += 1
        elif (
            cur.corp_code != rec.corp_code
            or cur.corp_name_from_dart != rec.corp_name_from_dart
            or cur.modify_date != rec.modify_date
        ):
            cur.corp_code = rec.corp_code
            cur.corp_name_from_dart = rec.corp_name_from_dart
            cur.modify_date = rec.modify_date
            cur.updated_at = now          # 실제 변경 시에만 갱신
            summary.updated += 1
        else:
            summary.unchanged += 1

    summary.missing = sum(1 for code in existing if code not in desired)  # 삭제 안 함(가시성만)
    await session.flush()
    return summary
