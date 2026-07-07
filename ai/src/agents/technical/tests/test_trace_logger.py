"""trace_logger 단위 테스트 — secret-safe·격리·직렬화.

now를 주입해 결정론으로 검증한다. 실 파일은 tmp_path에만 쓴다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from src.agents.technical.config import TRACE_MAX_ERROR_MESSAGE_LENGTH
from src.agents.technical.observability.trace_logger import (
    InMemoryTraceSink,
    JsonlTraceSink,
    NoopTraceSink,
    TraceLogger,
    hash_query,
    safe_error,
)

_NOW = datetime(2026, 7, 7, 0, 0, 0, tzinfo=timezone.utc)


def _logger(sink):
    return TraceLogger(sink, trace_id="trace_x", now_fn=lambda: _NOW)


# ── query_hash: 원문 미포함 ────────────────────────────────────────────────────
def test_hash_query_does_not_contain_plaintext():
    q = "LG엔솔 지금 사도 돼?"
    h = hash_query(q)
    assert h.startswith("sha256:")
    assert q not in h
    assert "사도" not in h
    assert hash_query(q) == hash_query(q)  # 결정론


# ── NoopTraceSink: 예외 없이 무시 ─────────────────────────────────────────────
def test_noop_sink_ignores():
    _logger(NoopTraceSink()).emit("trace_start")  # no raise, no state


# ── InMemoryTraceSink: event 저장 + 필드 ──────────────────────────────────────
def test_in_memory_sink_records_event():
    sink = InMemoryTraceSink()
    _logger(sink).emit("node_end", "success", node="data_collect",
                       output_summary={"cache_hit_by_period": {"D": True}}, duration_ms=12)
    assert len(sink.events) == 1
    e = sink.events[0]
    assert e["trace_id"] == "trace_x"
    assert e["event_type"] == "node_end" and e["status"] == "success"
    assert e["node"] == "data_collect" and e["duration_ms"] == 12
    assert e["output_summary"]["cache_hit_by_period"] == {"D": True}
    assert e["event_id"] == "evt_001" and e["started_at"] == _NOW.isoformat()


# ── JsonlTraceSink: 한 줄 JSONL ───────────────────────────────────────────────
def test_jsonl_sink_writes_one_line(tmp_path):
    path = tmp_path / "trace.jsonl"
    log = TraceLogger(JsonlTraceSink(path), trace_id="t", now_fn=lambda: _NOW)
    log.emit("trace_start")
    log.emit("trace_end", output_summary={"status": "completed"})
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event_type"] == "trace_start"
    assert json.loads(lines[1])["output_summary"]["status"] == "completed"


# ── secret redaction ──────────────────────────────────────────────────────────
def test_secret_keys_redacted_in_summary():
    sink = InMemoryTraceSink()
    _logger(sink).emit("node_end", node="x",
                       output_summary={"api_key": "sk-123", "token": "abc", "ticker": "373220"})
    out = sink.events[0]["output_summary"]
    assert out["api_key"] == "***redacted***"
    assert out["token"] == "***redacted***"
    assert out["ticker"] == "373220"  # 안전 값은 유지


def test_query_hash_key_is_not_redacted_but_raw_query_is():
    sink = InMemoryTraceSink()
    _logger(sink).emit("trace_start",
                       input_summary={"original_query_hash": "sha256:abc", "query": "원문"})
    out = sink.events[0]["input_summary"]
    assert out["original_query_hash"] == "sha256:abc"  # *_hash는 안전 파생값 → 유지
    assert out["query"] == "***redacted***"            # 원문 query 키는 redact


def test_safe_error_truncates_and_redacts():
    long = safe_error(ValueError("x" * 1000))
    assert long["error_type"] == "ValueError"
    assert len(long["message"]) <= TRACE_MAX_ERROR_MESSAGE_LENGTH
    secret = safe_error(RuntimeError("appsecret=SUPER_SECRET_VALUE leaked"))
    assert "SUPER_SECRET_VALUE" not in secret["message"]  # KIS appsecret 값 제거
    assert "***redacted***" in secret["message"]


def test_large_list_summary_omitted():
    sink = InMemoryTraceSink()
    _logger(sink).emit("node_end", node="chart_generate",
                       output_summary={"candles": list(range(100))})
    assert sink.events[0]["output_summary"]["candles"] == {"_omitted_list_len": 100}


# ── 값-패턴 secret 스크럽(§10·§13): key가 무해해도 값 형태로 잡는다 ─────────────
import pytest  # noqa: E402


@pytest.mark.parametrize("secret_val, leak", [
    ("HTTP 401: sk-proj-abc123xyz789def456", "sk-proj-abc123xyz789def456"),   # OpenAI key
    ("auth: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sIg", "eyJhbGciOiJIUzI1NiJ9"),  # Bearer/JWT
    ("connect redis://user:p4ssw0rd@host:6379/0", "p4ssw0rd"),               # URL credential
    ("KIS appsecret=SUPER_SECRET_abc123 rejected", "SUPER_SECRET_abc123"),   # k=v secret
])
def test_value_pattern_scrub_in_error(secret_val, leak):
    # error message(str)로 들어온 secret 값이 trace에 남지 않는다
    sink = InMemoryTraceSink()
    _logger(sink).emit("error", "failed", node="data_collect", error=RuntimeError(secret_val))
    dumped = json.dumps(sink.events[0], ensure_ascii=False)
    assert leak not in dumped
    assert "***redacted***" in dumped


def test_value_pattern_scrub_under_innocuous_key():
    # key 이름이 무해해도(detail/note) 값이 secret 형태면 스크럽된다
    sink = InMemoryTraceSink()
    _logger(sink).emit("node_end", node="data_collect", output_summary={
        "detail": "conn redis://u:p4ssw0rd@h", "note": "sk-proj-ZZZ1234567890abcdef"})
    out = sink.events[0]["output_summary"]
    assert "p4ssw0rd" not in out["detail"] and "***redacted***" in out["detail"]
    assert "sk-proj-ZZZ1234567890abcdef" not in out["note"]


def test_error_dict_is_sanitized_not_bypassed():
    # error=dict로 들어와도 raw secret이 그대로 sink에 저장되지 않는다
    sink = InMemoryTraceSink()
    _logger(sink).emit("error", "failed", node="data_collect",
                       error={"error_type": "RuntimeError", "message": "sk-proj-RAW_SECRET_1234567890"})
    dumped = json.dumps(sink.events[0]["error"], ensure_ascii=False)
    assert "sk-proj-RAW_SECRET_1234567890" not in dumped
    assert "***redacted***" in dumped


def test_identifiers_survive_high_entropy_scrub():
    # trace_id/event_id/original_query_hash는 긴 hex/base64처럼 보여도 사라지지 않는다
    sink = InMemoryTraceSink()
    long_hex = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"  # 40 hex → 긴 토큰처럼 보임
    _logger(sink).emit("trace_start", input_summary={
        "trace_id": long_hex, "event_id": "evt_042",
        "original_query_hash": hash_query("무엇을 살까"), "foo_hash": long_hex})
    out = sink.events[0]["input_summary"]
    assert out["trace_id"] == long_hex                     # 식별자 유지
    assert out["original_query_hash"].startswith("sha256:")
    assert out["foo_hash"] == long_hex                     # *_hash 면제


# ── sink 예외가 caller로 전파되지 않음 ────────────────────────────────────────
def test_sink_exception_is_isolated():
    class BoomSink:
        def emit(self, event):
            raise ConnectionError("sink down")
    _logger(BoomSink()).emit("trace_start")  # no raise


# ── error 인자로 예외 객체를 넘기면 safe_error로 변환 ─────────────────────────
def test_emit_error_from_exception():
    sink = InMemoryTraceSink()
    _logger(sink).emit("error", "failed", node="data_collect", error=RuntimeError("boom"))
    err = sink.events[0]["error"]
    assert err["error_type"] == "RuntimeError" and err["message"] == "boom"


def test_default_sink_is_noop():
    # sink=None이면 Noop으로 동작(예외 없음)
    TraceLogger(None, trace_id="t", now_fn=lambda: _NOW).emit("trace_start")
