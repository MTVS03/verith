"""fallback observability 테스트 — structured event 가 남는지 + secret-safe 검증.

fallback 시도 시 event 1건(source/match/status 기록), canonical 성공 시 미기록, raw query/secret 미노출.
"""

from __future__ import annotations

from src.supervisor.planning.fallback_observer import RecordingFallbackObserver
from src.supervisor.planning.fallback_source import (
    CompositeFallbackLookup,
    CuratedFallbackSource,
    FallbackEntry,
)
from src.supervisor.planning.planner import run_supervisor
from src.supervisor.schemas import SupervisorInput
from src.supervisor.tests._fakes import FakeFallback, FakeResolver, fb_ambiguous, not_found, resolved

_CURATED = CompositeFallbackLookup(
    [CuratedFallbackSource((FallbackEntry("035720", "카카오", "KOSPI", ("Kakao",)),))]
)


def test_event_recorded_on_fallback_resolved():
    obs = RecordingFallbackObserver()
    run_supervisor(
        SupervisorInput(query="Kakao 분석해줘"),
        resolver=FakeResolver(result=not_found()),
        fallback=_CURATED,
        observer=obs,
    )
    assert len(obs.events) == 1
    ev = obs.events[0]
    assert ev.attempted is True
    assert ev.final_status == "resolved"
    assert ev.final_source == "curated"
    assert ev.source_hits == {"curated": 1}
    assert ev.match_types == ["alias_exact"]
    assert ev.candidate_count == 0


def test_event_recorded_on_fallback_ambiguous():
    obs = RecordingFallbackObserver()
    run_supervisor(
        SupervisorInput(query="스페셜 어쩌고"),
        resolver=FakeResolver(result=not_found()),
        fallback=FakeFallback(result=fb_ambiguous(("035720", "카카오"), ("000660", "SK하이닉스"))),
        observer=obs,
    )
    assert len(obs.events) == 1
    ev = obs.events[0]
    assert ev.final_status == "ambiguous" and ev.candidate_count == 2
    assert ev.final_source is None            # ambiguous 는 최종 source 없음


def test_no_event_when_canonical_resolves():
    obs = RecordingFallbackObserver()
    run_supervisor(
        SupervisorInput(query="삼성전자 차트 어때?"),
        resolver=FakeResolver(result=resolved("005930", "삼성전자")),
        fallback=_CURATED,
        observer=obs,
    )
    assert obs.events == []                    # canonical 성공 → fallback 미시도 → 미기록


def test_no_event_when_canonical_error():
    obs = RecordingFallbackObserver()
    run_supervisor(
        SupervisorInput(query="카카오 분석해줘"),
        resolver=FakeResolver(raise_kind="timeout"),
        fallback=_CURATED,
        observer=obs,
    )
    assert obs.events == []                    # error 에선 fallback 미시도


def test_event_recorded_on_fallback_tool_error_kept_not_found():
    obs = RecordingFallbackObserver()
    run_supervisor(
        SupervisorInput(query="카카오 분석해줘"),
        resolver=FakeResolver(result=not_found()),
        fallback=FakeFallback(raise_error=True),
        observer=obs,
    )
    assert len(obs.events) == 1
    ev = obs.events[0]
    assert ev.final_status == "not_found"      # 도구 장애 → not_found 유지, 그래도 시도 기록
    assert ev.source_hits == {}


def test_event_is_secret_safe_no_raw_query():
    obs = RecordingFallbackObserver()
    query = "Kakao 초민감정보포함질의 분석해줘"
    run_supervisor(
        SupervisorInput(query=query),
        resolver=FakeResolver(result=not_found()),
        fallback=_CURATED,
        observer=obs,
    )
    ev = obs.events[0]
    # 길이만 남고 raw query 문자열은 어디에도 실리지 않는다.
    assert ev.query_len == len(query) and ev.query_norm_len > 0
    assert "초민감정보포함질의" not in repr(ev)
    assert not hasattr(ev, "query")


def test_observer_optional_no_crash_without_observer():
    # observer 미주입이어도 fallback 은 정상 동작한다(no-op).
    decision = run_supervisor(
        SupervisorInput(query="Kakao 분석해줘"),
        resolver=FakeResolver(result=not_found()),
        fallback=_CURATED,
    )
    assert decision.resolution.status == "resolved" and decision.resolution.persisted is False
