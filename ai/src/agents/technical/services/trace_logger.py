"""Technical Agent 실행 trace 로거 (trace_schema.md 정본).

관측 전용 계층 — 계산·판단 로직을 바꾸지 않는다. event_type은 정본 8개
(trace_start·trace_end·node_start·node_end·validation·retry·fallback·error)만 쓰고,
KIS/cache/LLM 등 세부는 `node` + event_type + summary 조합으로 표현한다(§7·§9·§12).

**secret-safe(§10·§13):** 원본 query는 `original_query_hash`(salt 없는 sha256)만, LLM prompt/response·
OHLCV 배열·API key/token은 절대 기록하지 않는다. error message는 type + 안전 truncate만 남긴다.
trace 실패는 호출자(agent 실행)로 전파하지 않는다 — `TraceLogger`가 sink.emit을 try/except로 격리한다.

sink는 주입식이다: `NoopTraceSink`(기본·아무것도 안 함)·`InMemoryTraceSink`(테스트)·`JsonlTraceSink`(운영,
path 주입). 실제 파일 경로/config 자동 생성은 이 브랜치 범위 밖(AI endpoint 통합에서 결선)."""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal, Protocol

from ..config import TRACE_MAX_ERROR_MESSAGE_LENGTH

logger = logging.getLogger(__name__)

EventType = Literal[
    "trace_start", "trace_end", "node_start", "node_end",
    "validation", "retry", "fallback", "error",
]
EventStatus = Literal["success", "failed", "skipped"]

# metadata/summary에 절대 넣으면 안 되는 secret 키워드(방어적 redaction — allowlist 실패 대비).
_SECRET_HINTS = ("key", "secret", "token", "password", "authorization", "prompt", "query")
_REDACTED = "***redacted***"


def hash_query(query: str) -> str:
    """원본 query → `sha256:<hex>`. 평문은 반환하지 않는다(§10, salt 없음)."""
    return "sha256:" + hashlib.sha256(query.encode("utf-8")).hexdigest()


def safe_error(exc: BaseException) -> dict[str, str] | None:
    """예외 → {error_type, message} 안전 요약. message는 truncate하고 secret 키워드는 통째 redact."""
    if exc is None:
        return None
    text = str(exc)
    lowered = text.lower()
    if any(h in lowered for h in ("key", "secret", "token", "password", "authorization")):
        message = _REDACTED  # secret이 섞였을 가능성 → 통째로 가림
    else:
        message = text[:TRACE_MAX_ERROR_MESSAGE_LENGTH]
    return {"error_type": type(exc).__name__, "message": message}


def _sanitize(value: Any) -> Any:
    """summary/metadata를 재귀 정화 — secret 힌트 key는 redact, 과대 배열/문자열은 축약."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k).lower()
            # secret 힌트 key는 redact. 단 `*_hash`(sha256 등 안전 파생값)는 예외 —
            # original_query_hash처럼 이미 해시된 필드는 원문이 아니므로 그대로 둔다.
            if "hash" not in key and any(h in key for h in _SECRET_HINTS):
                out[k] = _REDACTED
            else:
                out[k] = _sanitize(v)
        return out
    if isinstance(value, (list, tuple)):
        if len(value) > 20:  # 원천 배열 통째 저장 금지 — count로 축약
            return {"_omitted_list_len": len(value)}
        return [_sanitize(v) for v in value]
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "…"
    return value


def _ms(start: datetime, end: datetime) -> int:
    """두 시각의 경과를 밀리초 정수로. 음수(시계 역행)는 0으로 클램프."""
    return max(0, int((end - start).total_seconds() * 1000))


class _NodeSpan:
    """`TraceLogger.node()`가 yield하는 핸들 — 호출부가 node_end에 실을 요약/상태를 채운다."""

    def __init__(self) -> None:
        self.output_summary: dict[str, Any] = {}
        self.status: EventStatus = "success"


@dataclass
class TraceEvent:
    """trace event(§7). node/duration/summary/error는 선택. event_id는 sink 저장 순번으로 부여 가능."""
    trace_id: str
    event_type: EventType
    status: EventStatus
    started_at: str
    node: str | None = None
    node_run_id: str | None = None
    ended_at: str | None = None
    duration_ms: int | None = None
    input_summary: dict[str, Any] = field(default_factory=dict)
    output_summary: dict[str, Any] = field(default_factory=dict)
    error: dict[str, str] | None = None
    event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TraceSink(Protocol):
    """trace event 소비 경계. emit은 예외를 던져도 되지만 TraceLogger가 격리한다."""

    def emit(self, event: dict[str, Any]) -> None: ...


class NoopTraceSink:
    """아무것도 하지 않는 기본 sink(trace 비활성)."""

    def emit(self, event: dict[str, Any]) -> None:  # noqa: D401 - no-op
        return None


class InMemoryTraceSink:
    """테스트용 — event를 리스트에 모은다."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)


class JsonlTraceSink:
    """append-only JSONL sink(운영). path를 주입받는다(자동 생성/ config 결선은 범위 밖)."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def emit(self, event: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(event, ensure_ascii=False) + "\n")


class TraceLogger:
    """sink를 감싼 얇은 로거. **sink.emit 예외를 삼켜** trace 실패가 agent 실행을 깨지 않게 한다.

    summary/metadata는 `_sanitize`로 정화하고, error는 `safe_error`로 안전 요약한다.
    now는 주입 가능(테스트 결정론) — 미주입 시 실행 시각(UTC).
    """

    def __init__(self, sink: TraceSink | None, *, trace_id: str, now_fn=None):
        self._sink = sink or NoopTraceSink()
        self._trace_id = trace_id
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._seq = 0

    def now_iso(self) -> str:
        return self._now_fn().isoformat()

    @contextmanager
    def node(self, node_code: str, *, input_summary: dict[str, Any] | None = None) -> Iterator[_NodeSpan]:
        """node_start → (본문) → node_end(duration 포함)로 한 노드 실행을 감싼다.

        yield된 `_NodeSpan`에 `output_summary`/`status`를 채우면 node_end에 실린다.
        본문이 예외를 던지면 node_end를 `status=failed`(+safe_error)로 남기고 예외는 그대로 전파한다
        (trace만 실패를 흡수하고 계산 예외는 삼키지 않는다)."""
        start = self._now_fn()
        self.emit("node_start", node=node_code, started_at=start.isoformat(), input_summary=input_summary)
        span = _NodeSpan()
        try:
            yield span
        except BaseException as exc:  # noqa: BLE001 - node_end(failed) 남기고 재전파
            end = self._now_fn()
            self.emit("node_end", "failed", node=node_code, started_at=start.isoformat(),
                      ended_at=end.isoformat(), duration_ms=_ms(start, end),
                      output_summary=span.output_summary, error=exc)
            raise
        end = self._now_fn()
        self.emit("node_end", span.status, node=node_code, started_at=start.isoformat(),
                  ended_at=end.isoformat(), duration_ms=_ms(start, end),
                  output_summary=span.output_summary)

    def emit(
        self,
        event_type: EventType,
        status: EventStatus = "success",
        *,
        node: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        duration_ms: int | None = None,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
        error: BaseException | dict[str, str] | None = None,
    ) -> None:
        try:
            self._seq += 1
            ts = started_at or self.now_iso()
            err = safe_error(error) if isinstance(error, BaseException) else error
            event = TraceEvent(
                trace_id=self._trace_id,
                event_type=event_type,
                status=status,
                started_at=ts,
                node=node,
                ended_at=ended_at,
                duration_ms=duration_ms,
                input_summary=_sanitize(input_summary or {}),
                output_summary=_sanitize(output_summary or {}),
                error=err,
                event_id=f"evt_{self._seq:03d}",
            ).to_dict()
            self._sink.emit(event)
        except Exception:  # noqa: BLE001 - trace 실패는 agent 실행으로 전파하지 않는다
            logger.warning("trace_emit_failed", extra={"event_type": event_type}, exc_info=True)
