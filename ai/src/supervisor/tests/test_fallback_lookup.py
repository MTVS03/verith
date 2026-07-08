"""fallback lookup 경계 테스트 (fake resolver/fallback, 실 네트워크 없음).

절대 원칙 검증: **ephemeral resolve 허용 / persistent write 금지.** fallback 은 canonical not_found 일
때만 보조로 타고, 결과는 항상 persisted=False. 후보 다수면 자동선택하지 않는다.
"""

from __future__ import annotations

from src.supervisor.planning.fallback_lookup import StaticFallbackLookup
from src.supervisor.planning.planner import run_supervisor
from src.supervisor.planning.policy import STOCK_DEPENDENT, STOCK_OPTIONAL
from src.supervisor.schemas import AGENT_ORDER, StockContext, SupervisorInput
from src.supervisor.tests._fakes import (
    FakeFallback,
    FakeResolver,
    ambiguous,
    fb_ambiguous,
    fb_not_found,
    fb_resolved,
    not_found,
    resolved,
)


def _tasks_by_agent(decision):
    return {t.agent_type: t for t in decision.tasks}


# ── planning / resolution 분기 ──────────────────────────────────────────────
def test_canonical_resolved_does_not_call_fallback():
    resolver = FakeResolver(result=resolved("005930", "삼성전자"))
    fallback = FakeFallback(result=fb_resolved("000000", "오염"))
    decision = run_supervisor(
        SupervisorInput(query="삼성전자 차트 어때?"), resolver=resolver, fallback=fallback
    )
    assert fallback.calls == []                              # canonical 성공 → fallback 미호출
    assert decision.resolution.used_fallback_lookup is False
    assert decision.resolution.source == "canonical_resolver"
    assert decision.resolution.persisted is True
    assert decision.resolution.stock.stock_code == "005930"


def test_canonical_not_found_triggers_fallback():
    resolver = FakeResolver(result=not_found())
    fallback = FakeFallback(result=fb_resolved("035720", "카카오"))
    decision = run_supervisor(
        SupervisorInput(query="카카오 분석해줘"), resolver=resolver, fallback=fallback
    )
    assert fallback.calls == ["카카오 분석해줘"]           # not_found 일 때만 시도
    assert decision.resolution.used_fallback_lookup is True


def test_fallback_high_confidence_single_resolves_ephemeral():
    resolver = FakeResolver(result=not_found())
    fallback = FakeFallback(result=fb_resolved("035720", "카카오"))
    decision = run_supervisor(
        SupervisorInput(query="카카오 분석해줘"), resolver=resolver, fallback=fallback
    )
    r = decision.resolution
    assert r.status == "resolved"
    assert r.source == "fallback_lookup" and r.persisted is False   # 정본 아님(ephemeral)
    assert r.stock.stock_code == "035720" and r.stock.stock_name == "카카오"
    assert r.stock.source == "fallback_lookup" and r.stock.persisted is False


def test_fallback_ambiguous_does_not_autoselect():
    resolver = FakeResolver(result=not_found())
    fallback = FakeFallback(result=fb_ambiguous(("035720", "카카오"), ("323410", "카카오뱅크")))
    decision = run_supervisor(
        SupervisorInput(query="카카오 관련 주식"), resolver=resolver, fallback=fallback
    )
    r = decision.resolution
    assert r.status == "ambiguous" and r.stock is None              # 자동선택 금지
    assert {c.stock_code for c in r.candidates} == {"035720", "323410"}
    assert r.source == "fallback_lookup"


def test_fallback_not_found_keeps_not_found():
    resolver = FakeResolver(result=not_found())
    fallback = FakeFallback(result=fb_not_found())
    decision = run_supervisor(
        SupervisorInput(query="로제 관련 주식 어때?"), resolver=resolver, fallback=fallback
    )
    r = decision.resolution
    assert r.status == "not_found" and r.used_fallback_lookup is True
    assert r.stock is None


def test_fallback_tool_error_degrades_to_not_found_not_error():
    resolver = FakeResolver(result=not_found())
    fallback = FakeFallback(raise_error=True)
    decision = run_supervisor(
        SupervisorInput(query="카카오 분석해줘"), resolver=resolver, fallback=fallback
    )
    r = decision.resolution
    # fallback 도구 장애는 canonical not_found 를 error 로 바꾸지 않는다(보조 경로).
    assert r.status == "not_found" and r.used_fallback_lookup is True


def test_canonical_error_does_not_trigger_fallback():
    resolver = FakeResolver(raise_kind="timeout")
    fallback = FakeFallback(result=fb_resolved("035720", "카카오"))
    decision = run_supervisor(
        SupervisorInput(query="카카오 분석해줘"), resolver=resolver, fallback=fallback
    )
    assert fallback.calls == []                              # error 에서는 fallback 자동 시도 안 함
    assert decision.resolution.status == "error"
    assert decision.resolution.used_fallback_lookup is False


def test_canonical_ambiguous_does_not_trigger_fallback():
    resolver = FakeResolver(result=ambiguous(("006040", "동원산업"), ("049770", "동원F&B")))
    fallback = FakeFallback(result=fb_resolved("035720", "카카오"))
    decision = run_supervisor(
        SupervisorInput(query="동원 수급 어때?"), resolver=resolver, fallback=fallback
    )
    assert fallback.calls == []
    assert decision.resolution.status == "ambiguous"
    assert decision.resolution.used_fallback_lookup is False


def test_non_stock_query_never_calls_fallback():
    fallback = FakeFallback(result=fb_resolved("035720", "카카오"))
    decision = run_supervisor(
        SupervisorInput(query="2차전지 산업 전망 알려줘"), resolver=None, fallback=fallback
    )
    assert fallback.calls == []                              # not_attempted → fallback 미호출
    assert decision.resolution.status == "not_attempted"
    assert decision.resolution.used_fallback_lookup is False


# ── execution / task envelope ───────────────────────────────────────────────
def test_ephemeral_context_flows_to_stock_dependent_tasks():
    resolver = FakeResolver(result=not_found())
    fallback = FakeFallback(result=fb_resolved("035720", "카카오"))
    decision = run_supervisor(
        SupervisorInput(query="카카오 차트 보여줘"), resolver=resolver, fallback=fallback
    )
    assert len(decision.tasks) == 5
    assert [t.agent_type for t in decision.tasks] == list(AGENT_ORDER)
    by = _tasks_by_agent(decision)
    # 종목 의존 agent 는 ephemeral context 로 실행 가능해진다.
    for a in STOCK_DEPENDENT:
        assert by[a].can_run is True and by[a].reason == "stock_resolved"
        assert by[a].context.stock_code == "035720"
        assert by[a].context.persisted is False              # ephemeral 표기가 task 까지 전달
        assert by[a].context.source == "fallback_lookup"
        assert "카카오" in by[a].rewritten_query
    # 종목이 (ephemeral 로) 확정됐으므로 news/industry 도 그 종목 context 로 실행된다
    # (decide: status=resolved 면 모든 agent 가 stock_resolved). 기존 fan-out 정책 그대로.
    for a in STOCK_OPTIONAL:
        assert by[a].can_run is True and by[a].reason == "stock_resolved"
        assert by[a].context.persisted is False              # optional agent context 도 ephemeral


def test_original_query_preserved_through_fallback():
    q = "카카오 지금 차트상 어때?"
    resolver = FakeResolver(result=not_found())
    fallback = FakeFallback(result=fb_resolved("035720", "카카오"))
    decision = run_supervisor(SupervisorInput(query=q), resolver=resolver, fallback=fallback)
    assert decision.original_query == q


# ── 안전성 ─────────────────────────────────────────────────────────────────
def test_no_fallback_injected_behaves_like_today():
    # fallback 미주입이면 canonical not_found 가 그대로 유지된다(오늘 동작 무변경).
    resolver = FakeResolver(result=not_found())
    decision = run_supervisor(SupervisorInput(query="카카오 분석해줘"), resolver=resolver)
    assert decision.resolution.status == "not_found"
    assert decision.resolution.used_fallback_lookup is False


def test_static_fallback_empty_default_never_hallucinates():
    # 기본 entries 는 비어 있어 어떤 문자열도 근거 없이 resolved 되지 않는다.
    lookup = StaticFallbackLookup()
    assert lookup.lookup("삼성전자 같은 것 같음").status == "not_found"
    assert lookup.lookup("로제 관련 주식").status == "not_found"


def test_static_fallback_exact_single_and_ambiguous_and_none():
    entries = {
        "카카오톡": StockContext(stock_code="035720", stock_name="카카오", market="KOSPI"),
        "kakao corp": StockContext(stock_code="035720", stock_name="카카오"),   # 같은 종목 → 중복 아님
        "동원": StockContext(stock_code="006040", stock_name="동원산업"),
        "동원에프앤비": StockContext(stock_code="049770", stock_name="동원F&B"),
    }
    lookup = StaticFallbackLookup(entries)
    # 단일 exact(정규화: 대소문자/공백 무시).
    single = lookup.lookup("KAKAO Corp 분석")
    assert single.status == "resolved" and single.stock.stock_code == "035720"
    # 서로 다른 stock_code 2개 → ambiguous, 자동선택 금지, 결정론 정렬.
    amb = lookup.lookup("동원 그리고 동원에프앤비")
    assert amb.status == "ambiguous"
    assert [c.stock_code for c in amb.candidates] == ["006040", "049770"]
    # 매칭 없음 → not_found.
    assert lookup.lookup("전혀없는이름").status == "not_found"
