# scheduler/runner.py — 프로세스 엔트리포인트(조립·기동만, 얇게). TASK 10
"""배치·삭제 두 스케줄러를 함께 기동하고 graceful shutdown 을 처리하는 프로세스 엔트리포인트.

`python -m scheduler` 로 실행된다(scheduler/__main__.py → main). 배포(systemd·컨테이너)가 이 엔트리포인트를
기동한다(운영 영역과의 접점). 여기서는 두 스케줄러를 얹고 종료 신호를 기다릴 뿐, 파이프라인/삭제 로직은
넣지 않는다(§3.4-3). 실제 로직은 nodes/services/backend, 타이밍은 rss_scheduler/cleanup_scheduler 소유.
"""
from __future__ import annotations

import logging
import signal
import threading

from src.agents.news.scheduler.cleanup_scheduler import start_cleanup_scheduler
from src.agents.news.scheduler.rss_scheduler import start_rss_scheduler

logger = logging.getLogger(__name__)


def start_all():
    """배치·삭제 스케줄러를 함께 기동하고, SIGINT/SIGTERM 수신까지 블록한 뒤 graceful shutdown 한다.

    - 두 스케줄러를 분리 기동한다(관심사·주기·실패 분리, §2). 하나가 막혀도 다른 하나는 계속 돈다.
    - 종료 신호를 받으면 각 스케줄러를 shutdown(wait=True) — 진행 중인 배치가 끝날 때까지 기다린 뒤 정지한다.
    - 조립·기동만 담당한다(얇게). run_batch_once/run_cleanup_once 는 순수 엔트리포인트라 이 함수 없이도
      외부 cron 이 직접 부를 수 있다.
    """
    schedulers = [start_rss_scheduler(), start_cleanup_scheduler()]
    logger.info("start_all: 배치·삭제 스케줄러 기동 완료 — 종료 신호 대기")

    stop = threading.Event()

    def _handle(signum, _frame):
        logger.info("start_all: 신호 %s 수신 — 스케줄러 정지(진행 배치 완료 대기)", signum)
        stop.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    try:
        stop.wait()
    finally:
        for sched in schedulers:
            try:
                sched.shutdown(wait=True)  # 진행 중 배치/삭제가 끝날 때까지 대기 후 정지.
            except Exception:  # 정지 중 예외가 다른 스케줄러 정지를 막지 않게 격리.
                logger.exception("start_all: 스케줄러 정지 중 예외")
        logger.info("start_all: 모든 스케줄러 정지 완료")


def main():
    """프로세스 엔트리포인트. 로깅 기본 설정 후 start_all 을 부른다(python -m scheduler)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    start_all()


if __name__ == "__main__":
    main()
