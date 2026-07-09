# scheduler/cleanup_scheduler.py — 삭제 스케줄러(backend 에 트리거만). TASK 10
"""7일 롤링 삭제를 backend 에 주기적으로 **트리거**하는 얇은 계층.

실제 삭제(168h 경과 판정·CASCADE(Event 기사수 0 삭제·고아 Keyword/Person/Country 정리·**Company 유지**)·
살아남은 Event importance 재계산)는 전부 backend 가 수행한다(SCHEMA_SPEC §5, erd.dbml). 이 파일은
"언제 지우라 신호를 줄지" 타이밍만 정하고 save_client.request_cleanup() 을 부른다.

⚠️ 절대규칙 1: 삭제 SQL/Cypher·168h 판정·고아 정리 로직이 이 파일에 **없다** — 전부 backend. DB 드라이버·
   HTTP 라이브러리 import 없음. 삭제는 오직 save_client.request_cleanup(backend HTTP)로만.
⚠️ 스케줄링 라이브러리(APScheduler) import 는 start_cleanup_scheduler 안에만 가둔다(§2).
   run_cleanup_once 는 부수효과 순수 엔트리포인트라 외부 cron·수동 실행이 직접 부를 수 있다.
"""
from __future__ import annotations

import logging

import src.agents.news.services.backend.save_client as save_client
from src.agents.news.config import (
    CLEANUP_INTERVAL_MINUTES,
    CLEANUP_MAX_INSTANCES,
    CLEANUP_MISFIRE_GRACE_SEC,
    SCHEDULER_JITTER_SEC,
    SCHEDULER_TIMEZONE,
)
from src.agents.news.schemas.response import CleanupResponse

logger = logging.getLogger(__name__)

_CLEANUP_JOB_ID = "news_cleanup"


def run_cleanup_once() -> CleanupResponse:
    """save_client.request_cleanup() 로 7일 롤링 삭제를 backend 에 트리거하고 결과를 로깅·반환한다.

    - 168h·CASCADE·고아 정리·Company 유지·importance 재계산은 backend 가 수행(스케줄러는 타이밍만, §2).
    - 실패는 성공으로 위장하지 않는다 — CleanupResponse(ok=False) 를 정확히 로깅(§2-5). 다음 주기 재시도.
    - request_cleanup 은 쓰기 실패를 이미 degrade 없이 ok=False 로 돌려주지만(TASK 08), 예기치 못한 예외도
      스케줄러 루프를 죽이지 않도록 여기서 격리한다.
    - 자체 재시도 루프 없음(다음 주기 재시도). 부수효과 순수 엔트리포인트(외부 cron 직접 호출 가능).
    """
    try:
        result = save_client.request_cleanup()
    except Exception as exc:  # request_cleanup 은 보통 ok=False 로 보고하지만, 예외도 루프 밖으로 안 내보낸다.
        logger.exception("run_cleanup_once: 삭제 트리거 예외 — ok=False(다음 주기 재시도)")
        return CleanupResponse(ok=False, message=str(exc))

    if result.ok:
        logger.info(
            "run_cleanup_once: 삭제 트리거 완료(deleted_articles=%d, deleted_events=%d)",
            result.deleted_articles, result.deleted_events,
        )
    else:
        logger.error("run_cleanup_once: 삭제 실패(ok=False) — %s", result.message)
    return result


def _build_scheduler():
    """APScheduler BackgroundScheduler 를 만든다(스케줄링 라이브러리 import 를 이 층에만 가둠, §2)."""
    from apscheduler.schedulers.background import BackgroundScheduler

    return BackgroundScheduler(timezone=SCHEDULER_TIMEZONE)


def start_cleanup_scheduler(scheduler=None):
    """run_cleanup_once 를 CLEANUP_INTERVAL_MINUTES·SCHEDULER_TIMEZONE 으로 주기 등록·기동한다.

    겹침 방지(max_instances=CLEANUP_MAX_INSTANCES)·coalesce·misfire 유예·예외 격리는 배치와 동일 정책.
    `scheduler` 를 주입하면 그것을 쓴다(start_all·테스트). 없으면 _build_scheduler 로 만든다. 반환한
    scheduler 로 호출자가 graceful shutdown 한다. 스케줄링 라이브러리 import 는 이 함수(층)에만.
    """
    if scheduler is None:
        scheduler = _build_scheduler()

    scheduler.add_job(
        run_cleanup_once,
        trigger="interval",
        minutes=CLEANUP_INTERVAL_MINUTES,
        max_instances=CLEANUP_MAX_INSTANCES,
        misfire_grace_time=CLEANUP_MISFIRE_GRACE_SEC,
        coalesce=True,
        jitter=SCHEDULER_JITTER_SEC or None,
        timezone=SCHEDULER_TIMEZONE,
        id=_CLEANUP_JOB_ID,
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "start_cleanup_scheduler: 삭제 스케줄러 기동(주기=%d분, tz=%s, max_instances=%d)",
        CLEANUP_INTERVAL_MINUTES, SCHEDULER_TIMEZONE, CLEANUP_MAX_INSTANCES,
    )
    return scheduler
