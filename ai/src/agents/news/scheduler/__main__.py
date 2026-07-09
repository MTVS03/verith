# scheduler/__main__.py — `python -m scheduler` 엔트리포인트. TASK 10
"""배포(systemd·컨테이너)가 두 스케줄러를 기동하는 진입점. 조립·기동은 runner.main 이 담당한다."""
from __future__ import annotations

from src.agents.news.scheduler.runner import main

if __name__ == "__main__":
    main()
