# tests/test_state.py — 상태 키 계약 테스트(TASK 11)
"""BatchState·QueryState 가 TASK 11 §3.1 표와 **정확히 일치**하는 키·타입·부분성(total=False)을
갖는지 못박는다. 이 계약이 흔들리면 TASK 02~09 노드가 주고받는 키가 어긋나므로 여기서 회귀를 잡는다.

state.py 는 `from __future__ import annotations` 라 `__annotations__` 값이 소스 문자열 그대로다 —
그 문자열을 표와 대조한다(런타임 타입 해석 없이 계약 자체를 검증).
"""
from __future__ import annotations

import typing

import state


def _annotation_strings(td) -> dict[str, str]:
    """TypedDict 의 __annotations__ 를 소스 문자열 계약으로 정규화.

    `from __future__ import annotations` + TypedDict 는 3.10 에서 값을 ForwardRef 로 감싼다 —
    그 forward arg(원 소스 문자열)를 꺼내 표와 대조한다.
    """
    out: dict[str, str] = {}
    for key, val in td.__annotations__.items():
        out[key] = val.__forward_arg__ if isinstance(val, typing.ForwardRef) else str(val)
    return out


def test_batch_state_keys_and_types_match_contract():
    """BatchState 의 키·타입이 §3.1 배치 표와 정확히 일치."""
    assert _annotation_strings(state.BatchState) == {
        "articles": "list[Article]",
        "extracts_by_url": "dict[str, ExtractResult]",
        "events_by_id": "dict[str, Event]",
        "importance_by_event_id": "dict[str, float]",
        "graph_batch": "GraphBatch",
        "save_result": "SaveResponse",
    }


def test_query_state_keys_and_types_match_contract():
    """QueryState 의 키·타입이 §3.1 질의 표와 정확히 일치."""
    assert _annotation_strings(state.QueryState) == {
        "question": "str",
        "understanding": "QueryUnderstanding",
        "query_response": "SubjectQueryResponse",
        "answer": "Answer",
        "report_model": "ReportModel",
        "report_json": "dict",
    }


def test_both_states_are_partial_typeddicts():
    """total=False — 배치는 키가 점진적으로 채워지므로 모든 키가 선택적이어야 한다(§0 배경)."""
    for td in (state.BatchState, state.QueryState):
        assert td.__total__ is False
        # 모든 키가 optional, 필수 키는 없다(부분 딕셔너리 허용).
        assert td.__required_keys__ == frozenset()
        assert td.__optional_keys__ == frozenset(td.__annotations__)
