"""PostgreSQL 뉴스 테이블(news, news_reports) → 재현 가능한 .sql 스냅샷 export.

팀 컨벤션(backend/dumps/): git 이 나르는 건 볼륨이 아니라 재현 가능한 data artifact.
맨 앞 TRUNCATE 로 복원 시 스냅샷 상태로 리셋된다(COPY + setval 이 데이터·시퀀스 복구).

**기본은 embedding 제외** — embedding(pgvector)은 파일을 수십 MB 로 부풀리고 **배치의 이벤트 병합에만**
쓰인다(조회·리포트는 안 읽음). 완전 보존이 필요하면 --include-embedding.

도커 출력을 **바이트 그대로** 파일에 쓴다(shell 미경유 → PowerShell/cmd 인코딩·따옴표 문제 없음).

사용:
    python -m scripts.export_news_pg [out.sql] [--include-embedding]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CONTAINER = "verith-postgres"
DB_USER = "verith"
DB_NAME = "verith"

# embedding 제외 시 명시적으로 뜨는 news 컬럼(순서 = 복원 COPY 헤더와 일치해야 함).
NEWS_COLS_NO_EMBEDDING = [
    "id", "title", "content", "summary", "url", "publisher",
    "sentiment", "sentiment_score", "published_at", "event_id", "created_at",
]


def _psql(sql: str) -> bytes:
    """psql -c 로 SQL/메타명령 1개 실행, stdout 바이트 반환(shell 미경유)."""
    return subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME, "-c", sql],
        check=True, stdout=subprocess.PIPE,
    ).stdout


def _psql_scalar(sql: str) -> str:
    """단일 스칼라 값을 문자열로."""
    out = subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME, "-tA", "-c", sql],
        check=True, stdout=subprocess.PIPE,
    ).stdout
    return out.decode("utf-8").strip()


def _pg_dump_table(table: str) -> bytes:
    """pg_dump --data-only 로 테이블 하나(데이터+setval) 뜨기, 바이트 반환."""
    return subprocess.run(
        ["docker", "exec", CONTAINER, "pg_dump", "-U", DB_USER, "-d", DB_NAME,
         "--data-only", f"--table={table}"],
        check=True, stdout=subprocess.PIPE,
    ).stdout


def export(out_path: Path, include_embedding: bool) -> int:
    """news + news_reports 를 out_path(.sql)에 쓴다. news 행수 반환."""
    with out_path.open("wb") as f:
        header = "TRUNCATE public.news, public.news_reports RESTART IDENTITY CASCADE;\n\n"
        f.write(header.encode("utf-8"))

        if include_embedding:
            # 전체 컬럼(embedding 포함) — pg_dump 가 COPY + setval 을 모두 처리.
            f.write(_pg_dump_table("news"))
        else:
            # embedding 제외 — 명시적 컬럼 COPY 로 직접 구성.
            cols = ", ".join(NEWS_COLS_NO_EMBEDDING)
            f.write(f"COPY public.news ({cols}) FROM stdin;\n".encode("utf-8"))
            f.write(_psql(f"\\copy (SELECT {cols} FROM news ORDER BY id) TO STDOUT"))
            f.write(b"\\.\n")
            # 시퀀스 복구(pg_dump 대신 직접). 시퀀스명은 DB 에서 조회.
            seq = _psql_scalar("SELECT pg_get_serial_sequence('news','id')")
            maxid = _psql_scalar("SELECT COALESCE(MAX(id),1) FROM news")
            f.write(f"SELECT pg_catalog.setval('{seq}', {maxid}, true);\n".encode("utf-8"))

        f.write(b"\n")
        # news_reports 는 embedding 없음 — 항상 pg_dump 로.
        f.write(_pg_dump_table("news_reports"))

    return int(_psql_scalar("SELECT count(*) FROM news"))


def main() -> None:
    include_embedding = "--include-embedding" in sys.argv
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    default_out = Path(__file__).resolve().parent.parent / "dumps" / "shared_news_pg.sql"
    out_path = Path(positional[0]) if positional else default_out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"PG export ({'with' if include_embedding else 'no'} embedding): -> {out_path}")
    rows = export(out_path, include_embedding)
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"  news rows={rows}  size={size_mb:.1f}MB")


if __name__ == "__main__":
    main()
