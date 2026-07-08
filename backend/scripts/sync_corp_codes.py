"""DART corpCode.xml → stock_corp_codes 동기화 (수동 실행 전용).

기본은 **dry-run**(다운로드·파싱·검증·diff 출력, **DB 미변경**). `--apply` 일 때만 commit.
`--inspect` 는 파싱 요약과 샘플 행을 출력해 **실데이터를 검산**(DB 미변경).

⚠️ 이 스크립트는 **외부 네트워크(DART)** 를 호출한다. 앱 startup·pytest 에서 실행하지 않는다.
`DART_API_KEY`(.env) 가 필요하다 — sync 전용 값이며 startup 필수값이 아니다.

실행:
    cd backend
    uv run python -m scripts.sync_corp_codes             # dry-run (DB 미변경)
    uv run python -m scripts.sync_corp_codes --inspect    # 파싱 요약·샘플 검산 (DB 미변경)
    uv run python -m scripts.sync_corp_codes --apply       # 실제 반영 (commit)
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys

_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from src.api.clients.dart_corp_code_client import DartCorpCodeClient  # noqa: E402
from src.api.services.corp_code_sync_service import sync_corp_codes  # noqa: E402
from src.api.services.dart_corp_code_parser import parse_corp_code  # noqa: E402

_INSPECT_SAMPLE = 5


def _print_summary(summary) -> None:
    print(f"[sync_corp_codes] desired(listed)={summary.total_desired} "
          f"inserted={summary.inserted} updated={summary.updated} "
          f"unchanged={summary.unchanged} missing(keep)={summary.missing}")
    print(f"  non_listed(제외)={summary.non_listed} "
          f"invalid_modify_date(NULL)={summary.invalid_modify_date}")


async def _run(apply: bool) -> None:
    from db.session import async_session_factory, engine  # noqa: E402 (지연 import — config 로드)

    print("⚠️ DART corpCode.xml 다운로드(외부 네트워크) 시작. "
          + ("--apply: DB에 반영합니다." if apply else "dry-run: DB를 변경하지 않습니다."))
    client = DartCorpCodeClient()
    async with async_session_factory() as session:
        summary = await sync_corp_codes(session, fetch_corp_code=client.fetch_corp_code)
        if apply:
            await session.commit()
            print("APPLIED (committed).")
        else:
            await session.rollback()
            print("DRY-RUN (no DB change).")
    await engine.dispose()
    _print_summary(summary)


def _inspect() -> None:
    print("⚠️ DART corpCode.xml 다운로드(외부 네트워크) — 검산만, DB 미변경.")
    client = DartCorpCodeClient()
    parsed = parse_corp_code(client.fetch_corp_code())
    print(f"[inspect] listed={len(parsed.records)} non_listed={parsed.non_listed} "
          f"invalid_modify_date={parsed.invalid_modify_date}")
    for rec in parsed.records[:_INSPECT_SAMPLE]:
        print(f"  {rec.stock_code} corp_code={rec.corp_code} "
              f"modify_date={rec.modify_date!r} name={rec.corp_name_from_dart}")


def main() -> None:
    ap = argparse.ArgumentParser(description="DART corpCode.xml → stock_corp_codes 동기화")
    ap.add_argument("--apply", action="store_true", help="실제 DB 반영(commit). 없으면 dry-run.")
    ap.add_argument("--inspect", action="store_true", help="파싱 요약·샘플 검산(DB 미변경).")
    args = ap.parse_args()
    if args.inspect:
        _inspect()
    else:
        asyncio.run(_run(args.apply))


if __name__ == "__main__":
    main()
