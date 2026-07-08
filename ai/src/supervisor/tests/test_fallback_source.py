"""운영형 fallback source(curated + composite) 테스트 — 결정론, 실 네트워크 없음.

검증 축: code/name/alias exact 우선순위, 다중 source dedup/ambiguous, canonical 우선(planner 통합),
ephemeral 전파, canonical write 경로 부재.
"""

from __future__ import annotations

from src.supervisor.planning.fallback_lookup import FallbackLookupError
from src.supervisor.planning.fallback_source import (
    CURATED_FALLBACK_ENTRIES,
    CompositeFallbackLookup,
    CuratedFallbackSource,
    FallbackEntry,
    SourceHit,
    default_fallback_lookup,
)
from src.supervisor.planning.planner import run_supervisor
from src.supervisor.planning.policy import STOCK_DEPENDENT, STOCK_OPTIONAL
from src.supervisor.schemas import SupervisorInput
from src.supervisor.tests._fakes import FakeResolver, not_found, resolved

_ENTRIES = (
    FallbackEntry("005930", "삼성전자", "KOSPI", ("Samsung Electronics",)),
    FallbackEntry("035720", "카카오", "KOSPI", ("Kakao",)),
    FallbackEntry("000660", "SK하이닉스", "KOSPI", ("SK Hynix",)),
)


def _curated(entries=_ENTRIES) -> CompositeFallbackLookup:
    return CompositeFallbackLookup([CuratedFallbackSource(entries)])


# ── 판정 규칙 (curated + composite) ─────────────────────────────────────────
def test_alias_exact_single_resolves():
    r = _curated().lookup("Samsung Electronics 주가 어때")
    assert r.status == "resolved" and r.stock.stock_code == "005930"


def test_name_exact_korean_substring_resolves():
    # 한글 name 은 붙여쓰기 질의에도 매칭(정규화 substring).
    r = _curated().lookup("카카오주가어때")
    assert r.status == "resolved" and r.stock.stock_code == "035720"


def test_latin_alias_is_word_bounded_no_partial_hit():
    # 'Kakao' 는 단어 경계 매칭 — 'kakaobank' 같은 부분단어에 오탐하지 않는다.
    r = _curated().lookup("kakaobank 어때")
    assert r.status == "not_found"


def test_code_exact_takes_priority_over_alias():
    # 질의에 6자리 code(005930)와 다른 종목 alias(Kakao)가 동시에 → code_exact 최우선(단일) → resolved.
    r = _curated().lookup("005930 그리고 Kakao 비교")
    assert r.status == "resolved" and r.stock.stock_code == "005930"


def test_two_code_exacts_are_ambiguous():
    r = _curated().lookup("005930 000660 중 뭐가 나아?")
    assert r.status == "ambiguous"
    assert {c.stock_code for c in r.candidates} == {"005930", "000660"}


def test_two_distinct_names_are_ambiguous():
    r = _curated().lookup("Samsung Electronics 와 Kakao 비교")
    assert r.status == "ambiguous"
    assert [c.stock_code for c in r.candidates] == ["005930", "035720"]   # 결정론 정렬


def test_source_miss_is_not_found():
    assert _curated().lookup("로제 관련 주식 어때?").status == "not_found"


# ── 다중 source: dedup vs ambiguous ─────────────────────────────────────────
def test_multi_source_same_code_dedups_to_single():
    src_a = CuratedFallbackSource((FallbackEntry("035720", "카카오", "KOSPI", ("Kakao",)),), name="a")
    src_b = CuratedFallbackSource((FallbackEntry("035720", "카카오", "KOSPI", ("KakaoCorp",)),), name="b")
    r = CompositeFallbackLookup([src_a, src_b]).lookup("Kakao 분석")
    assert r.status == "resolved" and r.stock.stock_code == "035720"     # 같은 code → dedup 단일


def test_multi_source_different_code_is_ambiguous():
    src_a = CuratedFallbackSource((FallbackEntry("035720", "카카오", "KOSPI", ("스페셜엑스",)),), name="a")
    src_b = CuratedFallbackSource((FallbackEntry("000660", "SK하이닉스", "KOSPI", ("스페셜엑스",)),), name="b")
    r = CompositeFallbackLookup([src_a, src_b]).lookup("스페셜엑스 분석")
    assert r.status == "ambiguous"
    assert {c.stock_code for c in r.candidates} == {"035720", "000660"}


def test_source_tool_error_propagates_as_fallback_error():
    class _Boom:
        name = "boom"

        def find(self, query):
            raise FallbackLookupError("boom")

    try:
        CompositeFallbackLookup([_Boom()]).lookup("아무거나")
        raise AssertionError("FallbackLookupError 가 전파돼야 한다")
    except FallbackLookupError:
        pass


# ── planner 통합: canonical 우선 + ephemeral 전파 ───────────────────────────
def test_canonical_resolved_skips_operational_fallback():
    resolver = FakeResolver(result=resolved("005930", "삼성전자"))
    decision = run_supervisor(
        SupervisorInput(query="삼성전자 차트 어때?"), resolver=resolver, fallback=_curated()
    )
    assert decision.resolution.used_fallback_lookup is False
    assert decision.resolution.source == "canonical_resolver" and decision.resolution.persisted is True


def test_canonical_not_found_uses_operational_fallback_ephemeral():
    resolver = FakeResolver(result=not_found())
    decision = run_supervisor(
        SupervisorInput(query="Samsung Electronics chart?"), resolver=resolver, fallback=_curated()
    )
    r = decision.resolution
    assert r.status == "resolved" and r.source == "fallback_lookup" and r.persisted is False
    assert r.stock.stock_code == "005930" and r.stock.persisted is False
    # ephemeral context 가 종목 의존 agent task 까지 전파.
    by = {t.agent_type: t for t in decision.tasks}
    for a in STOCK_DEPENDENT:
        assert by[a].can_run is True and by[a].context.stock_code == "005930"
        assert by[a].context.persisted is False and by[a].context.source == "fallback_lookup"
    for a in STOCK_OPTIONAL:
        assert by[a].can_run is True and by[a].context.persisted is False


def test_default_fallback_lookup_matches_english_major_name():
    # 배선 기본값(default_fallback_lookup)이 실제로 동작하는지(curated seed).
    r = default_fallback_lookup().lookup("SK Hynix outlook")
    assert r.status == "resolved" and r.stock.stock_code == "000660"


# ── no persistence (안전성) ─────────────────────────────────────────────────
def test_curated_source_is_read_only_and_pure():
    # 조회는 순수 함수 — 반복 호출이 같은 결과이고 entries 를 변형하지 않는다(정본 write 경로 없음).
    src = CuratedFallbackSource(_ENTRIES)
    first = src.find("Kakao 분석")
    second = src.find("Kakao 분석")
    assert first == second
    assert [isinstance(h, SourceHit) for h in first] == [True] * len(first)
    assert src._entries == _ENTRIES     # 원본 불변


def test_curated_entries_have_valid_six_digit_codes():
    # curated seed 는 근거 있는 6자리 코드만(임의 문자열/추정 코드 금지).
    for e in CURATED_FALLBACK_ENTRIES:
        assert len(e.stock_code) == 6 and e.stock_code.isdigit()
        assert e.stock_name
