# tests/test_extract_node.py
"""nodes/extract.py 테스트 (mock 기반). llm.extract 를 monkeypatch 해 노드의 순회·격리·매핑만 검증한다.

노드는 얇은 껍데기이므로 여기서는 (1) state["extracts_by_url"] 가 url 기준으로 채워지는지,
(2) 한 기사 실패(None·예외)가 나머지 처리를 막지 않는지, (3) 0건 통과를 확인한다.
"""
from __future__ import annotations

import src.agents.news.nodes.extract as extract_node_mod
from src.agents.news.nodes.extract import extract_node
from src.agents.news.schemas.article import Article, ExtractResult, SourceType


def _article(url: str, title: str = "제목") -> Article:
    return Article(title=title, url=url)


def test_node_populates_extracts_by_url(monkeypatch):
    a1 = _article("https://ex.com/1", "기사1")
    a2 = _article("https://ex.com/2", "기사2")

    def fake_extract(article):
        return ExtractResult(summary=f"요약:{article.title}", source_type=SourceType.ARTICLE)

    monkeypatch.setattr(extract_node_mod.llm, "extract", fake_extract)

    state = extract_node({"articles": [a1, a2]})

    mapping = state["extracts_by_url"]
    assert set(mapping) == {"https://ex.com/1", "https://ex.com/2"}
    assert mapping["https://ex.com/1"].summary == "요약:기사1"
    # summary 는 Article 에도 반영된다.
    assert a1.summary == "요약:기사1"


def test_node_isolates_failures(monkeypatch):
    ok = _article("https://ex.com/ok", "정상")
    none_art = _article("https://ex.com/none", "스킵")
    boom = _article("https://ex.com/boom", "폭발")

    def fake_extract(article):
        if article.title == "스킵":
            return None                 # skip 신호
        if article.title == "폭발":
            raise RuntimeError("boom")  # 예외도 격리되어야
        return ExtractResult(summary="ok", source_type=SourceType.ARTICLE)

    monkeypatch.setattr(extract_node_mod.llm, "extract", fake_extract)

    state = extract_node({"articles": [ok, none_art, boom]})

    # 실패 2건은 skip, 정상 1건만 매핑에 남는다(파이프라인은 계속).
    assert set(state["extracts_by_url"]) == {"https://ex.com/ok"}


def test_node_zero_articles_passes(monkeypatch):
    monkeypatch.setattr(extract_node_mod.llm, "extract",
                        lambda a: (_ for _ in ()).throw(AssertionError("불려선 안 됨")))

    state = extract_node({"articles": []})

    assert state["extracts_by_url"] == {}


def test_node_missing_articles_key(monkeypatch):
    # articles 키가 아예 없어도 예외 없이 통과.
    state = extract_node({})
    assert state["extracts_by_url"] == {}
