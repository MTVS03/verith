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
from src.api.constants.kis_master import MARKET_KOSDAQ, MARKET_KOSPI  # noqa: E402
from src.api.services.stock_master_parser import inspect_rows  # noqa: E402
from src.api.services.stock_sync_service import sync_stocks  # noqa: E402

# 검산용 앵커(시장별): 포함(주권) 예시. 제외 예시는 --inspect 가 실데이터에서 자동 스캔한다.
_ANCHORS: dict[str, dict[str, str]] = {
    MARKET_KOSPI: {
        "005930": "삼성전자 (주권 ST, 포함)",
        "005935": "삼성전자우 (주권 ST·우선주, 포함)",
        "069500": "KODEX200 (ETF, 제외 기대)",
        "293940": "신한알파리츠 (REIT, 제외 기대)",
    },
    MARKET_KOSDAQ: {
        "086520": "에코프로 (주권 ST, 포함)",
        "247540": "에코프로비엠 (주권 ST, 포함)",
    },
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
    print("⚠️ KIS 마스터 다운로드(외부 네트워크) — 검산만, DB 미변경. "
          "값 semantics(ST/플래그)는 이 출력으로 확정한다.")
    client = KisMasterClient()
    for market in (MARKET_KOSPI, MARKET_KOSDAQ):
        text = client.fetch_mst(market).decode("cp949")
        anchors = _ANCHORS[market]
        rows = inspect_rows(text, market, anchors.keys())
        print(f"[{market}] (앵커 + 제외 자동 스캔)")
        for rec in rows:
            desc = anchors.get(rec["code"], "그룹≠ST 자동 검출(제외 대상)")
            print(f"  {rec['code']} {rec['name']:14} group={rec['group']!r} spac={rec['spac']!r} "
                  f"etp={rec['etp']!r} pref={rec['pref']!r}  ← {desc}")


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
