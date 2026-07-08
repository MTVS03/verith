"""fallback 승격 후보 집계 테스트 — 순수 함수 + capture sink + 오프라인 collect. canonical 미접근.

collect → review → approve → apply 중 collect 만 검증. 이 계층은 정본을 절대 write 하지 않는다.
"""

from __future__ import annotations

import json

from src.supervisor.planning.fallback_observer import (
    FallbackEvent,
    JsonlPromotionCaptureSink,
    MultiFallbackObserver,
    RecordingFallbackObserver,
)
from src.supervisor.planning.fallback_promotion import (
    PromotionInput,
    aggregate,
    classify,
    is_candidate,
)


def _inp(nq, code, source="dart", seen="2026-07-09T00:00:00+00:00", status="resolved", name="종목", mt=("name_exact",)):
    return PromotionInput(
        normalized_query=nq, stock_code=code, final_source=source, seen_at=seen,
        stock_name=name, market="KOSPI", match_types=mt, final_status=status,
    )


# ── is_candidate / classify ─────────────────────────────────────────────────
def test_is_candidate_true_for_resolved_known_source():
    assert is_candidate(_inp("삼성화재해상보험", "000810")) is True


def test_is_candidate_false_for_non_resolved():
    assert is_candidate(_inp("x", "000810", status="not_found")) is False
    assert is_candidate(_inp("x", "000810", status="ambiguous")) is False


def test_is_candidate_false_for_short_or_unknown_source():
    assert is_candidate(_inp("ab", "000810")) is False               # 정규화 len<3
    assert is_candidate(_inp("삼성화재해상보험", "000810", source="mystery")) is False


def test_classify_dart_vs_other():
    assert classify("dart") == ("alias_addition", False)             # 종목 존재 확정
    assert classify("curated") == ("alias_addition", True)           # canonical 재확인 필요


# ── aggregate ───────────────────────────────────────────────────────────────
def test_aggregate_dedups_and_counts():
    recs = [
        _inp("삼성화재해상보험", "000810", seen="2026-07-09T01:00:00+00:00"),
        _inp("삼성화재해상보험", "000810", seen="2026-07-09T05:00:00+00:00"),
        _inp("케이씨씨", "002380", seen="2026-07-09T06:00:00+00:00"),
    ]
    cands = aggregate(recs)
    assert len(cands) == 2
    top = cands[0]                                                    # observed_count 내림차순
    assert top.stock_code == "000810" and top.observed_count == 2
    assert top.first_seen_at == "2026-07-09T01:00:00+00:00"
    assert top.last_seen_at == "2026-07-09T05:00:00+00:00"
    assert top.candidate_type == "alias_addition" and top.promotion_status == "pending"


def test_aggregate_skips_non_candidates():
    recs = [_inp("x", "1", status="not_found"), _inp("ab", "2"), _inp("정상표현", "000810")]
    cands = aggregate(recs)
    assert [c.stock_code for c in cands] == ["000810"]


def test_aggregate_multi_source_dart_representative():
    recs = [
        _inp("어떤표현", "005930", source="curated"),
        _inp("어떤표현", "005930", source="dart"),
    ]
    (c,) = aggregate(recs)
    assert c.sources == ["curated", "dart"] and c.final_source == "dart"
    assert c.needs_canonical_check is False                           # dart 대표 → 재확인 불필요


# ── capture sink (opt-in) ───────────────────────────────────────────────────
def test_capture_sink_writes_resolved_only(tmp_path):
    path = tmp_path / "cap.jsonl"
    sink = JsonlPromotionCaptureSink(path)
    sink.record(FallbackEvent(
        attempted=True, final_status="resolved", final_source="dart",
        normalized_query="삼성화재해상보험", stock_code="000810", stock_name="삼성화재", market="KOSPI",
        match_types=["name_exact"],
    ))
    sink.record(FallbackEvent(attempted=True, final_status="not_found"))   # 무시돼야
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    d = json.loads(lines[0])
    assert d["stock_code"] == "000810" and d["normalized_query"] == "삼성화재해상보험"
    assert "seen_at" in d                                             # sink 이 stamp


def test_multi_observer_fans_out(tmp_path):
    rec = RecordingFallbackObserver()
    sink = JsonlPromotionCaptureSink(tmp_path / "cap.jsonl")
    multi = MultiFallbackObserver([rec, sink])
    multi.record(FallbackEvent(
        attempted=True, final_status="resolved", final_source="curated",
        normalized_query="카카오", stock_code="035720",
    ))
    assert len(rec.events) == 1
    assert (tmp_path / "cap.jsonl").exists()


# ── no canonical write (안전성) ──────────────────────────────────────────────
def test_promotion_modules_do_not_import_backend_or_db():
    # 이 계층은 canonical 을 읽지도 쓰지도 않는다 — DB/backend 접근 심볼 부재로 경계 고정.
    import src.supervisor.planning.fallback_promotion as mod
    text = open(mod.__file__ or "", encoding="utf-8").read()
    for forbidden in ("psycopg", "sqlalchemy", "from db", "import db", "requests", "httpx"):
        assert forbidden not in text
