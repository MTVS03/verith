"""PostgreSQL 산업 테이블(industry_reports + 스코프된 agent_reports) → .sql 스냅샷 export.

팀 컨벤션(backend/dumps/): git 이 나르는 건 볼륨이 아니라 재현 가능한 data artifact.

⚠ **`agent_reports` 는 전 에이전트 공용 인덱스 테이블**이다(technical/fundamental/news/flow/
industry). 뉴스 스냅샷처럼 `TRUNCATE` 하면 남의 인덱스 행까지 날아간다. 그래서 헤더는
`DELETE ... WHERE agent_type = 'industry'` 로만 스코프 리셋하고, 행도 `pg_dump` 가 아니라
WHERE 를 걸 수 있는 `\\copy` 로 뜬다.

`industry_reports` 는 산업 전용이라 `TRUNCATE` 해도 된다. 참조하는 FK 가 없으므로
(`agent_reports.agent_report_id` 는 app-level reference — schema.md §참고) `CASCADE` 는 쓰지 않는다.
두 테이블 다 uuid PK(`gen_random_uuid()`)라 시퀀스/`setval` 이 없다(뉴스 `news.id` 와 다른 점).

도커 출력을 **바이트 그대로** 파일에 쓴다(shell 미경유 → PowerShell/cmd 인코딩·따옴표 문제 없음).

사용:
    python -m scripts.export_industry_pg [out.sql]
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.export_news_pg import _pg_dump_table, _psql, _psql_scalar

AGENT_TYPE = "industry"

# agent_reports 의 전체 컬럼(순서 = 복원 COPY 헤더와 일치해야 함). db/models/common/agent_report.py.
AGENT_REPORT_COLS = [
    "id", "agent_type", "agent_report_id", "request_id", "client_session_id",
    "owner_user_id", "owner_session_id", "stock_code", "stock_name",
    "question", "answer_text", "data_status", "trace_id", "as_of", "created_at", "summary",
]


def export(out_path: Path) -> tuple[int, int]:
    """industry_reports + agent_reports(industry) 를 out_path 에 쓴다. (리포트수, 인덱스행수) 반환."""
    with out_path.open("wb") as f:
        header = (
            f"-- 산업 스냅샷: agent_reports 는 공용 테이블이라 스코프 DELETE 만 한다.\n"
            f"DELETE FROM public.agent_reports WHERE agent_type = '{AGENT_TYPE}';\n"
            f"TRUNCATE public.industry_reports;\n\n"
        )
        f.write(header.encode("utf-8"))

        # industry_reports 는 산업 전용 → pg_dump 가 COPY 를 통째로 처리.
        f.write(_pg_dump_table("industry_reports"))

        f.write(b"\n")
        # pg_dump preamble 이 search_path 를 '' 로 바꾼다 → 이후 객체는 반드시 public. 한정.
        cols = ", ".join(AGENT_REPORT_COLS)
        f.write(f"COPY public.agent_reports ({cols}) FROM stdin;\n".encode("utf-8"))
        f.write(_psql(
            f"\\copy (SELECT {cols} FROM agent_reports "
            f"WHERE agent_type = '{AGENT_TYPE}' ORDER BY created_at) TO STDOUT"
        ))
        f.write(b"\\.\n")

    reports = int(_psql_scalar("SELECT count(*) FROM industry_reports"))
    index_rows = int(_psql_scalar(
        f"SELECT count(*) FROM agent_reports WHERE agent_type = '{AGENT_TYPE}'"
    ))
    return reports, index_rows


def main() -> None:
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    default_out = Path(__file__).resolve().parent.parent / "dumps" / "shared_industry_pg.sql"
    out_path = Path(positional[0]) if positional else default_out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"PG 산업 export: -> {out_path}")
    reports, index_rows = export(out_path)
    size_kb = out_path.stat().st_size / 1024
    print(f"  industry_reports={reports}  agent_reports(industry)={index_rows}  size={size_kb:.0f}KB")


if __name__ == "__main__":
    main()
