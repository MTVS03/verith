# scheduler/rss_scheduler.py — 배치 스케줄러(트리거만. 파이프라인 로직은 nodes/services). TASK 10
"""매시간 배치 한 pass 를 실행하는 얇은 트리거 계층.

배치 파이프라인(crawl → extract → sentiment → embedding → merge_event → importance → graph → save,
CLAUDE.md §3)의 "무엇을 하는가"는 이미 nodes/services(TASK 02~08)가 구현했다. 이 파일은 그것을
**"언제 도는가"** 로만 묶는다 — 타이밍·겹침 방지·예외 격리(§2). 파이프라인 배선(LangGraph 조립)은
TASK 11(graph.py)의 배치 앱이 소유하고, 스케줄러는 초기 state 를 만들어 그 앱을 **invoke 만** 한다.

⚠️ 절대규칙 1: DB·backend 를 직접 부르지 않는다(SQL·Cypher·HTTP 없음). 저장은 파이프라인 안 save 노드가
   save_client 로 한다. 이 파일은 backend·모델을 import 하지 않는다.
⚠️ 절대규칙 2: 파이프라인 로직을 여기 복제하지 않는다 — 배선된 배치 앱을 invoke 할 뿐.
⚠️ 스케줄링 라이브러리(APScheduler) import 는 start_rss_scheduler 안에만 가둔다(교체 가능하게 격리, §2).
   run_batch_once 는 부수효과 순수 엔트리포인트라 스케줄러 없이(외부 cron·수동·테스트) 직접 부를 수 있다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from config import (
    BATCH_INTERVAL_MINUTES,
    BATCH_MAX_INSTANCES,
    BATCH_MISFIRE_GRACE_SEC,
    BATCH_RUN_ON_START,
    SCHEDULER_JITTER_SEC,
    SCHEDULER_TIMEZONE,
)

logger = logging.getLogger(__name__)

# APScheduler job id — replace_existing 로 중복 등록을 막는다.
_RSS_JOB_ID = "news_rss_batch"


@dataclass
class BatchRunResult:
    """배치 한 pass 결과(로깅·반환용). 성공 위장 금지 — 실패·skip 사유를 message 에 정직히 담는다(§2-5)."""

    ok: bool                    # 배치 pass 전체 성공 여부(저장 ok 반영)
    collected: int              # 수집 기사 수(state["articles"])
    saved: int                  # 저장 건수(SaveResponse.saved)
    message: str | None = None  # 실패·skip 사유


def _initial_batch_state() -> dict:
    """배치 파이프라인에 넘길 초기 state.

    노드들은 dict state 를 `state.get(...)` 로 읽고 채우는 계약이다(nodes/*.py). 초기값은 빈 dict 로
    충분하다 — 실제 상태 컨테이너 형태(BatchState)는 TASK 11 소유이며, 스케줄러는 시작점만 만든다.
    """
    return {}


def _run_batch_pipeline() -> dict:
    """TASK 11 이 조립한 배치 앱을 invoke 해 최종 state 를 돌려준다(스케줄러↔그래프 결합을 이 함수에 격리).

    lazy import 로 두어 (1) 스케줄러 모듈이 배치 그래프 미완성과 무관하게 import 되고, (2) 테스트가 이
    함수만 mock 해 파이프라인 결과/예외를 주입할 수 있게 한다. TASK 11 은 `graph.run_batch(state) -> state`
    를 제공한다(컴파일된 배치 앱 실행). 미구현 시 ImportError 는 run_batch_once 가 격리해 ok=False 로 보고.
    """
    from graph import run_batch  # TASK 11 소유(배치 앱 러너). 결합·미완성을 여기 가둔다.

    return run_batch(_initial_batch_state())


def run_batch_once() -> BatchRunResult:
    """배치 한 pass 실행: 초기 state → 배치 파이프라인 invoke → 결과 로깅·반환.

    - 파이프라인 어느 단계가 예외를 던져도 **삼켜 로깅**하고 결과에 정확히 담는다(스케줄러 루프 보호, §2-5).
    - 수집 0건이면 예외 없이 통과한다(환각 금지: 없으면 없는 대로, TASK 02 §3.6). 저장 노드가 backend 를
      부르지 않고 통과하므로 save_result 가 없을 수 있고, 이 경우 수집 0건이면 정상(ok=True)으로 본다.
    - 자체 배치 재시도 루프를 두지 않는다 — 실패는 다음 주기 재시도에 맡긴다(§2). 개별 호출 타임아웃·재시도는
      각 노드/서비스(TASK 02/03/08)가 이미 갖는다.
    - 부수효과 순수 엔트리포인트: 스케줄러 상태에 의존하지 않아 외부 cron·수동 실행이 직접 부를 수 있다.
    """
    try:
        state = _run_batch_pipeline()
    except Exception as exc:  # 파이프라인 전체를 감싸는 최후 방어 — 예외를 스케줄러 밖으로 내보내지 않는다.
        logger.exception("run_batch_once: 배치 파이프라인 예외 — ok=False(다음 주기 재시도)")
        return BatchRunResult(ok=False, collected=0, saved=0, message=str(exc))

    collected = len(state.get("articles") or [])
    save_result = state.get("save_result")

    if save_result is None:
        # 저장 결과가 없음 = 저장 단계까지 안 갔거나(수집 0건) 파이프라인이 save 를 건너뜀.
        if collected == 0:
            logger.info("run_batch_once: 수집 0건 — 예외 없이 통과")
            return BatchRunResult(ok=True, collected=0, saved=0, message="nothing collected")
        # 수집은 됐는데 저장 결과가 없다 = 파이프라인이 저장까지 못 감. 성공으로 위장하지 않는다.
        logger.error("run_batch_once: 수집 %d건이나 save_result 없음 — ok=False", collected)
        return BatchRunResult(
            ok=False, collected=collected, saved=0, message="pipeline produced no save_result"
        )

    ok = bool(getattr(save_result, "ok", False))
    saved = int(getattr(save_result, "saved", 0) or 0)
    if ok:
        logger.info("run_batch_once: 배치 완료(collected=%d, saved=%d)", collected, saved)
        return BatchRunResult(ok=True, collected=collected, saved=saved)
    # 저장 실패(SaveResponse.ok=False)는 진짜 실패 — 정직 보고(TASK 08 §4.2). idempotent 라 다음 주기 안전.
    message = getattr(save_result, "message", None)
    logger.error("run_batch_once: 저장 실패(ok=False) — %s", message)
    return BatchRunResult(ok=False, collected=collected, saved=saved, message=message)


def _build_scheduler():
    """APScheduler BackgroundScheduler 를 만든다. 스케줄링 라이브러리 import 를 이 층에만 가둔다(§2).

    타임존은 config(SCHEDULER_TIMEZONE)로 고정해 배포 서버 로컬 타임존에 흔들리지 않게 한다
    (published_at KST 정합, TASK 02). 스케줄링 수단을 바꿔도(OS cron·Celery beat) run_batch_once 는
    그대로 재사용된다.
    """
    from apscheduler.schedulers.background import BackgroundScheduler

    return BackgroundScheduler(timezone=SCHEDULER_TIMEZONE)


def start_rss_scheduler(scheduler=None):
    """run_batch_once 를 BATCH_INTERVAL_MINUTES·SCHEDULER_TIMEZONE 으로 주기 등록·기동한다.

    - 겹침 방지: max_instances=BATCH_MAX_INSTANCES(1이면 이전 배치 미완료 시 이번 주기 skip),
      coalesce=True(밀린 실행 합침), misfire_grace_time=BATCH_MISFIRE_GRACE_SEC(유예 초과 지연은 skip).
    - BATCH_RUN_ON_START 면 등록 직후 1회 즉시 실행(개발·초기 적재).
    - `scheduler` 를 주입하면 그것을 쓴다(start_all 이 여러 잡을 얹거나 테스트가 mock 주입할 때). 없으면
      _build_scheduler 로 만든다. 반환한 scheduler 로 호출자가 graceful shutdown(정지·완료 대기)을 한다.
    """
    if scheduler is None:
        scheduler = _build_scheduler()

    scheduler.add_job(
        run_batch_once,
        trigger="interval",
        minutes=BATCH_INTERVAL_MINUTES,
        max_instances=BATCH_MAX_INSTANCES,
        misfire_grace_time=BATCH_MISFIRE_GRACE_SEC,
        coalesce=True,
        jitter=SCHEDULER_JITTER_SEC or None,
        timezone=SCHEDULER_TIMEZONE,
        id=_RSS_JOB_ID,
        replace_existing=True,
    )

    if BATCH_RUN_ON_START:
        logger.info("start_rss_scheduler: BATCH_RUN_ON_START — 등록 직후 1회 배치 실행")
        run_batch_once()

    scheduler.start()
    logger.info(
        "start_rss_scheduler: 배치 스케줄러 기동(주기=%d분, tz=%s, max_instances=%d)",
        BATCH_INTERVAL_MINUTES, SCHEDULER_TIMEZONE, BATCH_MAX_INSTANCES,
    )
    return scheduler
