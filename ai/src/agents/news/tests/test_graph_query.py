# tests/test_graph_query.py — ② 그래프 탐색 설계(TASK 09) 테스트 (mock 기반)
"""회사 수·intent 로 single/multi-hop 분기, within_days 전달, BackendError degrade, DB 미접근을 검증한다.

실제 backend 는 부르지 않는다 — query_client 의 조회 함수를 monkeypatch 한다.
"""
from __future__ import annotations

from pathlib import Path

import src.agents.news.services.backend.query_client as query_client
import src.agents.news.services.graph_query as graph_query
from src.agents.news.schemas.query import QueryIntent, QueryUnderstanding
from src.agents.news.schemas.response import SubjectQueryResponse
from src.agents.news.services.backend.client import BackendError


def _resp(subject="삼성전자"):
    return SubjectQueryResponse(subject=subject, subject_found=True)


def test_single_company_uses_subject_endpoint(monkeypatch):
    calls = {}

    def fake_subject(companies, within_days):
        calls["companies"] = companies
        calls["within_days"] = within_days
        return _resp()

    def fail_shared(*a, **k):
        raise AssertionError("single-hop 인데 shared 를 불렀다")

    monkeypatch.setattr(query_client, "get_events_by_subject", fake_subject)
    monkeypatch.setattr(query_client, "get_shared_events", fail_shared)

    u = QueryUnderstanding(companies=["삼성전자"], period_days=5, intent=QueryIntent.SUMMARY)
    out = graph_query.fetch_events(u)
    assert calls["companies"] == ["삼성전자"]
    assert calls["within_days"] == 5          # period_days 가 within_days 로 전달
    assert out.subject_found is True


def test_two_companies_use_shared_endpoint(monkeypatch):
    calls = {}

    def fake_shared(company_a, company_b, within_days):
        calls.update(a=company_a, b=company_b, within_days=within_days)
        return _resp("삼성전자 · SK하이닉스")

    monkeypatch.setattr(query_client, "get_shared_events", fake_shared)
    monkeypatch.setattr(query_client, "get_events_by_subject",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("multi-hop 인데 subject 를 불렀다")))

    u = QueryUnderstanding(companies=["삼성전자", "SK하이닉스"], period_days=7,
                           intent=QueryIntent.RELATION)
    out = graph_query.fetch_events(u)
    assert calls == {"a": "삼성전자", "b": "SK하이닉스", "within_days": 7}
    assert out.subject_found is True


def test_zero_companies_skips_backend(monkeypatch):
    monkeypatch.setattr(query_client, "get_events_by_subject",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("backend 호출됨")))
    monkeypatch.setattr(query_client, "get_shared_events",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("backend 호출됨")))

    u = QueryUnderstanding(companies=[], original_question="없는거 물어봄")
    out = graph_query.fetch_events(u)
    assert out.subject_found is False
    assert out.events == []


def test_backend_error_degrades(monkeypatch):
    def boom(companies, within_days):
        raise BackendError("backend down")

    monkeypatch.setattr(query_client, "get_events_by_subject", boom)
    u = QueryUnderstanding(companies=["삼성전자"], period_days=7)
    out = graph_query.fetch_events(u)      # 예외 전파 안 함
    assert out.subject_found is False
    assert out.events == []


def test_no_db_driver_or_cypher_in_source():
    # 절대규칙 1: 질의 경로에 DB 드라이버 import·Cypher 실행이 없다(개념 설명 주석의 언급은 무방).
    src = Path(graph_query.__file__).read_text(encoding="utf-8")
    for forbidden_import in ("import neo4j", "from neo4j", "import psycopg",
                             "from psycopg", "import sqlalchemy", "from sqlalchemy"):
        assert forbidden_import not in src
    # Cypher 실행 키워드가 코드로 등장하지 않는다.
    for cypher in ("MATCH (", "MERGE (", "CREATE ("):
        assert cypher not in src
