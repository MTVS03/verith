# services/answer_generator.py — ④ 답변 생성 (Qwen3, 근거 news_id)
"""③ 근거(요약)를 바탕으로 '뉴스 흐름 요약' 본문을 쓰고, 모든 주장에 근거 news_id 를 부착한다(§0.2).

- LLM 은 텍스트만 만든다 — 감성을 판정·집계하지 않는다(절대규칙 4). 프롬프트에도 감성값을 넣지 않는다.
- 근거 기사는 우선 EventWithArticles.articles(대표 소수, news_id·summary 포함)에서 얻고, 대표가 비었을
  때만 query_client.get_articles_by_event(event_id, limit) 로 on-demand 보강한다(§0.2·§3.5·SCHEMA_SPEC §7.2).
- LLM 이 근거 밖 news_id/event_id 를 내밀면 걸러낸다(실제 조회된 값만, 환각 금지, 절대규칙 5).
- 데이터가 없으면(없는 종목/뉴스 0건) 지어내지 말고 data_limited=True + '데이터 제한' 문구(subject_found 로 구분).
- LLM 호출·타임아웃·재시도는 services/llm.py 소관. 출력은 Answer 로 파싱·검증(CLAUDE.md §2-3).
"""
from __future__ import annotations

import json
import logging

import services.backend.query_client as query_client
import services.llm as llm
from config import (
    QUERY_ANSWER_MAX_TOKENS,
    QUERY_ANSWER_SYSTEM_PROMPT,
    QUERY_ANSWER_TEMPERATURE,
    QUERY_INTENT_GUIDANCE,
    REPORT_MAX_ARTICLES_PER_EVENT,
)
from schemas.query import Answer, QueryUnderstanding
from schemas.report import ArticleRef
from schemas.response import SubjectQueryResponse
from services.backend.client import BackendError

logger = logging.getLogger(__name__)


def generate_answer(understanding: QueryUnderstanding,
                    response: SubjectQueryResponse) -> Answer:
    """③ 요약을 근거로 Answer(뉴스 흐름 요약 본문 + 근거 news_id/event_id)를 만든다."""
    # 데이터 없음: 없는 종목 vs 뉴스 0건을 subject_found 로 구분해 문구를 다르게(§0.2, TASK 01 §3.4).
    if not response.subject_found:
        return Answer(text=_no_subject_text(understanding), data_limited=True)
    if not response.events:
        return Answer(text=_no_news_text(understanding), data_limited=True)

    # ③ 근거 수집: 대표 소수 우선, 비었으면 on-demand. 실제 조회된 news_id/event_id 만 유효 근거로 인정.
    payload, valid_news_ids, valid_event_ids = _collect_evidence(response)
    if not valid_news_ids:
        # 이벤트는 있으나 근거 기사를 하나도 확보 못 함 → 근거 없는 서술 금지, 데이터 제한.
        return Answer(text=_no_news_text(understanding), data_limited=True)

    parsed = _generate_with_llm(understanding, payload)
    if parsed is None:
        # LLM 미가용/파싱 실패: 근거는 있으나 서술을 못 만들었다 → 데이터 제한으로 정직하게 표기(§7).
        logger.warning("generate_answer: LLM 파싱 실패 → 데이터 제한 degrade")
        return Answer(text=_llm_failed_text(understanding), data_limited=True)

    # 환각 방지: LLM 이 준 근거를 '실제 조회된 값'으로만 좁힌다(§0.2).
    evidence = [n for n in _as_int_list(parsed.get("evidence_news_ids")) if n in valid_news_ids]
    cited = [e for e in _as_str_list(parsed.get("cited_event_ids")) if e in valid_event_ids]
    text = parsed.get("text")
    if not isinstance(text, str) or not text.strip():
        return Answer(text=_llm_failed_text(understanding), data_limited=True)

    data_limited = bool(parsed.get("data_limited")) or not evidence
    return Answer(
        text=text.strip(),
        evidence_news_ids=evidence,
        cited_event_ids=cited,
        data_limited=data_limited,
    )


# ---------------------------------------------------------------------------
# 근거 수집 / LLM 호출 / 파싱 보조
# ---------------------------------------------------------------------------
def _collect_evidence(response: SubjectQueryResponse) -> tuple[list[dict], set[int], set[str]]:
    """이벤트별 근거(event_id·title·기사 news_id+summary)를 모아 LLM 입력 payload 와 유효 id 집합을 만든다.

    대표 소수(articles)로 근거를 닫고, 대표가 비었을 때만 on-demand 로 보강한다(대표/근거 조회 분리, §0.2).
    감성값(gauge)은 payload 에 넣지 않는다 — LLM 이 감성을 판정하지 못하게(절대규칙 4).
    """
    payload: list[dict] = []
    valid_news_ids: set[int] = set()
    valid_event_ids: set[str] = set()

    for ewa in response.events:
        event = ewa.event
        event_id = event.canonical_id
        articles: list[ArticleRef] = list(ewa.articles)
        # 대표 소수가 비었지만 총 건수는 있는 경우에만 on-demand 근거 조회(깊은 근거).
        if not articles and ewa.article_count > 0 and event_id:
            try:
                articles = query_client.get_articles_by_event(event_id, REPORT_MAX_ARTICLES_PER_EVENT)
            except BackendError as exc:
                logger.warning("get_articles_by_event 실패(event_id=%s): %s", event_id, exc)
                articles = []

        if event_id:
            valid_event_ids.add(event_id)
        art_items = []
        for a in articles:
            valid_news_ids.add(a.news_id)
            art_items.append({"news_id": a.news_id, "summary": a.summary})

        payload.append({
            "event_id": event_id,
            "title": event.canonical_title,
            "importance": event.importance,
            "articles": art_items,
        })

    return payload, valid_news_ids, valid_event_ids


def _generate_with_llm(understanding: QueryUnderstanding, payload: list[dict]) -> dict | None:
    """근거 payload + intent 초점으로 Qwen3 답변 생성 → dict. 오류·미파싱 시 None(degrade 신호)."""
    guidance = QUERY_INTENT_GUIDANCE.get(understanding.intent.value, "")
    system = QUERY_ANSWER_SYSTEM_PROMPT + ("\n[초점]\n" + guidance if guidance else "")
    user = (
        f"질문: {understanding.original_question or ''}\n"
        f"대상 회사: {', '.join(understanding.companies) or '(미상)'}\n"
        f"집계 기간(일): {understanding.period_days}\n"
        "다음은 근거 이벤트·기사다(JSON). 이 안의 news_id/event_id 만 근거로 인용하라:\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        text = llm.complete(messages, temperature=QUERY_ANSWER_TEMPERATURE,
                            max_tokens=QUERY_ANSWER_MAX_TOKENS)
    except Exception as exc:  # httpx 오류 등 — 흐름을 죽이지 않고 degrade
        logger.warning("generate_answer: LLM 호출 실패: %s", exc)
        return None
    return llm.coerce_json(text)


def _as_int_list(value: object) -> list[int]:
    """LLM 이 준 news_id 후보를 정수 리스트로 정규화(문자열 정수 허용). 비정수는 버린다."""
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for v in value:
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            out.append(v)
        elif isinstance(v, str) and v.strip().lstrip("-").isdigit():
            out.append(int(v.strip()))
    return out


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value if isinstance(v, str) and v.strip()]


# ---------------------------------------------------------------------------
# 데이터 제한 문구(subject_found 로 '없는 종목'과 '뉴스 0건'을 구분, §0.2)
# ---------------------------------------------------------------------------
def _subject_label(understanding: QueryUnderstanding) -> str:
    return " · ".join(understanding.companies) if understanding.companies else "요청 종목"


def _no_subject_text(understanding: QueryUnderstanding) -> str:
    return f"{_subject_label(understanding)}에 해당하는 종목을 찾지 못했습니다. 데이터 제한으로 추정 없이 표기합니다."


def _no_news_text(understanding: QueryUnderstanding) -> str:
    return (
        f"{_subject_label(understanding)} 관련 최근 {understanding.period_days}일 뉴스가 없어 "
        "요약할 근거가 부족합니다. 데이터 제한으로 추정 없이 표기합니다."
    )


def _llm_failed_text(understanding: QueryUnderstanding) -> str:
    return (
        f"{_subject_label(understanding)} 관련 뉴스 요약을 생성하지 못했습니다. "
        "데이터 제한으로 추정 없이 표기합니다."
    )
