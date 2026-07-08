"""KIS 종목마스터 → stocks 동기화 (수동 실행 전용).

기본은 **dry-run**(다운로드·파싱·검증·diff 출력, **DB 미변경**). `--apply` 일 때만 commit.
`--inspect` 는 앵커 종목의 tail 필드를 출력해 **offset/코드값을 실데이터로 검산**(DB 미변경).

⚠️ 이 스크립트는 **외부 네트워크(KIS)** 를 호출한다. 앱 startup·pytest 에서 실행하지 않는다.

실행:
    cd backend
    uv run python -m scripts.sync_stocks               # dry-run (DB 미변경)
    uv run python -m scripts.sync_stocks --inspect      # 앵커 검산 (DB 미변경)
    uv run python -m scripts.sync_stocks --apply         # 실제 반영 (commit)
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys

_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from src.api.clients.kis_master_client import KisMasterClient  # noqa: E402
from src.api.constants.kis_master import (  # noqa: E402
    FRONT_CODE,
    FRONT_NAME_START,
    KOSDAQ_FIELDS,
    KOSDAQ_TAIL,
    KOSPI_FIELDS,
    KOSPI_TAIL,
    MARKET_KOSDAQ,
    MARKET_KOSPI,
)
from src.api.services.stock_sync_service import sync_stocks  # noqa: E402

# 검산용 앵커: (code → 기대 성격). 실행 시 실제 tail 필드로 offset/코드값 확인.
_ANCHORS = {
    "005930": "삼성전자 (주권 ST, 포함)",
    "005935": "삼성전자우 (주권 ST·우선주, 포함)",
    "069500": "KODEX200 (ETF, 제외)",
    "293940": "신한알파리츠 (REIT, 제외)",
}


def _print_summary(summary) -> None:
    print(f"[sync_stocks] desired={summary.total_desired} "
          f"inserted={summary.inserted} updated={summary.updated} "
          f"unchanged={summary.unchanged} missing(keep)={summary.missing}")
    for market, cnt in summary.per_market.items():
        print(f"  {market}: 포함 {cnt} / 제외 {summary.excluded.get(market)}")


async def _run(apply: bool) -> None:
    from db.session import async_session_factory, engine  # noqa: E402 (지연 import — config 로드)

    print("⚠️ KIS 마스터 다운로드(외부 네트워크) 시작. "
          + ("--apply: DB에 반영합니다." if apply else "dry-run: DB를 변경하지 않습니다."))
    client = KisMasterClient()
    async with async_session_factory() as session:
        summary = await sync_stocks(session, fetch_mst=client.fetch_mst)
        if apply:
            await session.commit()
            print("APPLIED (committed).")
        else:
            await session.rollback()
            print("DRY-RUN (no DB change).")
    await engine.dispose()
    _print_summary(summary)


def _inspect() -> None:
    print("⚠️ KIS 마스터 다운로드(외부 네트워크) — 검산만, DB 미변경.")
    client = KisMasterClient()
    for market in (MARKET_KOSPI, MARKET_KOSDAQ):
        tail_len, fields = (
            (KOSPI_TAIL, KOSPI_FIELDS) if market == MARKET_KOSPI else (KOSDAQ_TAIL, KOSDAQ_FIELDS)
        )
        text = client.fetch_mst(market).decode("cp949")
        rows = {r[FRONT_CODE[0]:FRONT_CODE[1]].strip(): r for r in text.splitlines() if len(r) > tail_len}
        print(f"[{market}]")
        for code, desc in _ANCHORS.items():
            row = rows.get(code)
            if row is None:
                continue
            tail = row[-tail_len:]
            name = row[: len(row) - tail_len][FRONT_NAME_START:].strip()
            vals = {k: tail[o:o + w] for k, (o, w) in fields.items()}
            print(f"  {code} {name:12} group={vals['group']!r} spac={vals['spac']!r} "
                  f"etp={vals['etp']!r} pref={vals['pref']!r}  ← {desc}")


def main() -> None:
    ap = argparse.ArgumentParser(description="KIS 종목마스터 → stocks 동기화")
    ap.add_argument("--apply", action="store_true", help="실제 DB 반영(commit). 없으면 dry-run.")
    ap.add_argument("--inspect", action="store_true", help="앵커 tail 필드 검산(DB 미변경).")
    args = ap.parse_args()
    if args.inspect:
        _inspect()
    else:
        asyncio.run(_run(args.apply))


if __name__ == "__main__":
    main()
