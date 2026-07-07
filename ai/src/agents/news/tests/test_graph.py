# tests/test_graph.py — LangGraph 배선 테스트(mock 기반, TASK 11)
"""graph.py 의 배선(순서·주입·state 전파·진입점)만 검증한다. 각 단계의 실제 로직은 TASK 02~09 소유이므로
여기선 노드를 fake 로 대체해 **배선**만 본다(CLAUDE.md: tests 는 mock, 실제 backend·LLM·네트워크 미호출).

검증 축(TASK 11 §7):
- 배치 배선: crawl→…→save 순서, 앞 노드 산출 키를 뒤 노드가 받음, merge_event·importance 에 주입한
  Provider 가 실제로 노드에 전달됨, Provider 미주입(BatchProviders()) degrade(provider=None) 통과.
- 질의 배선: query→report 로 이어지고 run_query 가 질문→JSON 리포트(state["report_json"])를 반환.
- 진입점: run_batch/run_query 가 컴파일된 앱을 invoke.
- 얇음·미접근: graph.py/state.py 에 SQL·Cypher·DB 드라이버·HTTP 라이브러리 import 없음, 배선 라이브러리
  (LangGraph)·backend import 는 함수 안(격리)에만.
"""
from __future__ import annotations

import pathlib

import graph as g
from graph import BatchProviders, build_batch_graph, run_batch, run_query

# 배치 노드 이름(graph 모듈 전역) — fake 로 갈아끼워 배선만 검증한다.
_BATCH_NODE_NAMES = (
    "crawl_node", "extract_node", "sentiment_node", "embedding_node",
    "merge_event_node", "importance_node", "graph_node", "save_node",
)


def _passthrough_batch_nodes(monkeypatch):
    """모든 배치 노드를 무해한 통과 fake 로 대체(실제 크롤·모델·backend 미호출)."""
    monkeypatch.setattr(g, "crawl_node", lambda s: {"articles": []})
    for name in ("extract_node", "sentiment_node", "embedding_node", "graph_node"):
        monkeypatch.setattr(g, name, lambda s: {})
    monkeypatch.setattr(g, "merge_event_node", lambda s, provider=None: {})
    monkeypatch.setattr(g, "importance_node", lambda s, provider=None: {})
    monkeypatch.setattr(g, "save_node", lambda s: {"save_result": "SR"})


# ---------------------------------------------------------------------------
# 배치 배선 — 순서·state 전파
# ---------------------------------------------------------------------------
def test_batch_graph_runs_nodes_in_order_and_propagates_state(monkeypatch):
    """crawl→extract→sentiment→embedding→merge_event→importance→graph→save 순서로 돌고,
    앞 노드가 채운 state 키를 뒤 노드가 실제로 받는다(§7 배치 배선)."""
    order: list[str] = []

    def fake_crawl(state):
        order.append("crawl")
        return {"articles": ["a1", "a2"]}

    def fake_extract(state):
        order.append("extract")
        assert state["articles"] == ["a1", "a2"]      # crawl 산출을 받는다
        return {"extracts_by_url": {"u": "ex"}}

    def fake_sentiment(state):
        order.append("sentiment")
        assert "articles" in state
        return {}

    def fake_embedding(state):
        order.append("embedding")
        assert "articles" in state
        return {}

    def fake_merge(state, provider=None):
        order.append("merge_event")
        assert state["extracts_by_url"] == {"u": "ex"}  # extract 산출을 받는다
        return {"events_by_id": {"e": "E"}}

    def fake_importance(state, provider=None):
        order.append("importance")
        assert state["events_by_id"] == {"e": "E"}       # merge 산출을 받는다
        return {"importance_by_event_id": {"e": 1.0}}

    def fake_graph(state):
        order.append("graph")
        assert state["importance_by_event_id"] == {"e": 1.0}
        return {"graph_batch": "GB"}

    def fake_save(state):
        order.append("save")
        assert state["graph_batch"] == "GB"              # graph 산출을 받는다
        return {"save_result": "SR"}

    monkeypatch.setattr(g, "crawl_node", fake_crawl)
    monkeypatch.setattr(g, "extract_node", fake_extract)
    monkeypatch.setattr(g, "sentiment_node", fake_sentiment)
    monkeypatch.setattr(g, "embedding_node", fake_embedding)
    monkeypatch.setattr(g, "merge_event_node", fake_merge)
    monkeypatch.setattr(g, "importance_node", fake_importance)
    monkeypatch.setattr(g, "graph_node", fake_graph)
    monkeypatch.setattr(g, "save_node", fake_save)

    app = build_batch_graph(providers=BatchProviders())  # backend 없이 배선만
    final = app.invoke({})

    assert order == [
        "crawl", "extract", "sentiment", "embedding",
        "merge_event", "importance", "graph", "save",
    ]
    assert final["save_result"] == "SR"                  # 끝까지 전파
    assert final["articles"] == ["a1", "a2"]             # 앞 단계 산출이 최종 state 에 남는다


def test_batch_graph_completes_on_empty_initial_state(monkeypatch):
    """빈 초기 state·수집 0건이 각 노드를 통과해 끝까지 완주한다(경계 케이스, §7)."""
    _passthrough_batch_nodes(monkeypatch)
    app = build_batch_graph(providers=BatchProviders())
    final = app.invoke({})
    assert final["save_result"] == "SR"


# ---------------------------------------------------------------------------
# 배치 배선 — Provider 주입·미주입 degrade
# ---------------------------------------------------------------------------
def test_batch_graph_injects_providers_into_merge_and_importance(monkeypatch):
    """주입한 Provider 가 실제로 merge_event·importance 노드에 전달된다(functools.partial 주입, §7)."""
    seen: dict = {}

    monkeypatch.setattr(g, "crawl_node", lambda s: {"articles": []})
    for name in ("extract_node", "sentiment_node", "embedding_node", "graph_node"):
        monkeypatch.setattr(g, name, lambda s: {})
    monkeypatch.setattr(g, "save_node", lambda s: {"save_result": "SR"})
    monkeypatch.setattr(g, "merge_event_node",
                        lambda s, provider=None: seen.__setitem__("merge", provider) or {})
    monkeypatch.setattr(g, "importance_node",
                        lambda s, provider=None: seen.__setitem__("importance", provider) or {})

    providers = BatchProviders(recent_event="RE", event_stats="ES")
    build_batch_graph(providers=providers).invoke({})

    assert seen["merge"] == "RE"        # merge_event 는 recent_event Provider 를 받는다
    assert seen["importance"] == "ES"   # importance 는 event_stats Provider 를 받는다


def test_batch_graph_degrades_without_providers(monkeypatch):
    """BatchProviders()(둘 다 None) → 노드에 provider=None 전달, 예외 없이 완주(degrade, §7)."""
    seen: dict = {}

    monkeypatch.setattr(g, "crawl_node", lambda s: {"articles": []})
    for name in ("extract_node", "sentiment_node", "embedding_node", "graph_node"):
        monkeypatch.setattr(g, name, lambda s: {})
    monkeypatch.setattr(g, "save_node", lambda s: {"save_result": "SR"})
    monkeypatch.setattr(g, "merge_event_node",
                        lambda s, provider=None: seen.__setitem__("merge", provider) or {})
    monkeypatch.setattr(g, "importance_node",
                        lambda s, provider=None: seen.__setitem__("importance", provider) or {})

    final = build_batch_graph(providers=BatchProviders()).invoke({})

    assert seen["merge"] is None
    assert seen["importance"] is None
    assert final["save_result"] == "SR"


# ---------------------------------------------------------------------------
# 진입점 — run_batch / run_query
# ---------------------------------------------------------------------------
def test_run_batch_invokes_compiled_graph_and_returns_state(monkeypatch):
    """run_batch 가 배치 앱을 invoke 해 최종 state 를 돌려준다(TASK 10 이 부를 진입점)."""
    _passthrough_batch_nodes(monkeypatch)
    # 기본 Provider(backend) 생성을 피해 backend import·구성 없이 배선만 돈다.
    monkeypatch.setattr(g, "_default_batch_providers", lambda: BatchProviders())

    out = run_batch()  # state=None → 빈 초기 state

    assert out["save_result"] == "SR"


def test_run_query_returns_report_json_from_report_node(monkeypatch):
    """run_query('질문') 이 query→report 를 이어 state['report_json'](JSON 계약)을 반환한다(Supervisor 진입점, §7)."""
    order: list[str] = []

    def fake_query(state):
        order.append("query")
        assert state["question"] == "삼성 요약해줘"    # 질문 문자열이 그대로 들어온다
        return {"answer": "A"}

    def fake_report(state):
        order.append("report")
        assert state["answer"] == "A"                  # query 산출을 받는다
        return {"report_json": {"subject": "삼성전자", "answer_text": "리포트"}}

    monkeypatch.setattr(g, "query_node", fake_query)
    monkeypatch.setattr(g, "report_node", fake_report)

    payload = run_query("삼성 요약해줘")

    assert order == ["query", "report"]
    assert payload == {"subject": "삼성전자", "answer_text": "리포트"}


def test_run_query_returns_empty_dict_when_report_json_missing(monkeypatch):
    """report 가 report_json 을 못 채워도 run_query 는 예외 없이 dict({})를 반환한다(방어)."""
    monkeypatch.setattr(g, "query_node", lambda s: {})
    monkeypatch.setattr(g, "report_node", lambda s: {})
    assert run_query("q") == {}


# ---------------------------------------------------------------------------
# 얇음·미접근(정적 검사 — import 문만 파싱)
# ---------------------------------------------------------------------------
def _import_lines(module) -> list[str]:
    """import 문만 추출(주석·docstring 언급을 오탐하지 않도록)."""
    src = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    return [ln for ln in src.splitlines() if ln.lstrip().startswith(("import ", "from "))]


def test_graph_and_state_have_no_db_or_http_imports():
    """graph.py·state.py 어디에도 DB 드라이버·HTTP 라이브러리 import 가 없다(절대규칙 1)."""
    import state
    for module in (g, state):
        imports = " ".join(_import_lines(module)).lower()
        for mod in ("httpx", "psycopg", "sqlalchemy", "neo4j", "pymysql", "asyncpg", "requests"):
            assert mod not in imports, f"{module.__name__}: 금지된 DB/HTTP import: {mod}"


def test_wiring_library_import_is_isolated():
    """LangGraph import 는 build 함수 안(들여쓰기)에만 있어야 한다 — top-level 은 라이브러리 없이도 import(§5)."""
    for line in _import_lines(g):
        if "langgraph" in line.lower():
            assert line[:1].isspace(), f"top-level 에서 배선 라이브러리 import: {line!r}"


def test_backend_import_is_isolated_to_injection_seam():
    """backend Provider import 는 함수 안(주입 시점)에만 — graph.py 는 backend 를 top-level 로 끌어오지 않는다(절대규칙 1)."""
    for line in _import_lines(g):
        if "services.backend" in line:
            assert line[:1].isspace(), f"top-level backend import(직접 결합): {line!r}"
