from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def record_decision(
    decisions: list[dict[str, Any]] | None,
    *,
    stage: str,
    decision: str,
    reason: str,
    provider: str = "deterministic",
    model: str | None = None,
    latency_ms: int | None = None,
) -> list[dict[str, Any]]:
    """LLM/결정론 노드의 분기 선택을 meta.agent_decisions에 남긴다."""
    items = list(decisions or [])
    payload: dict[str, Any] = {
        "stage": stage,
        "decision": decision,
        "reason": reason,
        "provider": provider,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if model:
        payload["model"] = model
    if latency_ms is not None:
        payload["latency_ms"] = latency_ms
    items.append(payload)
    return items
