# services/query_understanding.py — ① 질문 이해 (Dictionary First → LLM Fallback)
"""자유 문장/종목을 companies·period·intent 로 파싱해 QueryUnderstanding 으로 강제한다(CLAUDE.md §2-3).

회사명 해석은 LLM 단독이 아니다(query_spec §①-1, CLAUDE.md §5): **사전(규칙) 우선 → LLM 보완**.
  ① config.COMPANY_ALIASES 최장일치 매칭으로 오타·약어를 먼저 잡는다(LLM 오인식·호출 감소).
  ② 사전이 못 잡은 부분만 Qwen3(services/llm.py)로 보완하고, 기간·의도도 이 호출에서 파싱한다.
  ③ 그래프(Company 노드) 검증은 전용 엔드포인트가 없어(SCHEMA_SPEC §7.3) ② 그래프순회의 subject_found
     로 대체한다 — 여기서는 backend 를 부르지 않고(순수·테스트 용이), 존재 검증을 fetch_events 에 위임한다.
  ④ 저신뢰·미매칭 토큰은 억지로 매핑하지 않고 버려 dropped_tokens 로 남긴다(환각 금지, 절대규칙 5).

감성·영향도는 판정하지 않는다(절대규칙 4). LLM 호출·타임아웃·재시도는 services/llm.py 소관.
"""
from __future__ import annotations

import logging

import services.llm as llm
from config import (
    COMPANY_ALIASES,
    QUERY_DEFAULT_PERIOD_DAYS,
    QUERY_PRESET_QUESTION_TEMPLATE,
    QUERY_UNDERSTANDING_SYSTEM_PROMPT,
)
from schemas.query import QueryIntent, QueryUnderstanding

logger = logging.getLogger(__name__)


def understand_query(question: str) -> QueryUnderstanding:
    """자유 질문 → QueryUnderstanding(companies·period_days·intent). §3.3 순서를 따른다.

    파싱 실패(LLM 오류·깨진 JSON)해도 예외로 흐름을 죽이지 않고 보수적 기본값으로 통과한다
    (회사 사전 결과만·기본 기간·요약 intent → 리포트가 '데이터 제한' 처리, 절대규칙 5·§7).
    """
    question = question or ""

    # ① 사전 최장일치 매칭(Dictionary First). 매칭분은 residual 에서 제거해 남은 토큰만 LLM 에 남긴다.
    dict_companies, residual = _match_aliases(question)

    # ② LLM 보완: 잔여 회사 후보 + 기간 + 의도. 실패 시 사전 결과만으로 degrade.
    companies = list(dict_companies)
    period_days = QUERY_DEFAULT_PERIOD_DAYS
    intent = QueryIntent.SUMMARY
    dropped: list[str] = []

    parsed = _parse_with_llm(question)
    if parsed is not None:
        # ④ LLM 이 확신한 회사만 병합(프롬프트가 '확실하지 않으면 넣지 않는다'로 저신뢰 제거를 유도).
        for name in parsed.get("companies") or []:
            if isinstance(name, str) and name.strip() and name not in companies:
                companies.append(name.strip())
        pd = parsed.get("period_days")
        if isinstance(pd, int) and pd > 0:
            period_days = pd
        intent = _to_intent(parsed.get("intent"))
        for tok in parsed.get("non_company_tokens") or []:
            if isinstance(tok, str) and tok.strip():
                dropped.append(tok.strip())
    else:
        # LLM 미가용/파싱 실패: 사전이 못 잡은 잔여 토큰을 관측용으로 남긴다(사전 보강 대상).
        logger.warning("understand_query: LLM 파싱 실패 → 사전 결과만 사용. question=%.120s", question)
        dropped.extend(_residual_tokens(residual))

    return QueryUnderstanding(
        companies=companies,
        period_days=period_days,
        intent=intent,
        is_preset=False,
        dropped_tokens=dropped,
        original_question=question,
    )


def from_subject(company: str) -> QueryUnderstanding:
    """종목 선택(A) → intent=요약 프리셋(B). LLM 없이 변환한다(query_spec §2-①)."""
    company = (company or "").strip()
    companies = [company] if company else []
    return QueryUnderstanding(
        companies=companies,
        period_days=QUERY_DEFAULT_PERIOD_DAYS,
        intent=QueryIntent.SUMMARY,
        is_preset=True,
        original_question=QUERY_PRESET_QUESTION_TEMPLATE.format(company=company),
    )


# ---------------------------------------------------------------------------
# 보조 — 사전 매칭 / LLM 파싱 / intent 매핑
# ---------------------------------------------------------------------------
def _match_aliases(question: str) -> tuple[list[str], str]:
    """COMPANY_ALIASES 를 최장일치로 스캔해 canonical 회사 리스트와 '매칭분을 지운 잔여 문자열'을 돌려준다.

    형태소 분석기 없이 별칭 substring 매칭(조사·공백에 강함, query_spec §①-1). 별칭이 여러 회사로 매핑되면
    모두 추가하고, 매칭 구간은 공백으로 치환해 중복 계수와 잔여 토큰 오염을 막는다.
    """
    companies: list[str] = []
    residual = question
    for alias in sorted(COMPANY_ALIASES, key=len, reverse=True):
        low = alias.lower()
        idx = residual.lower().find(low)
        while idx != -1:
            for canonical in COMPANY_ALIASES[alias]:
                if canonical not in companies:
                    companies.append(canonical)
            residual = residual[:idx] + " " + residual[idx + len(alias):]
            idx = residual.lower().find(low)
    return companies, residual


def _residual_tokens(residual: str) -> list[str]:
    """잔여 문자열을 공백 기준 토큰으로(관측·사전 보강용). 아주 짧은 조각은 버린다."""
    return [t for t in residual.split() if len(t) >= 2]


def _parse_with_llm(question: str) -> dict | None:
    """잔여 회사·기간·의도를 Qwen3 로 파싱해 dict 반환. 오류·미파싱 시 None(degrade 신호)."""
    if not question.strip():
        return None
    messages = [
        {"role": "system", "content": QUERY_UNDERSTANDING_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    try:
        text = llm.complete(messages)
    except Exception as exc:  # httpx 오류 등 — 흐름을 죽이지 않고 degrade
        logger.warning("understand_query: LLM 호출 실패: %s", exc)
        return None
    return llm.coerce_json(text)


def _to_intent(value: object) -> QueryIntent:
    """LLM 이 준 intent 문자열 → QueryIntent. 미지/누락은 요약으로 안전 대체."""
    try:
        return QueryIntent(value)  # type: ignore[arg-type]
    except (ValueError, KeyError):
        return QueryIntent.SUMMARY
