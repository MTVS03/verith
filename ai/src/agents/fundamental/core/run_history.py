from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUN_HISTORY_PATH = Path(__file__).resolve().parents[1] / "data" / ".runs" / "history.jsonl"


def _clean_record(record: dict[str, Any]) -> dict[str, Any]:
    # 로컬 실행 이력은 운영 관측용 최소 필드만 남긴다. 질문 원문이나 시크릿은 저장하지 않는다.
    allowed = {
        "trace_id",
        "request_id",
        "ticker",
        "corp_name",
        "report_mode",
        "score",
        "label",
        "llm_provider",
        "llm_model",
        "latency_ms",
        "llm_calls",
        "prompt_tokens",
        "completion_tokens",
        "guard_violations",
        "failures",
    }
    cleaned = {key: value for key, value in record.items() if key in allowed}
    cleaned["created_at"] = datetime.now(timezone.utc).isoformat()
    return cleaned


def append_history(record: dict[str, Any], path: Path = RUN_HISTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(_clean_record(record), ensure_ascii=False, default=str) + "\n")


def recent_stats(limit: int = 20, path: Path = RUN_HISTORY_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"runs": 0, "template_runs": 0, "failure_runs": 0}
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    records = [json.loads(line) for line in lines if line.strip()]
    return {
        "runs": len(records),
        "template_runs": sum(1 for item in records if item.get("llm_provider") == "template"),
        "failure_runs": sum(1 for item in records if item.get("failures")),
    }
