# tests/test_rss_scheduler.py — 배치 스케줄러 테스트(mock 기반, TASK 10)
"""run_batch_once(배치 한 pass invoke·예외 격리·정직 보고)와 start_rss_scheduler(주기 등록·겹침 방지)를 검증.

⚠️ 실제 네트워크·backend·모델·실시간 대기를 부르지 않는다(CLAUDE.md: tests 는 mock). 배치 파이프라인
   (invoke 대상 `_run_batch_pipeline`)과 스케줄링 라이브러리(주입 mock scheduler)를 대체해 고정 결과/예외를
   돌려준다. 시간은 가짜 시계 대신 트리거 등록 계약(add_job kwargs)만 확인한다.
검증 축(§7):
- run_batch_once: 성공 state→ok/saved, 파이프라인 예외→예외 전파 없이 ok=False, 저장 ok=False→ok=False,
  수집 0건→통과, 파이프라인을 invoke만(backend·모델 직접 호출 없음).
- start_rss_scheduler: interval·timezone·max_instances=1·misfire 유예가 그대로 전달, RUN_ON_START 시 1회 실행.
- DB 미접근·로직 미복제: 파일에 SQL·Cypher·DB 드라이버·HTTP 라이브러리 import 없음, 스케줄링 라이브러리는 lazy.
"""
from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

import scheduler.rss_scheduler as rss
from scheduler.rss_scheduler import BatchRunResult, run_batch_once, start_rss_scheduler
from schemas.response import SaveResponse


# ---------------------------------------------------------------------------
# run_batch_once — 배치 한 pass invoke·예외 격리·정직 보고
# ---------------------------------------------------------------------------
def test_run_batch_once_success(monkeypatch):
    """파이프라인이 성공 state(저장 ok=True, saved=n) → BatchRunResult(ok=True, collected=n, saved=n)."""
    state = {
        "articles": [object(), object(), object()],
        "save_result": SaveResponse(ok=True, saved=3),
    }
    monkeypatch.setattr(rss, "_run_batch_pipeline", lambda: state)

    result = run_batch_once()

    assert isinstance(result, BatchRunResult)
    assert result.ok is True
    assert result.collected == 3
    assert result.saved == 3


def test_run_batch_once_pipeline_exception_is_isolated(monkeypatch):
    """파이프라인 한 단계가 예외 → 예외 전파 없이 ok=False + 사유(스케줄러 루프 보호, 성공 위장 금지)."""
    def _boom():
        raise RuntimeError("extract 실패")

    monkeypatch.setattr(rss, "_run_batch_pipeline", _boom)

    result = run_batch_once()  # 예외가 밖으로 나오면 이 라인에서 테스트가 깨진다.

    assert result.ok is False
    assert result.saved == 0
    assert "extract 실패" in (result.message or "")


def test_run_batch_once_save_failure_reports_ok_false(monkeypatch):
    """저장 실패(SaveResponse.ok=False) → 결과도 ok=False(정직 보고). 성공으로 위장하지 않는다."""
    state = {
        "articles": [object()],
        "save_result": SaveResponse(ok=False, saved=0, message="backend 5xx"),
    }
    monkeypatch.setattr(rss, "_run_batch_pipeline", lambda: state)

    result = run_batch_once()

    assert result.ok is False
    assert result.collected == 1
    assert "backend 5xx" in (result.message or "")


def test_run_batch_once_zero_collected_passes(monkeypatch):
    """수집 0건(articles 없음·save_result 없음) → 예외 없이 통과(ok=True, 환각 금지)."""
    monkeypatch.setattr(rss, "_run_batch_pipeline", lambda: {"articles": []})

    result = run_batch_once()

    assert result.ok is True
    assert result.collected == 0
    assert result.saved == 0


def test_run_batch_once_collected_but_no_save_result_is_failure(monkeypatch):
    """수집은 됐는데 저장 결과가 없다 = 파이프라인이 저장까지 못 감 → ok=False(성공 위장 금지)."""
    monkeypatch.setattr(rss, "_run_batch_pipeline", lambda: {"articles": [object(), object()]})

    result = run_batch_once()

    assert result.ok is False
    assert result.collected == 2


def test_run_batch_once_invokes_pipeline_only(monkeypatch):
    """배치 파이프라인을 invoke만 한다 — backend·모델을 직접 부르지 않는다(seam=_run_batch_pipeline 1회)."""
    calls = {"n": 0}

    def _spy():
        calls["n"] += 1
        return {"articles": [], "save_result": SaveResponse(ok=True, saved=0)}

    monkeypatch.setattr(rss, "_run_batch_pipeline", _spy)

    run_batch_once()

    assert calls["n"] == 1  # 파이프라인 러너 외의 경로로 일을 하지 않는다.


# ---------------------------------------------------------------------------
# start_rss_scheduler — 주기 등록·겹침 방지·기동 정책
# ---------------------------------------------------------------------------
def test_start_rss_scheduler_registers_interval_job(monkeypatch):
    """interval·timezone·max_instances=1·misfire 유예·coalesce 가 add_job 에 그대로 전달되는지."""
    monkeypatch.setattr(rss, "BATCH_INTERVAL_MINUTES", 60)
    monkeypatch.setattr(rss, "BATCH_MAX_INSTANCES", 1)
    monkeypatch.setattr(rss, "BATCH_MISFIRE_GRACE_SEC", 300)
    monkeypatch.setattr(rss, "SCHEDULER_TIMEZONE", "Asia/Seoul")
    monkeypatch.setattr(rss, "SCHEDULER_JITTER_SEC", 0)
    monkeypatch.setattr(rss, "BATCH_RUN_ON_START", False)

    fake = MagicMock()
    returned = start_rss_scheduler(scheduler=fake)

    assert returned is fake
    fake.add_job.assert_called_once()
    args, kwargs = fake.add_job.call_args
    assert args[0] is run_batch_once           # 등록 대상 = 순수 엔트리포인트
    assert kwargs["trigger"] == "interval"
    assert kwargs["minutes"] == 60
    assert kwargs["max_instances"] == 1        # 겹침 방지: 이전 배치 미완료 시 skip
    assert kwargs["misfire_grace_time"] == 300
    assert kwargs["coalesce"] is True
    assert kwargs["timezone"] == "Asia/Seoul"
    fake.start.assert_called_once()


def test_start_rss_scheduler_run_on_start_triggers_once(monkeypatch):
    """BATCH_RUN_ON_START=True 면 등록 직후 run_batch_once 를 1회 즉시 실행한다."""
    monkeypatch.setattr(rss, "BATCH_RUN_ON_START", True)
    called = {"n": 0}
    monkeypatch.setattr(rss, "run_batch_once", lambda: called.__setitem__("n", called["n"] + 1))

    start_rss_scheduler(scheduler=MagicMock())

    assert called["n"] == 1


def test_start_rss_scheduler_no_run_on_start(monkeypatch):
    """BATCH_RUN_ON_START=False 면 기동 시 배치를 즉시 실행하지 않는다."""
    monkeypatch.setattr(rss, "BATCH_RUN_ON_START", False)
    called = {"n": 0}
    monkeypatch.setattr(rss, "run_batch_once", lambda: called.__setitem__("n", called["n"] + 1))

    start_rss_scheduler(scheduler=MagicMock())

    assert called["n"] == 0


# ---------------------------------------------------------------------------
# DB 미접근·로직 미복제·스케줄링 라이브러리 격리(정적 검사 — import 문만 파싱)
# ---------------------------------------------------------------------------
def _import_lines(module) -> list[str]:
    """import 문만 추출(주석·docstring 의 단어 언급을 오탐하지 않도록)."""
    src = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    return [ln for ln in src.splitlines() if ln.lstrip().startswith(("import ", "from "))]


def test_rss_scheduler_has_no_db_or_http_imports():
    """스케줄러 파일에 DB 드라이버·HTTP 라이브러리 import 가 없다(절대규칙 1). SQL·Cypher 도 직접 쓰지 않는다."""
    imports = " ".join(_import_lines(rss)).lower()
    for mod in ("httpx", "psycopg", "sqlalchemy", "neo4j", "pymysql", "asyncpg"):
        assert mod not in imports, f"금지된 DB/HTTP 라이브러리 import: {mod}"


def test_rss_scheduler_does_not_import_backend_directly():
    """배치 스케줄러는 파이프라인을 invoke만 한다 — backend 클라이언트를 직접 import 하지 않는다(§2)."""
    imports = " ".join(_import_lines(rss))
    assert "services.backend" not in imports
    assert "save_client" not in imports


def test_scheduling_library_import_is_isolated():
    """APScheduler import 는 함수 안(들여쓰기)에만 있어야 한다 — 모듈 top-level 은 스케줄러 없이도 import 된다(§2)."""
    for line in _import_lines(rss):
        if "apscheduler" in line.lower():
            assert line[:1].isspace(), f"top-level 에서 스케줄링 라이브러리 import: {line!r}"
