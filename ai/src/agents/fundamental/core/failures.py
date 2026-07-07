from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

FailureType = Literal[
    "dart_unavailable",
    "unsupported_ticker",
    "empty_data",
    "llm_all_failed",
    "critic_skipped",
    "guard_rejected",
]


def record_failure(
    failures: list[dict[str, Any]] | None,
    *,
    failure_type: FailureType,
    stage: str,
    message: str,
    retryable: bool,
) -> list[dict[str, Any]]:
    """실패를 예외로만 흘리지 않고 JSON 관측 필드로 보존한다."""
    items = list(failures or [])
    items.append(
        {
            "type": failure_type,
            "stage": stage,
            "message": message,
            "retryable": retryable,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return items
