# tests/test_cleanup_scheduler.py — 삭제 스케줄러 테스트(mock 기반, TASK 10)
"""run_cleanup_once(request_cleanup 트리거·예외 격리·정직 보고)와 start_cleanup_scheduler(주기 등록)를 검증.

⚠️ 실제 backend·네트워크를 부르지 않는다(CLAUDE.md: tests 는 mock). save_client.request_cleanup 과
   스케줄링 라이브러리(주입 mock scheduler)를 대체한다. 삭제 판정(168h·고아·Company 유지)은 backend 소관이라
   스케줄러가 하지 않음을 확인한다(request_cleanup 만 부른다).
"""
from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

import scheduler.cleanup_scheduler as cleanup
from scheduler.cleanup_scheduler import run_cleanup_once, start_cleanup_scheduler
from schemas.response import CleanupResponse


# ---------------------------------------------------------------------------
# run_cleanup_once — 삭제 트리거·예외 격리·정직 보고
# ---------------------------------------------------------------------------
def test_run_cleanup_once_success(monkeypatch):
    """request_cleanup 성공 → CleanupResponse(deleted_articles/events) 를 그대로 반환·로깅."""
    resp = CleanupResponse(ok=True, deleted_articles=12, deleted_events=3)
    monkeypatch.setattr(cleanup.save_client, "request_cleanup", lambda: resp)

    result = run_cleanup_once()

    assert result.ok is True
    assert result.deleted_articles == 12
    assert result.deleted_events == 3


def test_run_cleanup_once_failure_reports_ok_false(monkeypatch):
    """request_cleanup 실패(ok=False) → 그대로 반환(정직 보고). 예외로 루프를 죽이지 않는다."""
    resp = CleanupResponse(ok=False, message="backend down")
    monkeypatch.setattr(cleanup.save_client, "request_cleanup", lambda: resp)

    result = run_cleanup_once()

    assert result.ok is False
    assert "backend down" in (result.message or "")


def test_run_cleanup_once_exception_is_isolated(monkeypatch):
    """request_cleanup 이 예외를 던져도 전파 없이 ok=False 로 통과(스케줄러 루프 보호)."""
    def _boom():
        raise RuntimeError("connection reset")

    monkeypatch.setattr(cleanup.save_client, "request_cleanup", _boom)

    result = run_cleanup_once()  # 예외가 밖으로 나오면 이 라인에서 테스트가 깨진다.

    assert result.ok is False
    assert "connection reset" in (result.message or "")


def test_run_cleanup_once_calls_request_cleanup_only(monkeypatch):
    """삭제 조건(168h·고아·Company 유지)을 스케줄러가 판정하지 않는다 — request_cleanup 만 1회 호출."""
    calls = {"n": 0}

    def _spy():
        calls["n"] += 1
        return CleanupResponse(ok=True)

    monkeypatch.setattr(cleanup.save_client, "request_cleanup", _spy)

    run_cleanup_once()

    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# start_cleanup_scheduler — 주기 등록·겹침 방지
# ---------------------------------------------------------------------------
def test_start_cleanup_scheduler_registers_interval_job(monkeypatch):
    """CLEANUP_INTERVAL_MINUTES·timezone·max_instances·misfire 유예가 add_job 에 그대로 전달되는지."""
    monkeypatch.setattr(cleanup, "CLEANUP_INTERVAL_MINUTES", 60)
    monkeypatch.setattr(cleanup, "CLEANUP_MAX_INSTANCES", 1)
    monkeypatch.setattr(cleanup, "CLEANUP_MISFIRE_GRACE_SEC", 300)
    monkeypatch.setattr(cleanup, "SCHEDULER_TIMEZONE", "Asia/Seoul")
    monkeypatch.setattr(cleanup, "SCHEDULER_JITTER_SEC", 0)

    fake = MagicMock()
    returned = start_cleanup_scheduler(scheduler=fake)

    assert returned is fake
    fake.add_job.assert_called_once()
    args, kwargs = fake.add_job.call_args
    assert args[0] is run_cleanup_once
    assert kwargs["trigger"] == "interval"
    assert kwargs["minutes"] == 60
    assert kwargs["max_instances"] == 1
    assert kwargs["misfire_grace_time"] == 300
    assert kwargs["coalesce"] is True
    assert kwargs["timezone"] == "Asia/Seoul"
    fake.start.assert_called_once()


# ---------------------------------------------------------------------------
# DB 미접근·삭제 로직 부재(정적 검사 — import 문만 파싱)
# ---------------------------------------------------------------------------
def _import_lines(module) -> list[str]:
    """import 문만 추출(주석·docstring 의 'Cypher'·'168h' 언급을 오탐하지 않도록)."""
    src = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    return [ln for ln in src.splitlines() if ln.lstrip().startswith(("import ", "from "))]


def test_cleanup_scheduler_has_no_db_or_http_imports():
    """삭제 SQL/Cypher·DB 드라이버·HTTP 라이브러리 import 가 없다(전부 backend, 절대규칙 1)."""
    imports = " ".join(_import_lines(cleanup)).lower()
    for mod in ("httpx", "psycopg", "sqlalchemy", "neo4j", "pymysql", "asyncpg"):
        assert mod not in imports, f"금지된 DB/HTTP 라이브러리 import: {mod}"


def test_cleanup_scheduler_deletes_via_request_cleanup_only():
    """삭제 경로는 save_client(request_cleanup)뿐이다 — 그 외 backend 조회/저장을 import 하지 않는다."""
    src = pathlib.Path(cleanup.__file__).read_text(encoding="utf-8")
    # 삭제 판정 조건 문자열(168h 비교식·DELETE 실행)이 코드에 없다 — 주석 언급은 허용, 실행문은 금지.
    code_lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    code = "\n".join(code_lines).lower()
    for token in ("delete from", "detach delete", "now() - interval"):
        assert token not in code, f"삭제 실행문이 스케줄러에 있음: {token}"


def test_cleanup_scheduling_library_import_is_isolated():
    """APScheduler import 는 함수 안(들여쓰기)에만 있어야 한다(§2)."""
    for line in _import_lines(cleanup):
        if "apscheduler" in line.lower():
            assert line[:1].isspace(), f"top-level 에서 스케줄링 라이브러리 import: {line!r}"
