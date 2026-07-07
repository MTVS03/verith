# tests/test_query_understanding.py — ① 질문이해(TASK 09) 테스트 (mock 기반, 네트워크 없음)
"""Dictionary First → LLM Fallback 계약을 검증한다: 사전 매칭·LLM 보완·기본 기간·degrade·프리셋.

실제 LLM 은 부르지 않는다 — services.llm.complete 를 monkeypatch 해 고정 JSON/오류를 돌려준다.
"""
from __future__ import annotations

import json

import services.llm as llm
import services.query_understanding as qu
from config import QUERY_DEFAULT_PERIOD_DAYS
from schemas.query import QueryIntent, QueryUnderstanding


def _mock_llm(monkeypatch, payload):
    """llm.complete 가 payload(JSON 문자열 또는 dict)를 돌려주도록 교체."""
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)

    def fake(messages, **kwargs):
        return text

    monkeypatch.setattr(llm, "complete", fake)


def test_llm_json_parsed_into_understanding(monkeypatch):
    _mock_llm(monkeypatch, {"companies": ["현대자동차"], "period_days": 3,
                            "intent": "이유", "non_company_tokens": []})
    u = qu.understand_query("현대차 왜 올랐어")
    # 사전(현차→현대자동차) + LLM(현대자동차) 병합·dedup
    assert "현대자동차" in u.companies
    assert u.period_days == 3
    assert u.intent == QueryIntent.REASON
    assert u.is_preset is False
    assert u.original_question == "현대차 왜 올랐어"
    # 감성 필드는 존재하지 않는다(절대규칙 4)
    assert not hasattr(u, "sentiment")


def test_dictionary_first_resolves_alias(monkeypatch):
    # LLM 이 회사를 못 줘도 사전이 약어를 잡는다.
    _mock_llm(monkeypatch, {"companies": [], "period_days": None, "intent": "요약"})
    u = qu.understand_query("삼전닉스 어때")
    assert u.companies == ["삼성전자", "SK하이닉스"]  # 다중 매핑


def test_default_period_when_absent(monkeypatch):
    _mock_llm(monkeypatch, {"companies": ["삼성전자"], "period_days": None, "intent": "요약"})
    u = qu.understand_query("삼성전자 요약")
    assert u.period_days == QUERY_DEFAULT_PERIOD_DAYS


def test_broken_json_degrades_without_exception(monkeypatch):
    # 깨진 JSON → coerce 실패 → 예외 없이 보수적 기본값(사전 결과만)으로 통과.
    _mock_llm(monkeypatch, "이건 JSON 이 아니다 {깨짐")
    u = qu.understand_query("듣도보도못한종목 전망")
    assert u.companies == []           # 사전에도 없고 LLM 파싱 실패 → 빈 회사(리포트가 데이터 제한)
    assert u.period_days == QUERY_DEFAULT_PERIOD_DAYS
    assert u.intent == QueryIntent.SUMMARY
    assert u.dropped_tokens             # 잔여 토큰은 관측용으로 남는다


def test_llm_call_failure_keeps_dictionary_result(monkeypatch):
    def boom(messages, **kwargs):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(llm, "complete", boom)
    u = qu.understand_query("삼전 실적 어때")
    assert u.companies == ["삼성전자"]   # 사전 결과는 살아남는다


def test_from_subject_preset():
    u = qu.from_subject("삼성전자")
    assert isinstance(u, QueryUnderstanding)
    assert u.companies == ["삼성전자"]
    assert u.intent == QueryIntent.SUMMARY
    assert u.is_preset is True
    assert "삼성전자" in (u.original_question or "")
