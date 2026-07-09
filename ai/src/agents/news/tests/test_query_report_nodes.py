# tests/test_query_report_nodes.py — 얇은 노드(TASK 09) 테스트
"""query_node/report_node 가 서비스만 호출하고(backend·LLM 직접 호출 없음), 한 단계 실패해도
예외 없이 '데이터 제한' 리포트로 통과하며 state["report_json"](JSON 계약)을 채우는지 검증한다.
"""
from __future__ import annotations

from pathlib import Path

import src.agents.news.nodes.query as query_node_mod
import src.agents.news.nodes.report as report_node_mod
import src.agents.news.services.answer_generator as answer_generator
import src.agents.news.services.graph_query as graph_query
import src.agents.news.services.query_understanding as query_understanding
from src.agents.news.schemas.query import Answer, QueryIntent, QueryUnderstanding
from src.agents.news.schemas.response import SubjectQueryResponse


def test_query_node_calls_services_in_order(monkeypatch):
    seen = {}

    def fake_understand(q):
        seen["q"] = q
        return QueryUnderstanding(companies=["삼성전자"], intent=QueryIntent.SUMMARY)

    def fake_fetch(u):
        seen["u"] = u
        return SubjectQueryResponse(subject="삼성전자", subject_found=True)

    def fake_answer(u, r):
        seen["answered"] = True
        return Answer(text="요약", evidence_news_ids=[1])

    monkeypatch.setattr(query_understanding, "understand_query", fake_understand)
    monkeypatch.setattr(graph_query, "fetch_events", fake_fetch)
    monkeypatch.setattr(answer_generator, "generate_answer", fake_answer)

    state = query_node_mod.query_node({"question": "삼성전자 요약"})
    assert seen["q"] == "삼성전자 요약"
    assert isinstance(state["understanding"], QueryUnderstanding)
    assert isinstance(state["query_response"], SubjectQueryResponse)
    assert isinstance(state["answer"], Answer)
    assert state["answer"].text == "요약"


def test_query_node_preset_from_subject(monkeypatch):
    monkeypatch.setattr(graph_query, "fetch_events",
                        lambda u: SubjectQueryResponse(subject=u.companies[0], subject_found=True))
    monkeypatch.setattr(answer_generator, "generate_answer",
                        lambda u, r: Answer(text="프리셋 요약"))
    # 종목 입력 → from_subject 프리셋 경로(LLM 없이)
    state = query_node_mod.query_node({"subject": "삼성전자"})
    assert state["understanding"].is_preset is True
    assert state["understanding"].companies == ["삼성전자"]


def test_query_node_degrades_on_step_failure(monkeypatch):
    # 질문이해가 던져도 노드는 죽지 않고 빈 이해로 통과.
    def boom(q):
        raise RuntimeError("understand failed")

    monkeypatch.setattr(query_understanding, "understand_query", boom)
    monkeypatch.setattr(graph_query, "fetch_events",
                        lambda u: SubjectQueryResponse(subject="", subject_found=False))
    monkeypatch.setattr(answer_generator, "generate_answer",
                        lambda u, r: Answer(text="데이터 제한", data_limited=True))
    state = query_node_mod.query_node({"question": "무엇이든"})
    assert state["answer"].data_limited is True


def test_report_node_fills_report_json():
    state = {
        "understanding": QueryUnderstanding(companies=["삼성전자"], period_days=7),
        "query_response": SubjectQueryResponse(subject="삼성전자", subject_found=True),
        "answer": Answer(text="요약 본문", data_limited=True),
    }
    out = report_node_mod.report_node(state)
    payload = out["report_json"]
    assert isinstance(payload, dict)
    # ④ 답변이 JSON 리포트 안에 내장됨(별도 텍스트 출력 없음)
    assert payload["answer_text"] == "요약 본문"
    assert payload["subject"] == "삼성전자"
    assert payload["data_limited"] is True


def test_report_node_survives_render_failure(monkeypatch):
    # build_report_model 이 던져도 노드는 최소 JSON 으로 통과(흐름 안 죽임).
    import src.agents.news.services.report_renderer as rr
    monkeypatch.setattr(rr, "build_report_model",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("render boom")))
    state = {
        "understanding": QueryUnderstanding(companies=["삼성전자"]),
        "query_response": SubjectQueryResponse(subject="삼성전자"),
        "answer": Answer(text="x"),
    }
    out = report_node_mod.report_node(state)
    assert isinstance(out["report_json"], dict)
    assert out["report_json"]["data_limited"] is True
    assert "데이터 제한" in (out["report_json"]["note"] or "")


def test_nodes_do_not_import_backend_or_llm_directly():
    # 절대규칙 1·§2-2: 노드는 서비스만 부른다(httpx·query_client·llm 직접 import 없음).
    for mod in (query_node_mod, report_node_mod):
        src = Path(mod.__file__).read_text(encoding="utf-8").lower()
        assert "httpx" not in src
        assert "import services.backend" not in src
        assert "import services.llm" not in src
