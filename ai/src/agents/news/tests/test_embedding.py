# tests/test_embedding.py
"""services/embedder.py + utils/similarity.py + nodes/embedding.py 테스트 (mock 기반).

실제 임베딩 모델·네트워크를 부르지 않는다(CLAUDE.md: tests 는 mock). 저수준 인코딩 시임
embedder._embed_raw 를 monkeypatch 해 고정 벡터를 돌려주고, 계약(순서·길이 일치·배치 실패 시 개별
fallback·빈/None 처리)과 유사도 순수 함수(코사인·회사 중복도·시간 근접도)를 검증한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import src.agents.news.services.embedder as embedder
import src.agents.news.nodes.embedding as embedding_node_mod
from src.agents.news.nodes.embedding import embedding_node
from src.agents.news.schemas.article import Article
from src.agents.news.utils.similarity import company_overlap, cosine_similarity, time_proximity


def _article(url: str, summary: str | None) -> Article:
    return Article(title="제목", url=url, summary=summary)


# ---------------------------------------------------------------------------
# services/embedder.embed
# ---------------------------------------------------------------------------
def test_embed_returns_vector(monkeypatch):
    monkeypatch.setattr(embedder, "_embed_raw", lambda texts: [[0.1, 0.2, 0.3]])
    vec = embedder.embed("삼성전자가 HBM 공급 계약을 체결했다")
    assert vec == [0.1, 0.2, 0.3]


def test_embed_empty_or_none_no_model_call(monkeypatch):
    monkeypatch.setattr(embedder, "_embed_raw",
                        lambda texts: (_ for _ in ()).throw(AssertionError("빈 입력에서 모델 호출 금지")))
    assert embedder.embed("") is None
    assert embedder.embed("   ") is None
    assert embedder.embed(None) is None


def test_embed_truncates_input(monkeypatch):
    captured: dict = {}

    def fake_raw(texts):
        captured["texts"] = texts
        return [[1.0]]

    monkeypatch.setattr(embedder, "_embed_raw", fake_raw)
    embedder.embed("가" * (embedder.EMBED_MAX_INPUT_CHARS + 500))
    assert len(captured["texts"][0]) == embedder.EMBED_MAX_INPUT_CHARS


def test_embed_no_prefix_added(monkeypatch):
    # 대칭 비교라 query/document 프리픽스를 붙이지 않는다(model_choice §3). 원문 그대로 들어간다.
    captured: dict = {}

    def fake_raw(texts):
        captured["texts"] = texts
        return [[0.0]]

    monkeypatch.setattr(embedder, "_embed_raw", fake_raw)
    embedder.embed("원문요약")
    assert captured["texts"] == ["원문요약"]


def test_embed_inference_error_returns_none(monkeypatch):
    monkeypatch.setattr(embedder, "_embed_raw",
                        lambda texts: (_ for _ in ()).throw(RuntimeError("model down")))
    assert embedder.embed("본문") is None


# ---------------------------------------------------------------------------
# services/embedder.embed_batch
# ---------------------------------------------------------------------------
def test_embed_batch_preserves_order(monkeypatch):
    monkeypatch.setattr(embedder, "_embed_raw", lambda texts: [[1.0], [2.0], [3.0]])
    vs = embedder.embed_batch(["a", "b", "c"])
    assert vs == [[1.0], [2.0], [3.0]]


def test_embed_batch_empty_list(monkeypatch):
    monkeypatch.setattr(embedder, "_embed_raw",
                        lambda texts: (_ for _ in ()).throw(AssertionError("불려선 안 됨")))
    assert embedder.embed_batch([]) == []


def test_embed_batch_skips_empty_keeping_order(monkeypatch):
    seen: dict = {}

    def fake_raw(texts):
        seen["texts"] = texts
        return [[float(len(t))] for t in texts]

    monkeypatch.setattr(embedder, "_embed_raw", fake_raw)
    results = embedder.embed_batch(["요약A", "", "요약BB"])

    assert len(results) == 3
    assert seen["texts"] == ["요약A", "요약BB"]     # 빈 입력은 모델에 안 들어감
    assert results[0] is not None and results[1] is None and results[2] is not None


def test_embed_batch_falls_back_per_item_on_batch_failure(monkeypatch):
    calls = {"batch": 0, "single": 0}

    def fake_raw(texts):
        if len(texts) > 1:
            calls["batch"] += 1
            raise RuntimeError("OOM")
        calls["single"] += 1
        return [[9.0]]

    monkeypatch.setattr(embedder, "_embed_raw", fake_raw)
    results = embedder.embed_batch(["x", "y"])

    assert calls["batch"] == 1        # 배치 1회 시도 후
    assert calls["single"] == 2       # 건별 fallback
    assert results == [[9.0], [9.0]]


def test_embed_batch_length_mismatch_triggers_fallback(monkeypatch):
    def fake_raw(texts):
        if len(texts) > 1:
            return [[1.0]]            # 2건 요청에 1건만(계약 위반)
        return [[7.0]]

    monkeypatch.setattr(embedder, "_embed_raw", fake_raw)
    results = embedder.embed_batch(["a", "b"])
    assert results == [[7.0], [7.0]]


# ---------------------------------------------------------------------------
# utils/similarity (순수 함수 — mock 불필요)
# ---------------------------------------------------------------------------
def test_cosine_identical_is_one():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0


def test_cosine_orthogonal_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_opposite_clamped_to_zero():
    # 음수 코사인은 병합 신호 없음(0)으로 clamp.
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == 0.0


def test_cosine_zero_vector_is_zero():
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert cosine_similarity([], [1.0]) == 0.0


def test_cosine_dimension_mismatch_raises():
    import pytest
    with pytest.raises(ValueError):
        cosine_similarity([1.0, 2.0], [1.0])


def test_company_overlap_partial_jaccard():
    # {삼성전자, SK하이닉스} ∩ {삼성전자} = 1, ∪ = 2 → 0.5
    assert company_overlap(["삼성전자", "SK하이닉스"], ["삼성전자"]) == 0.5


def test_company_overlap_identical_is_one():
    assert company_overlap(["삼성전자"], ["삼성전자"]) == 1.0


def test_company_overlap_empty_side_is_zero():
    assert company_overlap([], ["삼성전자"]) == 0.0
    assert company_overlap(["삼성전자"], []) == 0.0


def test_company_overlap_normalizes_corp_tokens():
    # ㈜/(주) 표기와 공백 차이는 정규화로 같아진다(TASK 07 노드 key 와 동일 기준).
    assert company_overlap(["㈜카카오"], ["카카오"]) == 1.0
    assert company_overlap([" 삼성  전자 "], ["삼성 전자"]) == 1.0


def test_time_proximity_same_time_is_one():
    t = datetime(2026, 7, 6, tzinfo=timezone.utc)
    assert time_proximity(t, t) == 1.0


def test_time_proximity_decays_with_distance():
    t = datetime(2026, 7, 6, tzinfo=timezone.utc)
    near = time_proximity(t, t + timedelta(days=1))
    far = time_proximity(t, t + timedelta(days=10))
    assert 0.0 < far < near < 1.0


def test_time_proximity_none_is_zero():
    t = datetime(2026, 7, 6, tzinfo=timezone.utc)
    assert time_proximity(None, t) == 0.0
    assert time_proximity(t, None) == 0.0
    assert time_proximity(None, None) == 0.0


def test_time_proximity_aware_naive_mix_is_zero():
    aware = datetime(2026, 7, 6, tzinfo=timezone.utc)
    naive = datetime(2026, 7, 6)
    assert time_proximity(aware, naive) == 0.0


# ---------------------------------------------------------------------------
# nodes/embedding.embedding_node
# ---------------------------------------------------------------------------
def test_node_embeds_summary_articles(monkeypatch):
    a1 = _article("https://ex.com/1", "요약1")
    a2 = _article("https://ex.com/2", "요약2")

    monkeypatch.setattr(embedding_node_mod.embedder, "embed_batch",
                        lambda texts: [[1.0], [2.0]])

    embedding_node({"articles": [a1, a2]})

    assert a1.embedding == [1.0]
    assert a2.embedding == [2.0]


def test_node_skips_articles_without_summary(monkeypatch):
    has = _article("https://ex.com/has", "요약")
    empty = _article("https://ex.com/empty", "")
    none = _article("https://ex.com/none", None)

    seen: dict = {}

    def fake_batch(texts):
        seen["texts"] = texts
        return [[5.0]]

    monkeypatch.setattr(embedding_node_mod.embedder, "embed_batch", fake_batch)
    embedding_node({"articles": [has, empty, none]})

    assert seen["texts"] == ["요약"]      # summary 있는 기사만 대상
    assert has.embedding == [5.0]
    assert empty.embedding is None and none.embedding is None


def test_node_isolates_single_failure(monkeypatch):
    a1 = _article("https://ex.com/1", "요약1")
    a2 = _article("https://ex.com/2", "요약2")

    # 두 번째 기사는 임베딩 실패(None) — 나머지는 계속 반영.
    monkeypatch.setattr(embedding_node_mod.embedder, "embed_batch",
                        lambda texts: [[1.0], None])

    embedding_node({"articles": [a1, a2]})
    assert a1.embedding == [1.0]
    assert a2.embedding is None


def test_node_zero_targets_passes(monkeypatch):
    none = _article("https://ex.com/none", None)
    monkeypatch.setattr(embedding_node_mod.embedder, "embed_batch",
                        lambda texts: (_ for _ in ()).throw(AssertionError("불려선 안 됨")))
    state = embedding_node({"articles": [none]})
    assert none.embedding is None
    assert state["articles"] == [none]


def test_node_missing_articles_key():
    state = embedding_node({})
    assert state == {}
