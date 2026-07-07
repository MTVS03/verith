# scheduler/ — 매시간 배치·7일 삭제 스케줄러 엔트리포인트 재노출. TASK 10
"""배치·삭제의 "언제 도는가"만 담당하는 얇은 트리거 계층(CLAUDE.md §6).

- rss_scheduler   : 배치 한 pass(수집→분석→저장) 매시간 트리거. run_batch_once / start_rss_scheduler.
- cleanup_scheduler: 7일 롤링 삭제를 backend 에 트리거. run_cleanup_once / start_cleanup_scheduler.
- runner          : 두 스케줄러 함께 기동 + graceful shutdown(python -m scheduler → start_all/main).

run_batch_once/run_cleanup_once 는 부수효과 순수 엔트리포인트라 in-process 스케줄러 없이 외부 cron·
수동 실행이 직접 부를 수 있다. 실제 로직(크롤·LLM·저장·삭제 판정)은 nodes/services/backend 소유(§2).
"""
from __future__ import annotations

from scheduler.cleanup_scheduler import run_cleanup_once, start_cleanup_scheduler
from scheduler.rss_scheduler import BatchRunResult, run_batch_once, start_rss_scheduler
from scheduler.runner import main, start_all

__all__ = [
    "BatchRunResult",
    "run_batch_once",
    "start_rss_scheduler",
    "run_cleanup_once",
    "start_cleanup_scheduler",
    "start_all",
    "main",
]
