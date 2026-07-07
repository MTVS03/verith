# tests/test_event_merge.py
"""services/event_merge.py + nodes/merge_event.py 테스트 (mock/fake 기반, 핵심 로직).

병합은 파이프라인에서 가장 까다로운 부분이라 계약·점수·판정 분기를 촘촘히 검증한다(event_merge.md §8).
기존 이벤트 조회는 fake RecentEventProvider 로 주입한다(실제 backend·DB 없음, 절대규칙 1). canonical 은
규칙 기반이라 LLM(services/llm.py)이 병합 경로에 없음도 확인한다(CLAUDE.md §2-4).

점수 공식: score = 0.6·summary + 0.3·company + 0.1·time, 임계값 0.7(config, 미만이면 신규).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

import services.event_merge as event_merge
import nodes.merge_event as merge_node_mod
from nodes.merge_event import merge_event_node
from schemas.article import Article, EventCandidate, ExtractResult
from schemas.event import CandidateEvent

_T = datetime(2026, 7, 6, tzinfo=timezone.utc)


class FakeProvider:
    """주입 가능한 후보 조회 시임. 고정 후보를 돌려주고 호출 인자를 기록한다(실제 backend 없음)."""

    def __init__(self, events: list[CandidateEvent]):
        self.events = events
        self.calls: list[tuple] = []

    def get_recent_events(self, companies, within_days):
        self.calls.append((companies, within_days))
        return list(self.events)


def _article(url: str, embedding, published_at=_T) -> Article:
    return Article(title="제목", url=url, embedding=embedding, published_at=published_at)


def _extract(summary="요약", companies=None, events=None, event_date=None) -> ExtractResult:
    return ExtractResult(
        summary=summary,
        companies=companies or [],
        events=events or [],
        event_date=event_date,
    )


def _cand(cid, emb, companies, event_time=_T) -> CandidateEvent:
    return CandidateEvent(canonical_id=cid, companies=companies, embedding=emb, event_time=event_time)


# ---------------------------------------------------------------------------
# score_candidate — 가중 점수·세부 점수
# ---------------------------------------------------------------------------
def test_score_candidate_weighted_sum_and_subscores():
    cand = _cand("e1", [1.0, 0.0], ["삼성전자"], event_time=_T)
    mc = event_merge.score_candidate([1.0, 0.0], ["삼성전자"], _T, cand)

    assert mc.event_id == "e1"
    assert mc.summary_similarity == pytest.approx(1.0)
    assert mc.company_overlap == pytest.approx(1.0)
    assert mc.time_similarity == pytest.approx(1.0)
    # 0.6·1 + 0.3·1 + 0.1·1 = 1.0
    assert mc.score == pytest.approx(1.0)


def test_score_candidate_company_mismatch_drops_score():
    cand = _cand("e1", [1.0, 0.0], ["SK하이닉스"], event_time=_T)
    mc = event_merge.score_candidate([1.0, 0.0], ["삼성전자"], _T, cand)
    assert mc.company_overlap == 0.0
    # 0.6·1 + 0.3·0 + 0.1·1 = 0.7
    assert mc.score == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# decide_merge — 편입/신규 분기
# ---------------------------------------------------------------------------
def test_decide_merge_incorporates_when_above_threshold():
    art = _article("https://ex.com/1", [1.0, 0.0])
    ext = _extract(companies=["삼성전자"], event_date=_T)
    provider = FakeProvider([_cand("evt-1", [1.0, 0.0], ["삼성전자"], event_time=_T)])

    decision = event_merge.decide_merge(art, ext, provider)

    assert decision.is_new_event is False
    assert decision.assigned_event_id == "evt-1"
    assert decision.best_score == pytest.approx(1.0)
    # 후보 조회는 회사·창(7일)으로 축소 요청된다.
    assert provider.calls == [(["삼성전자"], event_merge.MERGE_CANDIDATE_WINDOW_DAYS)]


def test_decide_merge_new_when_company_differs():
    # 회사가 완전히 다르면 overlap 0 → 점수 하락으로 신규(다른 회사 사건 병합 방지).
    art = _article("https://ex.com/1", [1.0, 0.0])
    ext = _extract(companies=["삼성전자"], event_date=None)  # 시간 신호도 없음
    provider = FakeProvider([_cand("evt-1", [1.0, 0.0], ["SK하이닉스"], event_time=None)])

    decision = event_merge.decide_merge(art, ext, provider)
    # 0.6·1 + 0.3·0 + 0.1·0 = 0.6 < 0.7
    assert decision.is_new_event is True
    assert decision.assigned_event_id is None
    assert decision.best_score == pytest.approx(0.6)


def test_decide_merge_new_when_no_candidates():
    art = _article("https://ex.com/1", [1.0, 0.0])
    ext = _extract(companies=["삼성전자"])
    provider = FakeProvider([])

    decision = event_merge.decide_merge(art, ext, provider)
    assert decision.is_new_event is True
    assert decision.assigned_event_id is None
    assert decision.best_score is None
    assert decision.candidates == []


def test_decide_merge_just_below_threshold_is_new():
    # 회사·시간 일치(0.4)로 고정하고 summary 유사도만 조절해 임계값 바로 아래로 만든다.
    # cos([1,0],[1,2]) = 1/sqrt(5) ≈ 0.447 → 0.4 + 0.6·0.447 ≈ 0.668 < 0.7 (억지 편입 금지 경계).
    art = _article("https://ex.com/1", [1.0, 0.0])
    ext = _extract(companies=["삼성전자"], event_date=_T)
    provider = FakeProvider([_cand("evt-1", [1.0, 2.0], ["삼성전자"], event_time=_T)])

    decision = event_merge.decide_merge(art, ext, provider)
    assert decision.is_new_event is True
    assert decision.best_score < event_merge.MERGE_THRESHOLD


def test_decide_merge_skip_when_no_embedding():
    art = _article("https://ex.com/1", None)  # 임베딩 없음(요약/임베딩 실패)
    ext = _extract(companies=["삼성전자"])
    provider = FakeProvider([_cand("evt-1", [1.0, 0.0], ["삼성전자"])])

    assert event_merge.decide_merge(art, ext, provider) is None
    assert provider.calls == []  # 후보 조회조차 하지 않는다


def test_decide_merge_uses_event_date_over_published_at():
    # event_date 가 후보 시각과 일치 → time_similarity=1. published_at 은 멀어도 무시된다(발생≠발행).
    art = _article("https://ex.com/1", [0.0, 1.0], published_at=_T + timedelta(days=100))
    ext = _extract(companies=["삼성전자"], event_date=_T)
    provider = FakeProvider([_cand("evt-1", [1.0, 0.0], ["삼성전자"], event_time=_T)])

    decision = event_merge.decide_merge(art, ext, provider)
    assert decision.candidates[0].time_similarity == pytest.approx(1.0)


def test_decide_merge_falls_back_to_published_at_when_no_event_date():
    art = _article("https://ex.com/1", [0.0, 1.0], published_at=_T)
    ext = _extract(companies=["삼성전자"], event_date=None)
    provider = FakeProvider([_cand("evt-1", [1.0, 0.0], ["삼성전자"], event_time=_T)])

    decision = event_merge.decide_merge(art, ext, provider)
    assert decision.candidates[0].time_similarity == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# canonical 생성 (규칙 기반, LLM 미사용)
# ---------------------------------------------------------------------------
def test_make_canonical_title_picks_top_confidence():
    ext = _extract(events=[
        EventCandidate(title="지분 매각", confidence=0.4),
        EventCandidate(title="HBM 공급 계약", confidence=0.9),
    ])
    assert event_merge.make_canonical_title(ext) == "HBM 공급 계약"


def test_make_canonical_title_fallback_to_summary_when_no_events():
    ext = _extract(summary="삼성전자가 미국 공장 투자를 결정했다", events=[])
    title = event_merge.make_canonical_title(ext)
    assert title.startswith("삼성전자가 미국 공장 투자")
    assert len(title) <= event_merge._FALLBACK_TITLE_MAX_CHARS


def test_new_event_shape():
    ext = _extract(
        companies=["삼성전자"],
        events=[EventCandidate(title="실적 발표", confidence=0.8)],
    )
    ev = event_merge.new_event(ext)

    assert ev.canonical_title == "실적 발표"       # 감성 평가어 없음(사건명)
    assert ev.companies == ["삼성전자"]
    assert ev.importance is None                    # TASK 06 에서 계산
    assert ev.created_at is not None
    # canonical_id 는 UUID4 형식
    assert UUID(ev.canonical_id).version == 4


def test_merge_path_does_not_use_llm():
    # 병합·canonical 경로에 LLM 부재(CLAUDE.md §2-4). 서비스/노드 소스에 services.llm 참조가 없다.
    import inspect
    assert "services.llm" not in inspect.getsource(event_merge)
    assert "services.llm" not in inspect.getsource(merge_node_mod)


# ---------------------------------------------------------------------------
# nodes/merge_event.merge_event_node
# ---------------------------------------------------------------------------
def _state(articles, extracts):
    """articles + extracts_by_url(url→ExtractResult) 상태를 만든다."""
    return {
        "articles": articles,
        "extracts_by_url": {str(a.url): ext for a, ext in zip(articles, extracts)},
    }


def test_node_new_event_assigns_and_registers():
    art = _article("https://ex.com/1", [1.0, 0.0])
    ext = _extract(companies=["삼성전자"], events=[EventCandidate(title="HBM 공급 계약", confidence=0.9)])

    state = merge_event_node(_state([art], [ext]))  # provider 미주입 → 기본(빈 후보) → 신규

    assert art.event_id is not None
    assert art.analysis_completed is True
    assert art.event_id in state["events_by_id"]
    assert state["events_by_id"][art.event_id].canonical_title == "HBM 공급 계약"


def test_node_incorporates_via_injected_provider():
    art = _article("https://ex.com/1", [1.0, 0.0])
    ext = _extract(companies=["삼성전자"], event_date=_T)
    provider = FakeProvider([_cand("evt-existing", [1.0, 0.0], ["삼성전자"], event_time=_T)])

    state = merge_event_node(_state([art], [ext]), provider=provider)

    assert art.event_id == "evt-existing"      # 기존 이벤트에 편입
    assert art.analysis_completed is True
    assert state["events_by_id"] == {}          # 신규 이벤트 없음


def test_node_second_same_event_merges_into_first_batch_event():
    # 같은 배치·동일 사건 둘째 기사가 첫째가 만든 신규 이벤트에 편입된다(배치 내 중복 신규 방지, §7).
    a1 = _article("https://ex.com/1", [1.0, 0.0])
    a2 = _article("https://ex.com/2", [1.0, 0.0])
    ext = _extract(companies=["삼성전자"], event_date=_T,
                   events=[EventCandidate(title="HBM 공급 계약", confidence=0.9)])

    state = merge_event_node(_state([a1, a2], [ext, ext]))  # provider 미주입(빈 backend)

    assert a1.event_id is not None
    assert a2.event_id == a1.event_id             # 둘째가 첫째 이벤트로 편입
    assert len(state["events_by_id"]) == 1        # 신규 이벤트는 하나뿐


def test_node_skips_article_without_embedding():
    good = _article("https://ex.com/good", [1.0, 0.0])
    bad = _article("https://ex.com/bad", None)     # 임베딩 없음 → 병합 skip
    ext = _extract(companies=["삼성전자"])

    merge_event_node(_state([good, bad], [ext, ext]))

    assert good.event_id is not None and good.analysis_completed is True
    assert bad.event_id is None and bad.analysis_completed is False


def test_node_isolates_single_failure(monkeypatch):
    a1 = _article("https://ex.com/1", [1.0, 0.0])
    a2 = _article("https://ex.com/2", [1.0, 0.0])
    ext = _extract(companies=["삼성전자"])

    calls = {"n": 0}
    real_decide = event_merge.decide_merge

    def flaky_decide(article, extract, provider):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")   # 첫 기사 실패
        return real_decide(article, extract, provider)

    monkeypatch.setattr(merge_node_mod.event_merge, "decide_merge", flaky_decide)

    merge_event_node(_state([a1, a2], [ext, ext]))

    assert a1.event_id is None and a1.analysis_completed is False   # 실패 격리
    assert a2.event_id is not None and a2.analysis_completed is True


def test_node_zero_articles_passes():
    state = merge_event_node({"articles": [], "extracts_by_url": {}})
    assert state["events_by_id"] == {}


def test_node_missing_articles_key():
    state = merge_event_node({})
    assert state["events_by_id"] == {}
