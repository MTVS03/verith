"""전처리 LLM 노드(1·2) 단위테스트 (test_plan.md §5.9 PRE-*). 실제 LLM 호출 없음 — FakeLlm만.

정본 스키마(prompts.md §2·§3): 노드 1 = {normalized_question}만, 노드 2 = {analysis_focus, focus_summary}만.
"""

from __future__ import annotations

import inspect
import json

import pytest

from src.agents.technical.config import BATTERY_TICKERS
from src.agents.technical.nodes.focus_analysis import (
    FocusResult,
    run_focus_analysis,
)
from src.agents.technical.nodes.normalize_question import (
    NormalizeResult,
    run_normalize_question,
)
from src.agents.technical.schemas.enums import GenerationSource

TICKER = "373220"  # LG에너지솔루션
AS_OF = "2026-06-30T14:30:00+09:00"
SAFE_QUESTION = ("LG에너지솔루션의 최근 시세·거래량·기술적 신호를 중심으로 "
                 "현재 차트 국면과 리스크 관찰점을 분석합니다.")


class FakeLlm:
    """주입한 응답을 그대로 돌려주는 fake. 네트워크 없음."""

    def __init__(self, response: str):
        self._response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._response


def _norm(response: str) -> NormalizeResult:
    return run_normalize_question(FakeLlm(response), ticker=TICKER, query="LG엔솔 지금 사도 돼?", as_of=AS_OF)


def _focus(response: str) -> FocusResult:
    return run_focus_analysis(FakeLlm(response), ticker=TICKER, normalized_question=SAFE_QUESTION)


# ── normalize_question (PRE-01~05) ───────────────────────────────────────────
def test_pre01_normalize_normal():
    result = _norm(json.dumps({"normalized_question": SAFE_QUESTION}, ensure_ascii=False))
    assert result.source == GenerationSource.LLM
    assert result.normalized_question == SAFE_QUESTION


def test_pre02_normalize_extra_key_falls_back():
    result = _norm(json.dumps({"normalized_question": SAFE_QUESTION, "safety_notes": ["x"]},
                              ensure_ascii=False))
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


def test_pre03_normalize_parse_failure_falls_back():
    result = _norm("not json at all")
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


def test_pre04_normalize_forbidden_term_falls_back():
    result = _norm(json.dumps({"normalized_question": "지금 매수하세요."}, ensure_ascii=False))
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


def test_pre05_normalize_fallback_uses_ticker_name():
    result = _norm("not json")
    assert result.source == GenerationSource.TEMPLATE_FALLBACK
    assert BATTERY_TICKERS[TICKER] in result.normalized_question  # "LG에너지솔루션"


# ── stock_name 외부 주입 우선순위 (전체 종목 확장 핵심) ───────────────────────
def _norm_named(response: str, stock_name: str | None, *, ticker: str = TICKER) -> NormalizeResult:
    return run_normalize_question(
        FakeLlm(response), ticker=ticker, query="지금 어때?", as_of=AS_OF, stock_name=stock_name)


def test_injected_stock_name_wins_over_dev_fallback_in_template():
    # 주입 canonical 종목명이 dev 표시명(BATTERY)과 달라도 fallback 문장은 주입명을 쓴다.
    result = _norm_named("not json", "커스텀종목")
    assert result.source == GenerationSource.TEMPLATE_FALLBACK
    assert "커스텀종목" in result.normalized_question
    assert BATTERY_TICKERS[TICKER] not in result.normalized_question  # dev명 우선 아님


def test_preservation_uses_injected_stock_name():
    # 보존 검증 기준은 주입 canonical 종목명. 그 이름이 문장에 있으면 LLM 통과.
    q = "커스텀종목의 최근 시세와 거래량, 기술적 신호를 분석합니다."
    result = _norm_named(json.dumps({"normalized_question": q}, ensure_ascii=False), "커스텀종목")
    assert result.source == GenerationSource.LLM and result.normalized_question == q


def test_preservation_fails_when_injected_name_absent():
    # LLM 문장에 dev명만 있고 주입 canonical명이 없으면 보존 실패 → fallback(주입명 사용).
    q = "LG에너지솔루션의 최근 시세와 거래량, 기술적 신호를 분석합니다."
    result = _norm_named(json.dumps({"normalized_question": q}, ensure_ascii=False), "커스텀종목")
    assert result.source == GenerationSource.TEMPLATE_FALLBACK
    assert "커스텀종목" in result.normalized_question


def test_expanded_ticker_without_name_falls_back_to_code():
    # 이름 모르는 확장 종목(dev map 없음·주입 없음): 보존검증 skip, fallback은 ticker 코드.
    result = _norm_named("not json", None, ticker="999999")
    assert result.source == GenerationSource.TEMPLATE_FALLBACK
    assert "999999" in result.normalized_question


def test_normalize_fenced_json_parses():
    fenced = f"```json\n{json.dumps({'normalized_question': SAFE_QUESTION}, ensure_ascii=False)}\n```"
    assert _norm(fenced).source == GenerationSource.LLM


def test_normalize_missing_key_falls_back():
    result = _norm(json.dumps({}, ensure_ascii=False))  # 빈 object → 빈 문장
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


def test_normalize_requires_ticker_and_query():
    with pytest.raises(ValueError):
        run_normalize_question(FakeLlm("{}"), ticker="", query="q", as_of=AS_OF)
    with pytest.raises(ValueError):
        run_normalize_question(FakeLlm("{}"), ticker=TICKER, query="", as_of=AS_OF)


# ── H1: normalized_question 타입/공백 엄격 (PRE-13·14) ────────────────────────
@pytest.mark.parametrize("bad", [["안전한 문장"], {"text": "안전"}, 123, True, None])
def test_normalize_non_string_falls_back(bad):
    result = _norm(json.dumps({"normalized_question": bad}))
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


def test_normalize_whitespace_falls_back():
    result = _norm(json.dumps({"normalized_question": "   "}, ensure_ascii=False))
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


# ── H3: 구어체 행동 지시·미래 단정 (PRE-16) ──────────────────────────────────
@pytest.mark.parametrize("text", [
    "지금 사세요.",
    "지금 파세요.",
    "LG에너지솔루션은 오를 것입니다.",
    "LG에너지솔루션 지금 사도 됩니다. 급등합니다.",
])
def test_normalize_action_directive_falls_back(text):
    result = _norm(json.dumps({"normalized_question": text}, ensure_ascii=False))
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


# ── M1: 종목명 보존 (PRE-17) ─────────────────────────────────────────────────
def test_normalize_missing_ticker_name_falls_back():
    # 앵커는 있으나 종목명(LG에너지솔루션)이 없음
    result = _norm(json.dumps(
        {"normalized_question": "최근 시세와 기술적 흐름을 확인합니다."}, ensure_ascii=False))
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


def test_normalize_wrong_ticker_name_falls_back():
    result = _norm(json.dumps(
        {"normalized_question": "삼성전자의 최근 시세와 기술적 흐름을 확인합니다."}, ensure_ascii=False))
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


# ── M1: 기술적 분석 앵커 (PRE-18) ────────────────────────────────────────────
def test_normalize_no_technical_anchor_falls_back():
    # 종목명은 있으나 기술 앵커 단어가 없음(재무제표 = 펀더멘털)
    result = _norm(json.dumps(
        {"normalized_question": "LG에너지솔루션의 재무제표를 분석합니다."}, ensure_ascii=False))
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


def test_normalize_hello_falls_back():
    result = _norm(json.dumps({"normalized_question": "hello"}, ensure_ascii=False))
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


def test_normalize_with_name_and_anchor_is_llm():
    result = _norm(json.dumps(
        {"normalized_question": "LG에너지솔루션의 최근 시세와 기술적 흐름을 확인합니다."},
        ensure_ascii=False))
    assert result.source == GenerationSource.LLM


# ── H1: focus_summary 타입/공백 엄격 (PRE-13·14) ─────────────────────────────
@pytest.mark.parametrize("bad", [{"text": "추세"}, 123, ["추세"], None])
def test_focus_summary_non_string_falls_back(bad):
    result = _focus(json.dumps({"analysis_focus": ["trend"], "focus_summary": bad}))
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


def test_focus_summary_whitespace_falls_back():
    result = _focus(json.dumps({"analysis_focus": ["trend"], "focus_summary": "  "}, ensure_ascii=False))
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


# ── H2: analysis_focus 타입 안전(중첩 리스트에서 예외 아님, PRE-15) ──────────
@pytest.mark.parametrize("bad_focus", [
    "trend",          # list 아님
    [],               # 빈 list
    [["trend"]],      # 원소가 list (unhashable → 예외 대신 fallback이어야 함)
    [1, 2],           # 원소가 number
    ["trend", "trend"],  # 중복
    ["macd"],         # 허용값 밖
])
def test_focus_invalid_analysis_focus_falls_back(bad_focus):
    result = _focus(json.dumps({"analysis_focus": bad_focus, "focus_summary": "추세를 확인합니다."},
                               ensure_ascii=False))
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


def test_focus_summary_action_directive_falls_back():
    result = _focus(json.dumps(
        {"analysis_focus": ["trend"], "focus_summary": "지금 사세요."}, ensure_ascii=False))
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


# ── M3: LLM 호출 예외는 삼키지 않고 전파 (PRE-19) ────────────────────────────
class RaisingLlm:
    def complete(self, prompt: str) -> str:
        raise TimeoutError("LLM timed out")


def test_normalize_call_error_propagates_as_llmcallerror():
    # 호출 자체 예외는 LlmCallError로 전파(노드가 내부 fallback으로 삼키지 않음, M2).
    from src.agents.technical.nodes._llm_utils import LlmCallError
    with pytest.raises(LlmCallError):
        run_normalize_question(RaisingLlm(), ticker=TICKER, query="q", as_of=AS_OF)


def test_focus_call_error_propagates_as_llmcallerror():
    from src.agents.technical.nodes._llm_utils import LlmCallError
    with pytest.raises(LlmCallError):
        run_focus_analysis(RaisingLlm(), ticker=TICKER, normalized_question=SAFE_QUESTION)


# ── focus_analysis (PRE-06~11) ───────────────────────────────────────────────
def test_pre06_focus_normal():
    result = _focus(json.dumps(
        {"analysis_focus": ["trend", "momentum"], "focus_summary": "추세와 모멘텀을 함께 확인합니다."},
        ensure_ascii=False))
    assert result.source == GenerationSource.LLM
    assert result.analysis_focus == ["trend", "momentum"]


def test_pre07_focus_out_of_allowed_falls_back():
    result = _focus(json.dumps({"analysis_focus": ["macd"], "focus_summary": "x"}, ensure_ascii=False))
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


def test_pre08_focus_duplicate_or_empty_falls_back():
    dup = _focus(json.dumps({"analysis_focus": ["trend", "trend"], "focus_summary": "x"},
                            ensure_ascii=False))
    assert dup.source == GenerationSource.TEMPLATE_FALLBACK
    empty = _focus(json.dumps({"analysis_focus": [], "focus_summary": "x"}, ensure_ascii=False))
    assert empty.source == GenerationSource.TEMPLATE_FALLBACK


def test_pre09_focus_calc_field_rejected():
    result = _focus(json.dumps(
        {"analysis_focus": ["trend"], "focus_summary": "추세를 봅니다.", "signal_score": 0.3},
        ensure_ascii=False))
    assert result.source == GenerationSource.TEMPLATE_FALLBACK  # 추가 키 거부


def test_pre10_focus_forbidden_summary_falls_back():
    result = _focus(json.dumps(
        {"analysis_focus": ["trend"], "focus_summary": "이 종목을 추천합니다."}, ensure_ascii=False))
    assert result.source == GenerationSource.TEMPLATE_FALLBACK


def test_pre11_focus_fallback_uses_canonical_five():
    result = _focus("not json")
    assert result.source == GenerationSource.TEMPLATE_FALLBACK
    assert result.analysis_focus == ["trend", "momentum", "volume", "support_resistance", "risk"]


def test_focus_parse_failure_falls_back():
    assert _focus("not json").source == GenerationSource.TEMPLATE_FALLBACK


# ── PRE-12: 노드 2는 원본 query를 받지 않는다 (안전 가드) ─────────────────────
def test_pre12_focus_does_not_accept_query():
    params = inspect.signature(run_focus_analysis).parameters
    assert "query" not in params
    assert "normalized_question" in params


# ── 실제 LLM 호출 없음 ───────────────────────────────────────────────────────
def test_no_real_llm_calls():
    client = FakeLlm(json.dumps({"normalized_question": SAFE_QUESTION}, ensure_ascii=False))
    run_normalize_question(client, ticker=TICKER, query="q", as_of=AS_OF)
    assert len(client.prompts) == 1  # 단일 호출, fake만
