"""LLM 지시 성형 rewriter 테스트 — 주입식 LLM, 실패 시 결정론 템플릿 fallback (실 네트워크 없음)."""

from __future__ import annotations

import json

from src.supervisor.planning.rewrite_llm import (
    LlmRewriter,
    TemplateRewriter,
    build_prompt,
)
from src.supervisor.schemas import AGENT_ORDER, StockContext


def _ctx(name: str | None = "삼성전자", code: str | None = "005930") -> StockContext:
    return StockContext(stock_code=code, stock_name=name)


class _FakeLlm:
    """주입식 LLM 대역 — 지정한 completion 을 그대로 돌려주거나 예외를 던진다."""

    def __init__(self, completion: str | None = None, *, raises: Exception | None = None) -> None:
        self._completion = completion
        self._raises = raises
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self._raises is not None:
            raise self._raises
        return self._completion or ""


_VALID = json.dumps({
    "fundamental": "화재 이슈가 실적·재무 건전성에 줄 영향 관점에서 분석.",
    "technical": "최근 급락 구간의 거래량·지지 이탈 관점에서 분석.",
    "news": "삼성전자 배터리 화재 이슈와 주가 관련 최근 뉴스·심리 정리.",
    "flow": "이슈 전후 외국인·기관 수급 변화 분석.",
    "industry": "배터리 화재가 2차전지 산업 경쟁구도에 주는 영향.",
}, ensure_ascii=False)


# ── TemplateRewriter: 결정론 기본 ──────────────────────────────────────────────
def test_template_rewriter_returns_all_five():
    out = TemplateRewriter().rewrite_all("삼성전자 어때?", _ctx())
    assert set(out.keys()) == set(AGENT_ORDER)
    assert all(isinstance(v, str) and v for v in out.values())
    assert "삼성전자" in out["technical"]  # 종목형 템플릿


# ── LlmRewriter 성공: LLM 지시를 그대로 사용 ──────────────────────────────────
def test_llm_rewriter_uses_llm_instructions():
    llm = _FakeLlm(_VALID)
    out = LlmRewriter(llm).rewrite_all("삼성전자 배터리 화재 때문에 주가 괜찮아?", _ctx())
    assert set(out.keys()) == set(AGENT_ORDER)
    assert out["news"].startswith("삼성전자 배터리 화재")   # 원문 주제 보존
    assert "거래량" in out["technical"]                      # 코드형 초점
    assert llm.prompts and "배터리 화재" in llm.prompts[0]   # 사용자 원문이 프롬프트에 들어감


# ── LLM 호출 예외 → 전부 템플릿 fallback ──────────────────────────────────────
def test_llm_rewriter_falls_back_on_error():
    llm = _FakeLlm(raises=RuntimeError("boom"))
    out = LlmRewriter(llm).rewrite_all("삼성전자 어때?", _ctx())
    template = TemplateRewriter().rewrite_all("삼성전자 어때?", _ctx())
    assert out == template  # 전부 결정론 템플릿으로 안전 착지


# ── 파싱 불가(비-JSON) → 템플릿 fallback ──────────────────────────────────────
def test_llm_rewriter_falls_back_on_unparseable():
    out = LlmRewriter(_FakeLlm("죄송합니다 JSON이 아닙니다")).rewrite_all("q", _ctx())
    assert out == TemplateRewriter().rewrite_all("q", _ctx())


# ── 일부 키 누락/빈 값 → 해당 에이전트만 템플릿 ───────────────────────────────
def test_llm_rewriter_per_agent_fallback_on_partial():
    partial = json.dumps({
        "technical": "가격 축 지시.",
        "news": "",              # 빈 값 → 템플릿
        # fundamental/flow/industry 누락 → 템플릿
    }, ensure_ascii=False)
    out = LlmRewriter(_FakeLlm(partial)).rewrite_all("q", _ctx())
    template = TemplateRewriter().rewrite_all("q", _ctx())
    assert out["technical"] == "가격 축 지시."          # LLM 값 사용
    assert out["news"] == template["news"]              # 빈 값 → 템플릿
    assert out["fundamental"] == template["fundamental"]  # 누락 → 템플릿


# ── 안전선: LLM 이 코드를 지시 텍스트에 넣어도 구조 필드(stock_code)로는 안 감 ──
def test_llm_output_only_fills_query_not_code():
    # LLM 이 지시 텍스트에 엉뚱한 코드를 섞어도, 그건 rewritten_query(자연어)일 뿐이다.
    sneaky = json.dumps({a: f"{a} 지시 000000 코드사칭" for a in AGENT_ORDER}, ensure_ascii=False)
    out = LlmRewriter(_FakeLlm(sneaky)).rewrite_all("q", _ctx(code="005930"))
    # rewrite_all 은 문자열(지시)만 반환 — stock_code 는 여기서 다루지 않는다(planner 가 context 로 부착).
    assert all(isinstance(v, str) for v in out.values())


# ── build_prompt: 원문·카드·종목 컨텍스트 포함 ────────────────────────────────
def test_build_prompt_includes_query_cards_and_context():
    p = build_prompt("삼성전자 급락 이유?", _ctx(name="삼성전자"))
    assert "삼성전자 급락 이유?" in p
    assert "확정: 삼성전자" in p
    for a in AGENT_ORDER:
        assert a in p            # 에이전트 카드 5개 다 포함
    p2 = build_prompt("2차전지 업황?", _ctx(name=None, code=None))
    assert "미확정" in p2         # 종목 미확정 표기
