# tests/test_sentiment.py
"""services/finbert.py + nodes/sentiment.py 테스트 (mock 기반).

실제 모델·네트워크를 부르지 않는다(CLAUDE.md: tests 는 mock). 저수준 추론 시임 finbert._infer_raw 를
monkeypatch 해 고정 라벨·확률을 돌려주고, 매핑·분기·계약(순서 일치·실패 격리·skip)을 검증한다.
감성 판정 경로에 LLM(services/llm.py)이 없음을 함께 확인한다(CLAUDE.md §2-4).
"""
from __future__ import annotations

import src.agents.news.services.finbert as finbert
import src.agents.news.nodes.sentiment as sentiment_node_mod
from src.agents.news.nodes.sentiment import sentiment_node
from src.agents.news.schemas.article import Article, Sentiment


def _article(url: str, content: str | None, crawl_status: str = "success") -> Article:
    art = Article(title="제목", url=url, content=content, crawl_status=crawl_status)
    art.content_available = crawl_status == "success"
    return art


# ---------------------------------------------------------------------------
# services/finbert.classify
# ---------------------------------------------------------------------------
def test_classify_maps_label_and_score(monkeypatch):
    monkeypatch.setattr(finbert, "_infer_raw", lambda texts: [{"label": "positive", "score": 0.97}])

    result = finbert.classify("삼성전자 실적이 시장 예상을 크게 웃돌았다")

    assert result is not None
    assert result.sentiment is Sentiment.POSITIVE
    assert result.score == 0.97


def test_classify_maps_negative(monkeypatch):
    monkeypatch.setattr(finbert, "_infer_raw", lambda texts: [{"label": "negative", "score": 0.88}])
    result = finbert.classify("어닝쇼크로 주가가 급락했다")
    assert result.sentiment is Sentiment.NEGATIVE
    assert result.score == 0.88


def test_classify_label_case_insensitive(monkeypatch):
    # 모델 라벨 대소문자·공백이 달라도 매핑된다(정규화).
    monkeypatch.setattr(finbert, "_infer_raw", lambda texts: [{"label": " NEUTRAL ", "score": 0.5}])
    result = finbert.classify("실적을 발표했다")
    assert result.sentiment is Sentiment.NEUTRAL


def test_classify_truncates_input(monkeypatch):
    captured: dict = {}

    def fake_infer(texts):
        captured["texts"] = texts
        return [{"label": "neutral", "score": 0.6}]

    monkeypatch.setattr(finbert, "_infer_raw", fake_infer)
    long_text = "가" * (finbert.FINBERT_MAX_INPUT_CHARS + 500)
    finbert.classify(long_text)

    # 입력이 상한으로 잘려 들어간다(512 토큰 한계).
    assert len(captured["texts"][0]) == finbert.FINBERT_MAX_INPUT_CHARS


def test_classify_boundary_length_not_truncated(monkeypatch):
    captured: dict = {}

    def fake_infer(texts):
        captured["texts"] = texts
        return [{"label": "neutral", "score": 1.0}]

    monkeypatch.setattr(finbert, "_infer_raw", fake_infer)
    exact = "나" * finbert.FINBERT_MAX_INPUT_CHARS
    finbert.classify(exact)
    # 경계 길이(정확히 상한)는 그대로 들어간다.
    assert len(captured["texts"][0]) == finbert.FINBERT_MAX_INPUT_CHARS


def test_classify_empty_input_no_model_call(monkeypatch):
    def boom(texts):
        raise AssertionError("빈 입력에서 모델을 부르면 안 됨")

    monkeypatch.setattr(finbert, "_infer_raw", boom)
    assert finbert.classify("") is None
    assert finbert.classify("   ") is None
    assert finbert.classify(None) is None  # type: ignore[arg-type]


def test_classify_unmapped_label_returns_none(monkeypatch):
    # 예상 밖 라벨 → 실패 신호(None), 임의 중립 강제 없음.
    monkeypatch.setattr(finbert, "_infer_raw", lambda texts: [{"label": "LABEL_9", "score": 0.9}])
    assert finbert.classify("무언가") is None


def test_classify_confidence_boundaries(monkeypatch):
    for score in (0.0, 1.0):
        monkeypatch.setattr(finbert, "_infer_raw", lambda texts, s=score: [{"label": "neutral", "score": s}])
        result = finbert.classify("경계값")
        assert result is not None
        assert result.score == score


def test_classify_inference_error_returns_none(monkeypatch):
    def boom(texts):
        raise RuntimeError("model down")

    monkeypatch.setattr(finbert, "_infer_raw", boom)
    assert finbert.classify("본문") is None


# ---------------------------------------------------------------------------
# services/finbert.classify_batch
# ---------------------------------------------------------------------------
def test_classify_batch_preserves_order(monkeypatch):
    monkeypatch.setattr(finbert, "_infer_raw", lambda texts: [
        {"label": "positive", "score": 0.9},
        {"label": "negative", "score": 0.8},
        {"label": "neutral", "score": 0.7},
    ])

    results = finbert.classify_batch(["호재", "악재", "중립"])

    assert [r.sentiment for r in results] == [Sentiment.POSITIVE, Sentiment.NEGATIVE, Sentiment.NEUTRAL]
    assert [r.score for r in results] == [0.9, 0.8, 0.7]


def test_classify_batch_empty_list(monkeypatch):
    monkeypatch.setattr(finbert, "_infer_raw", lambda texts: (_ for _ in ()).throw(AssertionError("불려선 안 됨")))
    assert finbert.classify_batch([]) == []


def test_classify_batch_skips_empty_inputs_keeping_order(monkeypatch):
    # 빈 입력은 배치에서 제외되지만 자리(None)는 유지되어 길이·순서가 입력과 일치한다.
    seen: dict = {}

    def fake_infer(texts):
        seen["texts"] = texts
        return [{"label": "positive", "score": 0.9} for _ in texts]

    monkeypatch.setattr(finbert, "_infer_raw", fake_infer)
    results = finbert.classify_batch(["본문A", "", "본문B"])

    assert len(results) == 3
    assert seen["texts"] == ["본문A", "본문B"]     # 빈 입력은 모델에 안 들어감
    assert results[0] is not None and results[1] is None and results[2] is not None


def test_classify_batch_falls_back_per_item_on_batch_failure(monkeypatch):
    calls = {"batch": 0, "single": 0}

    def fake_infer(texts):
        # 배치(2건 이상) 호출은 실패, 개별(1건) fallback 은 성공하도록.
        if len(texts) > 1:
            calls["batch"] += 1
            raise RuntimeError("OOM")
        calls["single"] += 1
        return [{"label": "positive" if texts[0] == "ok" else "bogus", "score": 0.9}]

    monkeypatch.setattr(finbert, "_infer_raw", fake_infer)
    results = finbert.classify_batch(["ok", "bad", "ok"])

    assert calls["batch"] == 1        # 배치 1회 시도 후
    assert calls["single"] == 3       # 건별 fallback
    # "bad" 는 매핑 밖 라벨 → None 으로 격리, 나머지는 정상.
    assert results[0] is not None and results[0].sentiment is Sentiment.POSITIVE
    assert results[1] is None
    assert results[2] is not None


def test_classify_batch_length_mismatch_triggers_fallback(monkeypatch):
    # 파이프라인이 입력보다 짧은 결과를 주면 계약 위반 → 개별 fallback 으로 길이·순서 복구.
    def fake_infer(texts):
        if len(texts) > 1:
            return [{"label": "positive", "score": 0.9}]  # 2건 요청에 1건만 반환(위반)
        return [{"label": "neutral", "score": 0.5}]

    monkeypatch.setattr(finbert, "_infer_raw", fake_infer)
    results = finbert.classify_batch(["a", "b"])
    assert len(results) == 2
    assert all(r is not None for r in results)


# ---------------------------------------------------------------------------
# nodes/sentiment.sentiment_node
# ---------------------------------------------------------------------------
def test_node_scores_success_articles(monkeypatch):
    a1 = _article("https://ex.com/1", "본문1", crawl_status="success")
    a2 = _article("https://ex.com/2", "본문2", crawl_status="success")

    monkeypatch.setattr(sentiment_node_mod.finbert, "classify_batch", lambda texts: [
        _sr(Sentiment.POSITIVE, 0.9), _sr(Sentiment.NEGATIVE, 0.7),
    ])

    sentiment_node({"articles": [a1, a2]})

    assert a1.sentiment is Sentiment.POSITIVE and a1.sentiment_score == 0.9
    assert a2.sentiment is Sentiment.NEGATIVE and a2.sentiment_score == 0.7


def test_node_skips_no_content_and_failed(monkeypatch):
    ok = _article("https://ex.com/ok", "본문", crawl_status="success")
    breaking = _article("https://ex.com/breaking", None, crawl_status="no_content")
    failed = _article("https://ex.com/failed", None, crawl_status="failed")

    seen: dict = {}

    def fake_batch(texts):
        seen["texts"] = texts
        return [_sr(Sentiment.NEUTRAL, 0.6)]

    monkeypatch.setattr(sentiment_node_mod.finbert, "classify_batch", fake_batch)

    sentiment_node({"articles": [ok, breaking, failed]})

    # 본문 있는 기사만 모델에 들어간다(제목 추론 금지).
    assert seen["texts"] == ["본문"]
    assert ok.sentiment is Sentiment.NEUTRAL
    assert breaking.sentiment is None and breaking.sentiment_score is None
    assert failed.sentiment is None and failed.sentiment_score is None
    # 상태 필드는 감성 단계에서 바뀌지 않는다.
    assert ok.crawl_status == "success"


def test_node_isolates_single_failure(monkeypatch):
    a1 = _article("https://ex.com/1", "본문1", crawl_status="success")
    a2 = _article("https://ex.com/2", "본문2", crawl_status="success")

    # 두 번째 기사는 감성 실패(None) — 나머지는 계속 반영된다.
    monkeypatch.setattr(sentiment_node_mod.finbert, "classify_batch",
                        lambda texts: [_sr(Sentiment.POSITIVE, 0.9), None])

    sentiment_node({"articles": [a1, a2]})

    assert a1.sentiment is Sentiment.POSITIVE
    assert a2.sentiment is None and a2.sentiment_score is None


def test_node_no_content_articles_pass(monkeypatch):
    breaking = _article("https://ex.com/b", None, crawl_status="no_content")

    def boom(texts):
        raise AssertionError("본문 없는 기사뿐이면 모델을 부르면 안 됨")

    monkeypatch.setattr(sentiment_node_mod.finbert, "classify_batch", boom)

    state = sentiment_node({"articles": [breaking]})
    assert breaking.sentiment is None
    assert state["articles"] == [breaking]


def test_node_zero_articles_passes(monkeypatch):
    monkeypatch.setattr(sentiment_node_mod.finbert, "classify_batch",
                        lambda texts: (_ for _ in ()).throw(AssertionError("불려선 안 됨")))
    state = sentiment_node({"articles": []})
    assert state["articles"] == []


def test_node_missing_articles_key():
    state = sentiment_node({})
    assert state == {}


def test_node_does_not_import_llm():
    # 감성 판정 경로에 LLM 부재(CLAUDE.md §2-4). 노드/서비스 소스에 services.llm 참조가 없다.
    import inspect
    assert "services.llm" not in inspect.getsource(sentiment_node_mod)
    assert "services.llm" not in inspect.getsource(finbert)


def _sr(sentiment: Sentiment, score: float):
    from src.agents.news.schemas.article import SentimentResult
    return SentimentResult(sentiment=sentiment, score=score)
