# demo_sentiment_app.py
"""TASK 01~07 수동 확인용 Streamlit 데모 (throwaway — 파이프라인 코드 아님).

기존 코드·docs·테스트는 건드리지 않는 별도 파일이다. schemas / services / nodes 를 사람이
눈으로 만져보기 위한 용도이며, 지워도 에이전트 동작에 영향 없다.

실행 (c:\\verith 기준):
    uv run --project ai --with streamlit streamlit run ai/src/agents/news/demo_sentiment_app.py

무거운 외부 의존성(모델·네트워크)은 각 서비스의 '시임' 함수를 monkeypatch 해 mock 으로 돌린다
(테스트와 같은 방식). 파서·정규화·검증처럼 순수 함수는 실제 그대로 호출한다.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone

# news 루트(config.py·services·nodes 가 있는 곳)를 임포트 루트로. conftest.py 규약과 동일.
_ROOT = os.path.dirname(__file__)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st  # noqa: E402  (sys.path 설정 뒤에 import — conftest 규약)
from pydantic import ValidationError  # noqa: E402

import config  # noqa: E402
import services.backend.client as backend_client  # noqa: E402
import services.backend.providers as backend_providers  # noqa: E402
import services.backend.query_client as query_client  # noqa: E402
import services.backend.save_client as save_client  # noqa: E402
import services.crawler as crawler  # noqa: E402
import services.embedder as embedder  # noqa: E402
import services.event_merge as event_merge  # noqa: E402
import services.finbert as finbert  # noqa: E402
import services.graph_builder as graph_builder  # noqa: E402
import services.importance as importance  # noqa: E402
import services.llm as llm  # noqa: E402
import services.rss as rss  # noqa: E402
from nodes.embedding import embedding_node  # noqa: E402
from nodes.graph_builder import graph_node  # noqa: E402
from nodes.importance import importance_node  # noqa: E402
from nodes.merge_event import merge_event_node  # noqa: E402
from nodes.save import save_node  # noqa: E402
from nodes.sentiment import sentiment_node  # noqa: E402
from schemas.article import Article, EventCandidate, ExtractResult, Sentiment  # noqa: E402
from schemas.event import CandidateEvent, Event, EventArticleStats  # noqa: E402
from schemas.graph import GraphBatch, GraphNode, GraphRelationship, NodeLabel, RelType  # noqa: E402
from utils.html_parser import extract_text  # noqa: E402
from utils.rss_parser import parse_rss  # noqa: E402
from utils.similarity import company_overlap, cosine_similarity, time_proximity  # noqa: E402

# --- TASK 09 질의·리포트 흐름 (질문이해 → 그래프탐색 → 답변생성 → HTML 렌더) ---
import streamlit.components.v1 as components  # noqa: E402
import services.answer_generator as answer_generator  # noqa: E402
import services.graph_query as graph_query  # noqa: E402
import services.query_understanding as query_understanding  # noqa: E402
from nodes.query import query_node  # noqa: E402
from nodes.report import report_node  # noqa: E402
from schemas.query import QueryIntent, QueryUnderstanding  # noqa: E402
from schemas.response import SubjectQueryResponse  # noqa: E402

st.set_page_config(page_title="news 에이전트 데모 (TASK 01~09)", page_icon="📰", layout="wide")
st.title("📰 news 에이전트 — TASK 01~09 수동 테스트")

# mock↔실제 전환 시 원본 시임으로 되돌릴 수 있게, 진짜 원본을 (스트림릿 rerun 에도) 딱 1회만 보관한다.
# streamlit 은 모듈을 재import 하지 않으므로 hasattr 가드로 mock 이 원본 자리를 덮는 것을 막는다.
if not hasattr(llm, "_orig_chat_completion"):
    llm._orig_chat_completion = llm._chat_completion
if not hasattr(finbert, "_orig_infer_raw"):
    finbert._orig_infer_raw = finbert._infer_raw
if not hasattr(embedder, "_orig_embed_raw"):
    embedder._orig_embed_raw = embedder._embed_raw

TASK = st.sidebar.radio(
    "TASK 선택",
    [
        "TASK 01 — 스키마(schemas)",
        "TASK 02 — 수집·크롤(rss·crawler)",
        "TASK 03 — 추출(llm.extract)",
        "TASK 04 — 감성(finbert)",
        "TASK 05 — 임베딩·병합(embedder·event_merge)",
        "TASK 06 — 중요도(importance)",
        "TASK 07 — 지식그래프(graph_builder)",
        "TASK 08 — backend 클라이언트(save·query·providers)",
        "TASK 09 — 질의·리포트(query→report·HTML)",
    ],
)
st.sidebar.caption("무거운 부분(모델·네트워크)은 mock 시임으로 대체합니다.")


def _model_json(model) -> str:
    return model.model_dump_json(indent=2)


# ===========================================================================
# TASK 01 — schemas: Pydantic 강제(검증) 확인
# ===========================================================================
if TASK.startswith("TASK 01"):
    st.header("TASK 01 — 데이터 계약(Pydantic)이 실제로 강제되는지")
    st.caption("절대규칙 3: LLM/입력 결과는 schemas 로 파싱·검증한다. 잘못된 값은 통과하지 못한다.")

    st.subheader("Sentiment Enum — 3종만 허용")
    st.write({s.name: s.value for s in Sentiment})
    st.caption("긍정/중립/부정 외 문자열은 감성으로 들어올 수 없다(§2-4).")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Article 검증")
        default_article = json.dumps(
            {
                "title": "삼성전자 3분기 영업이익 사상 최대",
                "url": "https://example.com/news/1",
                "publisher": "매일경제",
                "sentiment": "긍정",
                "sentiment_score": 0.94,
            },
            ensure_ascii=False,
            indent=2,
        )
        raw = st.text_area("Article JSON", default_article, height=260, key="a01_article")
        if st.button("Article 검증", key="a01_btn_article"):
            try:
                art = Article.model_validate(json.loads(raw))
                st.success("검증 통과 → 정규화된 모델")
                st.code(_model_json(art), language="json")
            except json.JSONDecodeError as exc:
                st.error(f"JSON 형식 오류: {exc}")
            except ValidationError as exc:
                st.error("Pydantic 검증 실패 (계약이 막아냄)")
                st.code(str(exc))

    with col2:
        st.subheader("ExtractResult 검증")
        default_extract = json.dumps(
            {
                "summary": "삼성전자가 HBM 공급 계약을 체결했다.",
                "companies": ["삼성전자"],
                "events": [{"title": "HBM 공급 계약", "confidence": 0.8}],
                "keywords": ["HBM", "반도체"],
            },
            ensure_ascii=False,
            indent=2,
        )
        raw_e = st.text_area("ExtractResult JSON", default_extract, height=260, key="a01_extract")
        if st.button("ExtractResult 검증", key="a01_btn_extract"):
            try:
                res = ExtractResult.model_validate(json.loads(raw_e))
                st.success("검증 통과")
                st.code(_model_json(res), language="json")
            except json.JSONDecodeError as exc:
                st.error(f"JSON 형식 오류: {exc}")
            except ValidationError as exc:
                st.error("Pydantic 검증 실패")
                st.code(str(exc))
        st.caption('sentiment 에 "매우긍정" 같은 값을 넣거나 url 을 빼보면 검증이 막는 걸 볼 수 있습니다.')


# ===========================================================================
# TASK 02 — rss·crawler: 순수 함수(정규화·파싱·정제·SSRF) 확인 (오프라인)
# ===========================================================================
elif TASK.startswith("TASK 02"):
    st.header("TASK 02 — 수집·크롤 구성요소")
    st.caption("순수 함수는 오프라인으로, '실제 RSS 수집' 탭은 RSS_CANDIDATES 로 네트워크 수집합니다.")

    t0, t1, t2, t3, t4 = st.tabs(
        ["실제 RSS 수집", "URL 정규화·중복키", "RSS/Atom 파싱", "HTML→본문·임계", "SSRF URL 검사"]
    )

    with t0:
        st.subheader("collect_articles — config.RSS_CANDIDATES 실제 수집(네트워크)")
        names = [p for p, _ in config.RSS_CANDIDATES]
        chosen = st.multiselect("수집할 언론사(피드)", names, default=names[:3])
        st.caption("선택한 피드만 수집하도록 rss.RSS_CANDIDATES 를 그 순간만 좁혀 실제 collect_articles() 를 호출합니다.")
        if st.button("실제 수집", key="a02_collect"):
            subset = [(p, u) for p, u in config.RSS_CANDIDATES if p in chosen]
            if not subset:
                st.warning("언론사를 하나 이상 선택하세요.")
            else:
                orig = rss.RSS_CANDIDATES
                rss.RSS_CANDIDATES = subset  # collect_articles 가 참조하는 모듈 전역만 잠시 교체
                try:
                    with st.spinner(f"{len(subset)}개 피드 수집·정규화·중복제거 중…"):
                        arts = rss.collect_articles()
                except Exception as exc:
                    st.error(f"수집 실패: {exc}")
                    arts = []
                finally:
                    rss.RSS_CANDIDATES = orig
                st.session_state["collected"] = arts
                st.success(f"{len(arts)}건 수집(중복 제거 후). 본문·감성은 아직 없음(pending).")

        collected = st.session_state.get("collected") or []
        if collected:
            st.dataframe(
                [
                    {"publisher": a.publisher, "title": a.title,
                     "published_at": str(a.published_at), "crawl_status": a.crawl_status,
                     "url": str(a.url)}
                    for a in collected
                ],
                use_container_width=True,
            )
            st.info("➡️ 이 목록은 'TASK 03 — 추출' 에서 실제 기사로 골라 본문 크롤+추출까지 돌릴 수 있습니다.")

    with t1:
        st.subheader("normalize_url — 추적 파라미터 제거, 중복 접기")
        urls = st.text_area(
            "URL 여러 개(줄바꿈)",
            "https://News.example.com/a?utm_source=fb&fbclid=xx&id=10\n"
            "https://news.example.com/a?id=10\n"
            "https://news.example.com/a?id=10#comments",
            height=120,
        )
        if st.button("정규화", key="a02_norm"):
            seen: dict[str, int] = {}
            for u in [x for x in urls.splitlines() if x.strip()]:
                key = rss.normalize_url(u)
                dup = key in seen
                seen[key] = seen.get(key, 0) + 1
                st.write(f"`{u}`")
                st.write(f"→ **{key}**  {'🔁 중복(같은 키)' if dup else '🆕'}")
            st.info(f"고유 기사 {len(seen)}건 (입력의 추적 파라미터·fragment 차이는 접힘)")

    with t2:
        st.subheader("parse_rss — RSS 2.0 / Atom XML → 항목")
        sample_xml = (
            '<?xml version="1.0"?>\n<rss version="2.0"><channel>\n'
            "<item><title>삼성전자 실적 발표</title>"
            "<link>https://example.com/1</link>"
            "<pubDate>Mon, 06 Jul 2026 09:00:00 +0900</pubDate></item>\n"
            "<item><title>SK하이닉스 HBM 수주</title>"
            "<link>https://example.com/2</link>"
            "<pubDate>Mon, 06 Jul 2026 08:30:00 +0900</pubDate></item>\n"
            "</channel></rss>"
        )
        xml = st.text_area("RSS/Atom XML", sample_xml, height=200)
        publisher = st.text_input("publisher", "매일경제")
        if st.button("파싱", key="a02_parse"):
            items = parse_rss(xml, publisher)
            st.success(f"{len(items)}건 파싱")
            st.dataframe(
                [
                    {
                        "title": it["title"],
                        "link": it["link"],
                        "published_at": str(it["published_at"]),
                        "publisher": it["publisher"],
                    }
                    for it in items
                ],
                use_container_width=True,
            )

    with t3:
        st.subheader("extract_text + 본문 인정 임계(MIN_CONTENT_LEN)")
        st.caption(f"현재 임계: {config.MIN_CONTENT_LEN}자 이상이면 success, 미만이면 no_content(속보).")
        html = st.text_area(
            "기사 HTML",
            "<html><head><title>무시됨</title><style>.x{}</style></head>"
            "<body><nav>메뉴</nav><article><p>본문 문단 하나.</p>"
            "<p>두 번째 문단입니다.</p></article><footer>푸터</footer></body></html>",
            height=160,
        )
        if st.button("정제", key="a02_html"):
            text = extract_text(html)
            status = "success" if len(text) >= config.MIN_CONTENT_LEN else "no_content"
            st.metric("추출 본문 길이", f"{len(text)}자", status)
            st.text(text or "(빈 텍스트)")

    with t4:
        st.subheader("_validate_url — SSRF/사설 IP 차단 (하위 방어)")
        st.caption("도메인은 DNS 조회가 일어날 수 있습니다. 사설/루프백/메타데이터 대역은 차단됩니다.")
        test_url = st.text_input("검사할 URL", "http://169.254.169.254/latest/meta-data/")
        if st.button("검사", key="a02_ssrf"):
            try:
                crawler._validate_url(test_url)
                st.success("허용됨 (scheme·주소 정책 통과)")
            except crawler.CrawlBlocked as exc:
                st.error(f"🚫 차단(CrawlBlocked): {exc}")
            except crawler.CrawlError as exc:
                st.warning(f"검사 중 오류(CrawlError): {exc}")
        st.caption("예: http://localhost/, http://10.0.0.1/, file:///etc/passwd 를 넣어보세요.")


# ===========================================================================
# TASK 03 — llm.extract: _chat_completion 시임 mock → ExtractResult
# ===========================================================================
elif TASK.startswith("TASK 03"):
    st.header("TASK 03 — LLM 추출(요약·개체·이벤트)")
    st.caption("감성·중요도는 추출하지 않습니다(§2-4). 결과는 ExtractResult(Pydantic)로 강제.")

    mode = st.sidebar.radio("추출 모드", ["실제 Qwen3 서버", "Mock (가짜 LLM 응답)"])

    # TASK 02 에서 실제 수집한 기사가 있으면 그중에서 골라 실제 본문 크롤+추출을 돌린다.
    collected = st.session_state.get("collected") or []
    picked = None
    if collected:
        labels = ["(직접 입력)"] + [f"{a.publisher} · {a.title}" for a in collected]
        idx = st.selectbox("수집된 기사에서 선택", range(len(labels)), format_func=lambda i: labels[i])
        if idx > 0:
            picked = collected[idx - 1]
    else:
        st.caption("‘TASK 02 → 실제 RSS 수집’ 을 먼저 돌리면 실제 기사를 여기서 골라 추출할 수 있습니다.")

    title = st.text_input("기사 제목", picked.title if picked else "삼성전자, 엔비디아에 HBM 공급 계약 체결")
    url = st.text_input("기사 URL", str(picked.url) if picked else "https://example.com/news/1")
    publisher = st.text_input("언론사", (picked.publisher or "") if picked else "한국경제")

    _KNOWN = ["삼성전자", "SK하이닉스", "엔비디아", "현대차", "LG에너지솔루션", "네이버", "카카오"]

    def _mock_chat_completion(messages, tools=None, tool_choice="auto"):
        """가짜 LLM: 제목만으로 그럴듯한 추출 JSON 을 만들어 OpenAI 응답 형태로 돌려준다.
        tool 을 호출하지 않으므로 extract 는 title_only 경로로 바로 파싱한다(크롤러 미사용).
        """
        companies = [c for c in _KNOWN if c in title]
        payload = {
            "summary": f"{title} (제목 기반 요약)",
            "companies": companies,
            "people": [],
            "industries": ["반도체"] if ("HBM" in title or "반도체" in title) else [],
            "events": [{"title": "HBM 공급 계약" if "HBM" in title else "기업 발표", "confidence": 0.6}],
            "countries": [],
            "keywords": [w for w in ["HBM", "계약", "실적"] if w in title],
            "event_date": None,
        }
        return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}

    if mode.startswith("Mock"):
        llm._chat_completion = _mock_chat_completion  # 테스트와 같은 시임 교체
        st.sidebar.success("Mock: 실제 모델·크롤러를 부르지 않습니다.")
    else:
        llm._chat_completion = getattr(llm, "_orig_chat_completion")  # 원본 복원(실제 Qwen3 호출)
        st.sidebar.info("실제 모드: QWEN_API_KEY 의 Qwen3 서버 호출 + 본문 크롤(fetch_article Tool).")

    if st.button("추출 실행"):
        art = Article(title=title, url=url, publisher=publisher)
        try:
            result = llm.extract(art)
        except Exception as exc:
            st.error(f"추출 실패: {exc}")
        else:
            if result is None:
                st.warning("결과 없음(None) — 크롤 실패·파싱 실패 등 skip 신호")
            else:
                st.success(f"추출 완료 · source_type={result.source_type.value}")
                st.code(_model_json(result), language="json")
                st.caption(f"Article.crawl_status={art.crawl_status} · content_available={art.content_available}")

    st.divider()
    with st.expander("🔎 본문 크롤 진단 — 왜 '본문 없음'인지 이 URL 을 직접 크롤해 확인"):
        st.caption(
            "LLM 없이 services/crawler 로 이 URL 을 직접 받아, 원시 HTML 길이 vs 추출 텍스트 길이를 비교합니다. "
            f"추출 텍스트가 {config.MIN_CONTENT_LEN}자 미만이면 no_content(속보)로 분류됩니다."
        )
        if st.button("이 URL 크롤 진단", key="a03_diag"):
            try:
                raw_html = crawler._download_with_retry(url)  # 리다이렉트·SSRF 검사 포함 실제 다운로드
            except crawler.CrawlBlocked as exc:
                st.error(f"🚫 차단(CrawlBlocked): {exc}")
            except crawler.CrawlError as exc:
                st.error(f"크롤 실패(CrawlError): {exc} — status=failed")
            else:
                text = extract_text(raw_html)[: config.ARTICLE_CONTENT_MAX_CHARS]
                status = "success" if len(text) >= config.MIN_CONTENT_LEN else "no_content"
                c1, c2, c3 = st.columns(3)
                c1.metric("원시 HTML", f"{len(raw_html):,}자")
                c2.metric("추출 텍스트", f"{len(text):,}자")
                c3.metric("판정", status)
                script_cnt = raw_html.lower().count("<script")
                st.caption(
                    f"<script> 태그 {script_cnt}개. 원시 HTML 은 큰데 추출 텍스트가 거의 0이면 "
                    "→ 본문을 JavaScript 로 그리는 페이지(urllib 은 JS 실행 안 함) 또는 이미지/웹툰 본문입니다."
                )
                st.text_area("추출 텍스트 미리보기", text[:1500] or "(빈 텍스트)", height=200)


# ===========================================================================
# TASK 04 — finbert 감성 (단건/배치 + 노드 분기)
# ===========================================================================
elif TASK.startswith("TASK 04"):
    st.header("TASK 04 — 감성분석(KR-FinBert-SC)")
    st.caption(
        f"모델: `{config.FINBERT_MODEL}` · 입력 상한 {config.FINBERT_MAX_INPUT_CHARS}자 · "
        f"라벨맵 {config.FINBERT_LABEL_MAP}"
    )

    mode = st.sidebar.radio("추론 모드", ["Mock (키워드 휴리스틱)", "실제 KR-FinBert 모델"])

    _POS = ["호조", "상승", "급등", "최대", "돌파", "호재", "흑자", "개선", "성장", "수주", "계약", "호실적", "웃돌"]
    _NEG = ["급락", "하락", "쇼크", "부진", "적자", "악재", "리콜", "소송", "감소", "우려", "위기", "손실", "밑돌"]

    def _mock_infer(texts):
        out = []
        for t in texts:
            pos = sum(t.count(w) for w in _POS)
            neg = sum(t.count(w) for w in _NEG)
            if pos > neg:
                label, score = "positive", min(0.5 + 0.1 * (pos - neg), 0.99)
            elif neg > pos:
                label, score = "negative", min(0.5 + 0.1 * (neg - pos), 0.99)
            else:
                label, score = "neutral", 0.6
            out.append({"label": label, "score": round(score, 3)})
        return out

    if mode.startswith("Mock"):
        finbert._infer_raw = _mock_infer
        st.sidebar.success("Mock: 모델 미사용. 키워드로 라벨을 흉내냅니다.")
        st.sidebar.caption(f"긍정어: {', '.join(_POS[:6])}…")
        st.sidebar.caption(f"부정어: {', '.join(_NEG[:6])}…")
    else:
        finbert._infer_raw = getattr(finbert, "_orig_infer_raw")  # 원본 복원(실제 KR-FinBert 추론)
        st.sidebar.info("실제 모드: 첫 추론 시 모델을 내려받습니다(수백 MB).")

    _BADGE = {"긍정": "🟢 긍정", "중립": "⚪ 중립", "부정": "🔴 부정"}

    def _render(result):
        if result is None:
            st.warning("감성 없음(None) — 빈 입력·매핑 밖 라벨·추론 실패")
            return
        # 명확한 문장은 confidence 가 0.9999 로 saturate 한다(정상). .3f 면 1.000 으로 반올림되어
        # 애매한 문장(예: 0.79)과의 차이가 안 보이므로, 정밀도를 높여(소수 4자리 + %) 표시한다.
        st.metric(
            _BADGE.get(result.sentiment.value, result.sentiment.value),
            f"{result.score:.2%}",
            help=f"softmax confidence = {result.score:.4f} (0~1). 명확한 문장일수록 1.0에 가깝게 saturate.",
        )

    tab1, tab2 = st.tabs(["단건/배치 (services/finbert)", "노드 분기 (nodes/sentiment)"])

    with tab1:
        st.subheader("classify — 본문 1건")
        text = st.text_area("기사 본문(Article.content)", "삼성전자 실적이 시장 예상을 크게 웃돌았다.", height=110)
        if st.button("감성 판정", key="a04_single"):
            try:
                _render(finbert.classify(text))
            except Exception as exc:
                st.error(f"추론 실패: {exc}")

        st.divider()
        st.subheader("classify_batch — 여러 건(줄바꿈, 순서 유지)")
        batch_raw = st.text_area(
            "본문 여러 개",
            "SK하이닉스 HBM 수주 급증으로 흑자 전환\n국민연금 매도폭탄에 주가 급락\n실적을 발표했다",
            height=110,
        )
        if st.button("배치 판정", key="a04_batch"):
            texts = [ln for ln in batch_raw.splitlines() if ln.strip()]
            try:
                for t, r in zip(texts, finbert.classify_batch(texts)):
                    st.write(f"**{t}**")
                    _render(r)
            except Exception as exc:
                st.error(f"추론 실패: {exc}")

    with tab2:
        st.subheader("crawl_status 별 분기")
        st.caption("success 만 판정 · no_content/failed 는 skip(sentiment=None). 제목만으로 추론하지 않음.")
        samples = [
            Article(title="호실적", url="https://ex.com/1", content="영업이익 사상 최대 흑자 달성",
                    crawl_status="success", content_available=True),
            Article(title="속보", url="https://ex.com/2", content=None, crawl_status="no_content"),
            Article(title="크롤실패", url="https://ex.com/3", content=None, crawl_status="failed"),
        ]
        if st.button("노드 실행", key="a04_node"):
            try:
                sentiment_node({"articles": samples})
                for a in samples:
                    s = a.sentiment.value if a.sentiment else "None (skip)"
                    sc = f"{a.sentiment_score:.3f}" if a.sentiment_score is not None else "—"
                    st.write(f"`{a.crawl_status}` · **{a.title}** → 감성 **{s}** / score {sc}")
            except Exception as exc:
                st.error(f"노드 실패: {exc}")


# ===========================================================================
# TASK 05 — 임베딩(embedder) & 이벤트 병합(event_merge) + 노드
# ===========================================================================
elif TASK.startswith("TASK 05"):
    st.header("TASK 05 — 임베딩 & 이벤트 병합")
    st.caption(
        "summary 를 임베딩해(대칭, 프리픽스 없음) 가중 점수로 이벤트에 편입/신규 판정. "
        "기존 이벤트 조회는 주입 provider(여기선 fake)로만 — 실제 DB/backend 는 부르지 않습니다(절대규칙 1)."
    )

    _EMBED_DIM = 64

    def _mock_embed_raw(texts):
        """가짜 임베딩: 문자 bigram 해싱 BoW 벡터. 비슷한 요약일수록 코사인이 높아 병합을 눈으로 볼 수 있다.
        실제 arctic 모델을 부르지 않는 시임 교체(테스트와 같은 방식). 순서·길이는 입력과 일치."""
        out = []
        for t in texts:
            s = "".join((t or "").split())
            v = [0.0] * _EMBED_DIM
            grams = [s[i:i + 2] for i in range(len(s) - 1)] or ([s] if s else [])
            for g in grams:
                h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
                v[h % _EMBED_DIM] += 1.0
            out.append(v)
        return out

    class _DemoProvider:
        """주입형 fake RecentEventProvider — 고정 후보를 돌려준다(backend 조회 결과 대역)."""

        def __init__(self, candidates):
            self._candidates = candidates

        def get_recent_events(self, companies, within_days):
            return list(self._candidates)

    def _parse_iso(value):
        """ISO 문자열 → datetime(aware). 빈 값/파싱 실패는 None."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    emb_mode = st.sidebar.radio("임베딩 모드", ["Mock (문자 bigram 해싱)", "실제 arctic 모델"])
    if emb_mode.startswith("Mock"):
        embedder._embed_raw = _mock_embed_raw  # 테스트와 같은 시임 교체
        st.sidebar.success("Mock: 실제 임베딩 모델을 부르지 않습니다.")
    else:
        embedder._embed_raw = getattr(embedder, "_orig_embed_raw")  # 원본 복원(실제 arctic)
        st.sidebar.info("실제 모드: 첫 임베딩 시 모델을 내려받습니다(수백 MB).")

    st.sidebar.caption(
        f"가중치 summary/company/time = {config.MERGE_W_SUMMARY}/{config.MERGE_W_COMPANY}/{config.MERGE_W_TIME} · "
        f"임계값 {config.MERGE_THRESHOLD} · 후보창 {config.MERGE_CANDIDATE_WINDOW_DAYS}일 · "
        f"시간감쇠 {config.MERGE_TIME_DECAY_DAYS}일"
    )

    t_emb, t_sim, t_dec, t_node = st.tabs(
        ["① 임베딩", "② 유사도(순수함수)", "③ 병합 판정", "④ 노드(embedding→merge)"]
    )

    # -----------------------------------------------------------------------
    # ① embed_batch + 쌍별 코사인
    # -----------------------------------------------------------------------
    with t_emb:
        st.subheader("embed_batch — 요약 여러 건 → 벡터 + 쌍별 코사인")
        st.caption("반환 순서·길이는 입력과 일치, 빈 줄은 None(임베딩 없음). 프리픽스 없이 대칭 임베딩.")
        default_sums = (
            "삼성전자가 엔비디아에 HBM을 공급하는 계약을 체결했다\n"
            "삼성전자, 엔비디아향 HBM 공급 계약 체결을 공식 발표했다\n"
            "국민연금 매도폭탄에 코스피가 급락했다"
        )
        raw = st.text_area("요약들(줄바꿈)", default_sums, height=140, key="a05_emb")
        if st.button("임베딩 실행", key="a05_emb_btn"):
            texts = [ln for ln in raw.splitlines() if ln.strip()]
            vecs = embedder.embed_batch(texts)
            st.dataframe(
                [
                    {"summary": t, "dim": (len(v) if v else 0),
                     "L2 norm": (round(sum(x * x for x in v) ** 0.5, 3) if v else 0.0),
                     "none": v is None}
                    for t, v in zip(texts, vecs)
                ],
                use_container_width=True,
            )
            st.write("**쌍별 코사인 유사도** (1에 가까울수록 같은 사건)")
            matrix = []
            for i, vi in enumerate(vecs):
                row = {"": f"[{i}] {texts[i][:12]}…"}
                for j, vj in enumerate(vecs):
                    row[f"[{j}]"] = round(cosine_similarity(vi, vj), 3) if (vi and vj) else None
                matrix.append(row)
            st.dataframe(matrix, use_container_width=True)
            st.caption("①②는 같은 사건이라 코사인이 높고, ③은 다른 사건이라 낮게 나오면 정상입니다.")

    # -----------------------------------------------------------------------
    # ② 순수 함수 놀이터
    # -----------------------------------------------------------------------
    with t_sim:
        st.subheader("순수 함수 — cosine / company_overlap / time_proximity")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**company_overlap** (Jaccard · 한쪽 비면 0)")
            ca = st.text_input("회사 A(쉼표)", "삼성전자, SK하이닉스", key="a05_ca")
            cb = st.text_input("회사 B(쉼표)", "㈜삼성전자", key="a05_cb")
            la = [x.strip() for x in ca.split(",") if x.strip()]
            lb = [x.strip() for x in cb.split(",") if x.strip()]
            st.metric("overlap", round(company_overlap(la, lb), 3))
            st.caption("㈜/(주)·공백 차이는 normalize_entity_name 으로 접힙니다(TASK 07 노드 key 와 동일 기준).")
        with c2:
            st.markdown("**time_proximity** (exp 감쇠 · None→0)")
            d1 = st.date_input("발생일 1", value=date(2026, 7, 6), key="a05_d1")
            d2 = st.date_input("발생일 2", value=date(2026, 7, 6), key="a05_d2")
            t1 = datetime.combine(d1, datetime.min.time()).replace(tzinfo=timezone.utc)
            t2 = datetime.combine(d2, datetime.min.time()).replace(tzinfo=timezone.utc)
            st.metric("proximity", round(time_proximity(t1, t2), 3))
            st.caption(f"Δ가 커질수록 0으로 감쇠(스케일 {config.MERGE_TIME_DECAY_DAYS}일).")

        st.divider()
        st.markdown("**cosine_similarity** — 두 요약을 임베딩해 계산")
        s1 = st.text_input("요약 1", "삼성전자 HBM 공급 계약 체결", key="a05_s1")
        s2 = st.text_input("요약 2", "삼성전자, 엔비디아향 HBM 공급 계약", key="a05_s2")
        if st.button("코사인 계산", key="a05_cos"):
            v1, v2 = embedder.embed(s1), embedder.embed(s2)
            if v1 and v2:
                st.metric("cosine", round(cosine_similarity(v1, v2), 3))
            else:
                st.warning("빈 입력은 임베딩 없음(None)")

    # -----------------------------------------------------------------------
    # ③ decide_merge (fake provider 주입)
    # -----------------------------------------------------------------------
    with t_dec:
        st.subheader("decide_merge — 편입 vs 신규 (fake provider 주입)")
        st.caption("후보 이벤트를 JSON 으로 정의(=backend 조회 결과 대역). 후보 요약을 임베딩해 대표 벡터로 씁니다.")
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**새 기사**")
            a_sum = st.text_area(
                "summary", "삼성전자가 엔비디아에 HBM을 공급하는 계약을 체결했다", height=90, key="a05_asum"
            )
            a_co = st.text_input("companies(쉼표)", "삼성전자", key="a05_aco")
            a_date = st.text_input("event_date(ISO · 빈칸=없음)", "2026-07-06T09:00:00+09:00", key="a05_adate")
        with col_b:
            st.markdown("**후보 이벤트들(JSON)**")
            default_cands = json.dumps(
                [
                    {"canonical_id": "evt-HBM", "summary": "삼성전자가 엔비디아에 HBM 공급 계약을 맺었다",
                     "companies": ["삼성전자"], "event_time": "2026-07-06T09:00:00+09:00"},
                    {"canonical_id": "evt-pension", "summary": "국민연금 매도폭탄에 코스피가 급락했다",
                     "companies": ["삼성전자"], "event_time": "2026-07-05T09:00:00+09:00"},
                ],
                ensure_ascii=False, indent=2,
            )
            cands_raw = st.text_area("candidates", default_cands, height=210, key="a05_cands")

        if st.button("판정 실행", key="a05_decide"):
            try:
                cand_specs = json.loads(cands_raw)
            except json.JSONDecodeError as exc:
                st.error(f"후보 JSON 오류: {exc}")
                cand_specs = None

            if cand_specs is not None:
                cand_events = [
                    CandidateEvent(
                        canonical_id=spec["canonical_id"],
                        companies=spec.get("companies", []),
                        embedding=embedder.embed(spec.get("summary", "")) or [],
                        event_time=_parse_iso(spec.get("event_time")),
                    )
                    for spec in cand_specs
                ]
                provider = _DemoProvider(cand_events)
                art = Article(title="새 기사", url="https://ex.com/new", summary=a_sum)
                art.embedding = embedder.embed(a_sum)
                ext = ExtractResult(
                    summary=a_sum,
                    companies=[c.strip() for c in a_co.split(",") if c.strip()],
                    events=[EventCandidate(title="HBM 공급 계약", confidence=0.9)],
                    event_date=_parse_iso(a_date) if a_date.strip() else None,
                )
                decision = event_merge.decide_merge(art, ext, provider)
                if decision is None:
                    st.warning("임베딩 없음 → 병합 skip(None). summary 가 비어 있는지 확인하세요.")
                else:
                    verdict = "🆕 신규 이벤트" if decision.is_new_event else f"➡️ 편입: {decision.assigned_event_id}"
                    st.success(f"{verdict} · best_score={decision.best_score}")
                    st.caption(f"임계값 {config.MERGE_THRESHOLD} 이상이면 편입, 미만이면 신규(억지 편입 금지).")
                    st.dataframe(
                        [
                            {"event_id": c.event_id, "score": round(c.score, 3),
                             "summary×0.6": round(c.summary_similarity or 0, 3),
                             "company×0.3": round(c.company_overlap or 0, 3),
                             "time×0.1": round(c.time_similarity or 0, 3)}
                            for c in decision.candidates
                        ],
                        use_container_width=True,
                    )
                    if decision.is_new_event:
                        st.write("**규칙 기반 canonical (신규 이벤트):**")
                        st.code(_model_json(event_merge.new_event(ext)), language="json")

    # -----------------------------------------------------------------------
    # ④ 노드 파이프라인: embedding_node → merge_event_node
    # -----------------------------------------------------------------------
    with t_node:
        st.subheader("embedding_node → merge_event_node (배치)")
        st.caption(
            "요약 있는 기사만 임베딩 → 병합. provider 미주입(빈 backend)이라 모두 신규지만, "
            "같은 배치의 동일 사건 둘째 기사는 첫 기사가 만든 이벤트로 편입됩니다(배치 내 중복 신규 방지)."
        )
        default_arts = json.dumps(
            [
                {"url": "https://ex.com/1", "title": "삼성 HBM ①",
                 "summary": "삼성전자가 엔비디아에 HBM을 공급하는 계약을 체결했다",
                 "companies": ["삼성전자"], "event_title": "HBM 공급 계약",
                 "event_date": "2026-07-06T09:00:00+09:00"},
                {"url": "https://ex.com/2", "title": "삼성 HBM ②(같은 사건)",
                 "summary": "삼성전자, 엔비디아향 HBM 공급 계약 체결을 공식 발표했다",
                 "companies": ["삼성전자"], "event_title": "HBM 공급 계약",
                 "event_date": "2026-07-06T10:00:00+09:00"},
                {"url": "https://ex.com/3", "title": "연금 매도(다른 사건)",
                 "summary": "국민연금 매도폭탄에 코스피가 급락했다",
                 "companies": ["삼성전자"], "event_title": "국민연금 매도",
                 "event_date": "2026-07-05T09:00:00+09:00"},
                {"url": "https://ex.com/4", "title": "요약 없음(skip)",
                 "summary": "", "companies": [], "event_title": "", "event_date": None},
            ],
            ensure_ascii=False, indent=2,
        )
        arts_raw = st.text_area("기사들(JSON)", default_arts, height=260, key="a05_arts")
        if st.button("파이프라인 실행", key="a05_node"):
            try:
                specs = json.loads(arts_raw)
            except json.JSONDecodeError as exc:
                st.error(f"JSON 오류: {exc}")
                specs = None

            if specs is not None:
                articles, extracts = [], {}
                for spec in specs:
                    art = Article(title=spec.get("title", "기사"), url=spec["url"],
                                  summary=(spec.get("summary") or None))
                    articles.append(art)
                    extracts[str(art.url)] = ExtractResult(
                        summary=(spec.get("summary") or ""),
                        companies=spec.get("companies", []),
                        events=[EventCandidate(title=(spec.get("event_title") or "사건"), confidence=0.8)],
                        event_date=_parse_iso(spec.get("event_date")),
                    )
                state = {"articles": articles, "extracts_by_url": extracts}
                embedding_node(state)      # summary 있는 기사만 Article.embedding 채움
                merge_event_node(state)    # provider 미주입 → 기본(빈 후보), 배치 내 누적 편입

                st.success(f"이번 배치 이벤트 {len(state.get('events_by_id', {}))}개 생성")
                st.dataframe(
                    [
                        {"title": a.title,
                         "embedding": ("있음" if a.embedding else "없음"),
                         "event_id": (a.event_id[:8] + "…" if a.event_id else None),
                         "analysis_completed": a.analysis_completed}
                        for a in articles
                    ],
                    use_container_width=True,
                )
                st.write("**events_by_id (이번 배치 생성 이벤트):**")
                for cid, ev in state.get("events_by_id", {}).items():
                    st.write(f"`{cid[:8]}…` · **{ev.canonical_title}** · {ev.companies}")
                st.caption(
                    "①②가 같은 event_id 로 묶이고, ③은 다른 이벤트, ④(요약 없음)는 event_id=None·"
                    "analysis_completed=False 이면 정상입니다."
                )


# ===========================================================================
# TASK 06 — 중요도(importance): publisher_weight / sentiment_magnitude /
#           compute_importance / importance_node (순수·결정적, mock 불필요)
# ===========================================================================
elif TASK.startswith("TASK 06"):
    st.header("TASK 06 — 중요도(importance)")
    st.caption(
        "importance = 기사 개수 + 언론사 가중치 + 감성 절대값 (pipeline_spec §9). LLM 아님 · "
        "결정적 계산(같은 입력→같은 출력). 기존 이벤트 통계는 주입 provider(여기선 fake)로만 — "
        "DB/backend 를 직접 부르지 않습니다(절대규칙 1)."
    )
    st.sidebar.caption(
        f"가중치 volume/publisher/sentiment = {config.IMPORTANCE_W_VOLUME}/"
        f"{config.IMPORTANCE_W_PUBLISHER}/{config.IMPORTANCE_W_SENTIMENT} · "
        f"volume 변환 = {config.IMPORTANCE_VOLUME_MODE} · "
        f"미등록/None 기본 가중치 {config.IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT}"
    )
    st.sidebar.caption("⚠️ 언론사 가중치 테이블·계수는 미확정(임시값, CLAUDE.md §8).")
    st.sidebar.info("importance 는 순수 계산이라 mock 이 없습니다 — 실제 함수를 그대로 호출합니다.")

    _SENT_OPTS = {"긍정": Sentiment.POSITIVE, "중립": Sentiment.NEUTRAL,
                  "부정": Sentiment.NEGATIVE, "None (감성 없음)": None}

    def _parse_sentiment(value):
        """데모 입력 문자열 → Sentiment | None. 빈 값/None/미지원은 None(집계 제외)."""
        if value in (None, "", "None"):
            return None
        try:
            return Sentiment(value)   # "긍정"/"중립"/"부정"
        except ValueError:
            return None

    def _article_from_spec(spec) -> Article:
        """데모 스펙(dict) → Article. importance 는 publisher·sentiment·sentiment_score·event_id 만 본다."""
        return Article(
            title=spec.get("title", "기사"),
            url=spec["url"],
            publisher=spec.get("publisher"),
            sentiment=_parse_sentiment(spec.get("sentiment")),
            sentiment_score=spec.get("sentiment_score"),
            event_id=spec.get("event_id"),
        )

    def _existing_from_spec(spec) -> EventArticleStats:
        return EventArticleStats(
            article_count=spec.get("article_count", 0),
            publishers=spec.get("publishers", []),
            sentiment_magnitude_sum=spec.get("sentiment_magnitude_sum", 0.0),
            sentiment_count=spec.get("sentiment_count", 0),
        )

    def _breakdown(articles, existing):
        """데모 표시용 하위 점수 분해(서비스의 공개/내부 함수를 그대로 호출해 재현).

        총점(total)은 compute_importance 가 소스오브트루스다 — 아래 세 항의 합과 일치해야 한다.
        """
        total_count = len(articles) + (existing.article_count if existing else 0)
        vol_raw = importance._volume_transform(total_count)
        vol_score = config.IMPORTANCE_W_VOLUME * vol_raw

        pub_keys = {importance._normalize_publisher(a.publisher) for a in articles}
        if existing:
            pub_keys |= {importance._normalize_publisher(p) for p in existing.publishers}
        pub_sum = sum(importance.publisher_weight(k) for k in pub_keys)
        pub_score = config.IMPORTANCE_W_PUBLISHER * pub_sum

        mags = [m for m in (importance.sentiment_magnitude(a) for a in articles) if m is not None]
        t_sum = sum(mags) + (existing.sentiment_magnitude_sum if existing else 0.0)
        t_cnt = len(mags) + (existing.sentiment_count if existing else 0)
        sent_avg = (t_sum / t_cnt) if t_cnt else 0.0
        sent_score = config.IMPORTANCE_W_SENTIMENT * sent_avg
        return {
            "total_count": total_count, "vol_raw": vol_raw, "vol_score": vol_score,
            "distinct_publishers": pub_keys, "pub_sum": pub_sum, "pub_score": pub_score,
            "sentiment_n": t_cnt, "sentiment_avg": sent_avg, "sent_score": sent_score,
        }

    t_sig, t_compute, t_node = st.tabs(
        ["① 신호 함수", "② compute_importance", "③ 노드(importance_node)"]
    )

    # -----------------------------------------------------------------------
    # ① publisher_weight / sentiment_magnitude
    # -----------------------------------------------------------------------
    with t_sig:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("publisher_weight — 언론사 가중치")
            st.caption("테이블 조회 · 미등록/None → 기본값. 가중치 적용은 오직 이 함수에서만.")
            pub = st.text_input("언론사명(빈칸=None)", "매일경제", key="a06_pub")
            weight = importance.publisher_weight(pub or None)
            registered = importance._normalize_publisher(pub or None) in config.IMPORTANCE_PUBLISHER_WEIGHTS
            st.metric("weight", weight, "테이블 등록" if registered else "기본값(미등록/None)")
            st.write("**IMPORTANCE_PUBLISHER_WEIGHTS (⚠️ 임시값)**")
            st.dataframe(
                [{"publisher": k, "weight": v} for k, v in config.IMPORTANCE_PUBLISHER_WEIGHTS.items()],
                use_container_width=True,
            )
        with c2:
            st.subheader("sentiment_magnitude — 감성 절대값(세기)")
            st.caption("긍/부 → sentiment_score · 중립 → 0.0 · None → None(집계 제외). 방향은 버림.")
            label = st.selectbox("sentiment", list(_SENT_OPTS.keys()), key="a06_sent")
            score = st.slider("sentiment_score (confidence)", 0.0, 1.0, 0.9, 0.01, key="a06_score")
            art = Article(title="t", url="https://ex.com/x",
                          sentiment=_SENT_OPTS[label], sentiment_score=score)
            mag = importance.sentiment_magnitude(art)
            st.metric("magnitude", "None (집계 제외)" if mag is None else round(mag, 4))
            st.caption("긍정 0.9 와 부정 0.9 는 같은 magnitude — importance 는 방향이 아니라 세기만 봅니다.")

    # -----------------------------------------------------------------------
    # ② compute_importance — 배치 기사(+선택적 existing) 합산
    # -----------------------------------------------------------------------
    with t_compute:
        st.subheader("compute_importance — 한 이벤트의 importance")
        st.caption(
            "배치 기사(미저장 신규)에 existing(저장된 누적 통계)을 합산해 전체 재계산. "
            "existing 없으면 신규 이벤트(배치만으로 정확), 있으면 편입 이벤트."
        )
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**이번 배치 기사(JSON)**")
            default_arts = json.dumps(
                [
                    {"url": "https://ex.com/1", "publisher": "매일경제", "sentiment": "긍정", "sentiment_score": 0.92},
                    {"url": "https://ex.com/2", "publisher": "한국경제", "sentiment": "부정", "sentiment_score": 0.88},
                    {"url": "https://ex.com/3", "publisher": "매일경제", "sentiment": "중립", "sentiment_score": 0.60},
                    {"url": "https://ex.com/4", "publisher": "블로그미상", "sentiment": None, "sentiment_score": None},
                ],
                ensure_ascii=False, indent=2,
            )
            arts_raw = st.text_area("articles", default_arts, height=240, key="a06_arts")
        with col_b:
            st.markdown("**기존 통계 existing (편입 이벤트일 때)**")
            use_existing = st.checkbox("existing 사용(편입 이벤트)", value=False, key="a06_use_ex")
            default_ex = json.dumps(
                {"article_count": 5, "publishers": ["조선일보", "매일경제"],
                 "sentiment_magnitude_sum": 2.4, "sentiment_count": 3},
                ensure_ascii=False, indent=2,
            )
            ex_raw = st.text_area("existing (EventArticleStats)", default_ex, height=180,
                                  key="a06_ex", disabled=not use_existing)

        if st.button("importance 계산", key="a06_compute"):
            try:
                specs = json.loads(arts_raw)
                existing = _existing_from_spec(json.loads(ex_raw)) if use_existing else None
            except json.JSONDecodeError as exc:
                st.error(f"JSON 오류: {exc}")
            else:
                articles = [_article_from_spec(s) for s in specs]
                total = importance.compute_importance(articles, existing)
                bd = _breakdown(articles, existing)
                st.metric("importance", round(total, 4))
                st.dataframe(
                    [
                        {"신호": "volume(기사 수)",
                         "원값": f"{bd['total_count']}건 → {config.IMPORTANCE_VOLUME_MODE}={round(bd['vol_raw'], 4)}",
                         "가중치": config.IMPORTANCE_W_VOLUME, "기여": round(bd["vol_score"], 4)},
                        {"신호": "publisher(distinct 합)",
                         "원값": f"{sorted(str(k) for k in bd['distinct_publishers'])} → sum={round(bd['pub_sum'], 4)}",
                         "가중치": config.IMPORTANCE_W_PUBLISHER, "기여": round(bd["pub_score"], 4)},
                        {"신호": "sentiment(평균 세기)",
                         "원값": f"n={bd['sentiment_n']} → avg={round(bd['sentiment_avg'], 4)}",
                         "가중치": config.IMPORTANCE_W_SENTIMENT, "기여": round(bd["sent_score"], 4)},
                    ],
                    use_container_width=True,
                )
                recomposed = bd["vol_score"] + bd["pub_score"] + bd["sent_score"]
                st.caption(
                    f"세 기여 합 {round(recomposed, 6)} = compute_importance {round(total, 6)} "
                    f"({'일치 ✅' if abs(recomposed - total) < 1e-9 else '불일치 ⚠️'}). "
                    "distinct 언론사 합(중복 매체는 1회) · None 감성은 분모 제외 · 중립은 0 강도로 포함."
                )

    # -----------------------------------------------------------------------
    # ③ importance_node — event_id 별 묶기·반영 + fake provider
    # -----------------------------------------------------------------------
    with t_node:
        st.subheader("importance_node — 이벤트별 묶기 → 계산 → 반영")
        st.caption(
            "event_id 배정 기사만 이벤트별로 묶어 계산. 모든 영향 이벤트를 importance_by_event_id 에, "
            "신규 이벤트(events_by_id)의 Event.importance 에 반영. provider stats 가 있는 event_id 는 "
            "'편입(기존)'으로 취급(Event 객체 없이 map 에만 실림)."
        )
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**기사들(JSON · event_id 포함)**")
            default_node_arts = json.dumps(
                [
                    {"url": "https://ex.com/1", "event_id": "evt-A", "publisher": "매일경제", "sentiment": "긍정", "sentiment_score": 0.90},
                    {"url": "https://ex.com/2", "event_id": "evt-A", "publisher": "한국경제", "sentiment": "부정", "sentiment_score": 0.85},
                    {"url": "https://ex.com/3", "event_id": "evt-B", "publisher": "한겨레", "sentiment": "중립", "sentiment_score": 0.60},
                    {"url": "https://ex.com/4", "event_id": None, "publisher": "조선일보", "sentiment": "긍정", "sentiment_score": 0.70},
                ],
                ensure_ascii=False, indent=2,
            )
            node_arts_raw = st.text_area("articles", default_node_arts, height=260, key="a06_node_arts")
        with col_b:
            st.markdown("**provider 통계(event_id → EventArticleStats)**")
            st.caption("여기 있는 event_id = 편입(기존). 없는 event_id = 이번 배치 신규.")
            default_provider = json.dumps(
                {"evt-A": {"article_count": 3, "publishers": ["세계일보"],
                           "sentiment_magnitude_sum": 1.5, "sentiment_count": 2}},
                ensure_ascii=False, indent=2,
            )
            provider_raw = st.text_area("provider stats", default_provider, height=260, key="a06_provider")

        if st.button("노드 실행", key="a06_node_run"):
            try:
                specs = json.loads(node_arts_raw)
                stats_specs = json.loads(provider_raw) or {}
            except json.JSONDecodeError as exc:
                st.error(f"JSON 오류: {exc}")
            else:
                provider_stats = {eid: _existing_from_spec(s) for eid, s in stats_specs.items()}

                class _DemoStatsProvider:
                    """주입형 fake EventArticleStatsProvider — 고정 통계를 돌려준다(backend 대역)."""

                    def __init__(self, stats):
                        self._stats = stats
                        self.calls = []

                    def get_event_article_stats(self, event_id):
                        self.calls.append(event_id)
                        return self._stats.get(event_id)

                articles = [_article_from_spec(s) for s in specs]
                assigned_ids = {a.event_id for a in articles if a.event_id}
                # provider 통계가 없는 event_id 만 '이번 배치 신규'로 Event 객체를 만든다(편입은 map 에만).
                events_by_id = {
                    eid: Event(canonical_id=eid, canonical_title=f"이벤트 {eid}")
                    for eid in assigned_ids if eid not in provider_stats
                }
                provider = _DemoStatsProvider(provider_stats)
                state = {"articles": articles, "events_by_id": events_by_id}
                importance_node(state, provider=provider)

                st.write("**importance_by_event_id (모든 영향 이벤트 — 신규+편입):**")
                st.dataframe(
                    [
                        {"event_id": eid, "importance": round(score, 4),
                         "종류": "편입(기존)" if eid in provider_stats else "신규",
                         "provider 조회됨": eid in provider.calls}
                        for eid, score in state["importance_by_event_id"].items()
                    ],
                    use_container_width=True,
                )
                st.write("**events_by_id (신규 이벤트만 — Event.importance 직접 반영):**")
                st.dataframe(
                    [
                        {"canonical_id": cid, "canonical_title": ev.canonical_title,
                         "importance": (round(ev.importance, 4) if ev.importance is not None else None)}
                        for cid, ev in events_by_id.items()
                    ],
                    use_container_width=True,
                )
                skipped = [str(a.url) for a in articles if not a.event_id]
                st.caption(
                    f"event_id 없는 기사 {len(skipped)}건은 대상 아님(병합 skip): {skipped}. "
                    "편입 이벤트(evt-A)는 Event 객체 없이 map 에만, 신규(evt-B)는 map + Event.importance 둘 다."
                )


# ===========================================================================
# TASK 07 — 지식그래프 조립(graph_builder): build_graph_batch / graph_node
#           (순수 매핑 · 결정적 · mock 불필요 — LLM/backend/DB 미호출)
# ===========================================================================
elif TASK.startswith("TASK 07"):
    st.header("TASK 07 — 지식그래프 조립(GraphBatch 델타)")
    st.caption(
        "event_id 배정 기사·ExtractResult·Event·importance → GraphBatch(노드·관계 델타). "
        "backend 가 key 기준 MERGE(upsert)로 합칠 payload 만 만듭니다 — 실제 Neo4j 저장은 TASK 08. "
        "순수 매핑이라 mock 이 없습니다(LLM·backend·DB 미호출, 절대규칙 1)."
    )

    # 3차·보류 관계 토글: config 값을 그 순간만 덮어써 on/off 를 눈으로 본다(원본 config 는 유지).
    st.sidebar.markdown("**3차·보류 관계 토글**")
    en_belongs = st.sidebar.checkbox(
        "GRAPH_ENABLE_BELONGS_TO", value=config.GRAPH_ENABLE_BELONGS_TO,
        help="(Company)-[:BELONGS_TO]->(Sector). 기본 off — 회사↔산업 매핑 부재(pipeline_spec §12).",
    )
    en_related = st.sidebar.checkbox(
        "GRAPH_ENABLE_RELATED_TO", value=config.GRAPH_ENABLE_RELATED_TO,
        help="(Company)-[:RELATED_TO]->(Company). 기본 off — 공유이벤트 파생 규칙 미정(3차).",
    )
    # graph_builder 모듈이 import 시점에 읽어 온 전역을 그 순간만 교체(테스트 monkeypatch 와 같은 방식).
    graph_builder.GRAPH_ENABLE_BELONGS_TO = en_belongs
    graph_builder.GRAPH_ENABLE_RELATED_TO = en_related
    st.sidebar.caption(f"NewsRef 키 방식 = {config.GRAPH_NEWSREF_KEY!r} (빌드 시점엔 news_id 미부여 → url)")
    st.sidebar.caption("정체성 키: Event=canonical_id · 개체=정규화 이름 · NewsRef=url")

    _LABEL_ICON = {
        NodeLabel.EVENT: "🟣 Event", NodeLabel.COMPANY: "🏢 Company",
        NodeLabel.KEYWORD: "🔑 Keyword", NodeLabel.PERSON: "🧑 Person",
        NodeLabel.COUNTRY: "🌐 Country", NodeLabel.SECTOR: "🏭 Sector",
        NodeLabel.NEWS_REF: "📰 NewsRef",
    }

    def _demo_article(spec) -> Article:
        return Article(
            title=spec.get("title", "기사"),
            url=spec["url"],
            publisher=spec.get("publisher"),
            published_at=(
                datetime.fromisoformat(spec["published_at"])
                if spec.get("published_at") else None
            ),
            event_id=spec.get("event_id"),
        )

    def _demo_extract(spec) -> ExtractResult:
        return ExtractResult(
            summary=spec.get("summary", "요약"),
            companies=spec.get("companies", []),
            keywords=spec.get("keywords", []),
            people=spec.get("people", []),
            countries=spec.get("countries", []),
            industries=spec.get("industries", []),
        )

    def _render_batch(batch):
        """GraphBatch 를 노드·관계 표로 렌더. 감성 property 가 없음을 눈으로 확인할 수 있다."""
        c1, c2, c3 = st.columns(3)
        c1.metric("노드", len(batch.nodes))
        c2.metric("관계", len(batch.relationships))
        c3.metric("이벤트 노드", sum(1 for n in batch.nodes if n.label is NodeLabel.EVENT))

        st.write("**노드 (label + key = MERGE 정체성)**")
        st.dataframe(
            [
                {"label": _LABEL_ICON.get(n.label, n.label.value), "key": n.key,
                 "properties": json.dumps(n.properties, ensure_ascii=False)}
                for n in batch.nodes
            ],
            use_container_width=True,
        )
        st.write("**관계 (type + 양끝 노드 = MERGE 정체성)**")
        st.dataframe(
            [
                {"type": r.type.value,
                 "start": f"{r.start_label.value}:{r.start_key}",
                 "→": "→",
                 "end": f"{r.end_label.value}:{r.end_key}"}
                for r in batch.relationships
            ],
            use_container_width=True,
        )
        # 감성 미포함·news_id 미포함 자기검증(환각 금지·CLAUDE.md §5).
        bad = [
            n.key for n in batch.nodes
            for k in n.properties
            if any(t in k.lower() for t in ("sentiment", "count", "gauge", "news_id"))
        ]
        if bad:
            st.error(f"⚠️ 금지 property 발견(감성/news_id): {bad}")
        else:
            st.caption("✅ 어떤 노드에도 감성 count/분포·news_id property 없음(구조만, backend 가 해소).")

    t_build, t_node = st.tabs(["① build_graph_batch (서비스)", "② graph_node (노드 → state)"])

    # 데모 공통 기본 입력: 이벤트 2개(신규 evt-A / 편입 evt-B) · 회사 공유 · 개체 union.
    _DEFAULT_ARTICLES = json.dumps(
        [
            {"url": "https://ex.com/1", "title": "삼성 HBM ①", "publisher": "매일경제",
             "published_at": "2026-07-06T09:00:00+09:00", "event_id": "evt-A",
             "summary": "삼성전자가 엔비디아에 HBM 공급 계약을 체결했다",
             "companies": ["삼성전자"], "keywords": ["HBM", "반도체"],
             "people": ["이재용"], "countries": ["미국"], "industries": ["반도체"]},
            {"url": "https://ex.com/2", "title": "삼성 HBM ②(같은 이벤트)", "publisher": "한국경제",
             "published_at": "2026-07-06T10:00:00+09:00", "event_id": "evt-A",
             "summary": "삼성전자, 엔비디아향 HBM 공급 물량 확대",
             "companies": ["삼성전자", "SK하이닉스"], "keywords": ["HBM"],
             "people": [], "countries": [], "industries": []},
            {"url": "https://ex.com/3", "title": "SK 편입 이벤트", "publisher": "한겨레",
             "published_at": "2026-07-05T09:00:00+09:00", "event_id": "evt-B",
             "summary": "SK하이닉스 실적 발표",
             "companies": ["SK하이닉스"], "keywords": ["실적"],
             "people": [], "countries": [], "industries": []},
            {"url": "https://ex.com/4", "title": "병합 skip(event_id 없음)", "publisher": "조선일보",
             "published_at": None, "event_id": None,
             "summary": "", "companies": ["현대차"], "keywords": []},
        ],
        ensure_ascii=False, indent=2,
    )
    # events_by_id = 이번 배치 신규 이벤트(full 노드). 여기 없는 event_id 는 편입(얇은 노드).
    _DEFAULT_EVENTS = json.dumps(
        [{"canonical_id": "evt-A", "canonical_title": "HBM 공급 계약", "companies": ["삼성전자"]}],
        ensure_ascii=False, indent=2,
    )
    _DEFAULT_IMPORTANCE = json.dumps({"evt-A": 2.31, "evt-B": 1.05}, ensure_ascii=False, indent=2)

    def _inputs(key_prefix):
        col_a, col_b = st.columns([3, 2])
        with col_a:
            st.markdown("**기사들(JSON · event_id·개체 포함)**")
            arts_raw = st.text_area("articles", _DEFAULT_ARTICLES, height=340, key=f"{key_prefix}_arts")
        with col_b:
            st.markdown("**신규 이벤트 events_by_id (JSON 리스트)**")
            st.caption("여기 있는 event_id = 신규(canonical_title 실린 full 노드). 없으면 편입(얇은 노드).")
            events_raw = st.text_area("events", _DEFAULT_EVENTS, height=150, key=f"{key_prefix}_events")
            st.markdown("**importance_by_event_id (JSON)**")
            imp_raw = st.text_area("importance", _DEFAULT_IMPORTANCE, height=120, key=f"{key_prefix}_imp")
        return arts_raw, events_raw, imp_raw

    def _parse_inputs(arts_raw, events_raw, imp_raw):
        specs = json.loads(arts_raw)
        event_specs = json.loads(events_raw) or []
        importance_by_event_id = json.loads(imp_raw) or {}
        articles = [_demo_article(s) for s in specs]
        extracts_by_url = {str(a.url): _demo_extract(s) for a, s in zip(articles, specs)}
        events_by_id = {
            e["canonical_id"]: Event(
                canonical_id=e["canonical_id"],
                canonical_title=e["canonical_title"],
                companies=e.get("companies", []),
                importance=e.get("importance"),
            )
            for e in event_specs
        }
        return articles, extracts_by_url, events_by_id, importance_by_event_id

    # -----------------------------------------------------------------------
    # ① build_graph_batch — 서비스 직접 호출
    # -----------------------------------------------------------------------
    with t_build:
        st.subheader("build_graph_batch — 이벤트별 묶기 → 서브그래프 → dedup·정렬")
        st.caption(
            "신규(evt-A)는 canonical_title 실린 full Event 노드, 편입(evt-B)은 canonical_title 없는 얇은 노드. "
            "회사(삼성전자)는 두 이벤트 공유 → Company 노드 1개·PARTICIPATES_IN 은 이벤트마다."
        )
        arts_raw, events_raw, imp_raw = _inputs("a07_build")
        if st.button("GraphBatch 조립", key="a07_build_btn"):
            try:
                articles, extracts, events, imp = _parse_inputs(arts_raw, events_raw, imp_raw)
            except (json.JSONDecodeError, KeyError, ValidationError) as exc:
                st.error(f"입력 오류: {exc}")
            else:
                batch = graph_builder.build_graph_batch(articles, extracts, events, imp)
                _render_batch(batch)
                # 결정성 자기검증: 같은 입력 두 번 → 동일 payload.
                again = graph_builder.build_graph_batch(articles, extracts, events, imp)
                same = batch.model_dump() == again.model_dump()
                st.caption(f"결정성: 같은 입력 재조립 결과 {'동일 ✅' if same else '다름 ⚠️'} (정렬·dedup).")

    # -----------------------------------------------------------------------
    # ② graph_node — state 반영(얇은 노드)
    # -----------------------------------------------------------------------
    with t_node:
        st.subheader("graph_node — state['graph_batch'] 반영")
        st.caption(
            "얇은 노드: build_graph_batch 를 호출해 state['graph_batch'] 에 싣기만 함(backend 미호출). "
            "대상 0건이면 빈 GraphBatch, 서비스 실패해도 빈 GraphBatch 로 통과(§7)."
        )
        arts_raw, events_raw, imp_raw = _inputs("a07_node")
        if st.button("graph_node 실행", key="a07_node_btn"):
            try:
                articles, extracts, events, imp = _parse_inputs(arts_raw, events_raw, imp_raw)
            except (json.JSONDecodeError, KeyError, ValidationError) as exc:
                st.error(f"입력 오류: {exc}")
            else:
                state = {
                    "articles": articles,
                    "extracts_by_url": extracts,
                    "events_by_id": events,
                    "importance_by_event_id": imp,
                }
                out = graph_node(state)
                batch = out["graph_batch"]
                st.success(
                    f"state['graph_batch'] 채워짐 · 노드 {len(batch.nodes)}개 · 관계 {len(batch.relationships)}개"
                )
                _render_batch(batch)
                st.caption("➡️ 이 GraphBatch 를 TASK 08 이 backend 로 보내 Neo4j MERGE(url→news_id 해소)합니다.")


# ===========================================================================
# TASK 08 — backend HTTP 클라이언트: save_client · providers · query_client · save_node
#   실제 backend(:8000) 없이 BackendClient._request 를 mock 시임으로 교체(테스트와 동일 방식).
#   save_client/providers/query_client/save_node 는 '진짜 코드 경로'를 그대로 타고, HTTP 한 겹만 mock 이다.
# ===========================================================================
elif TASK.startswith("TASK 08"):
    st.header("TASK 08 — backend 클라이언트(저장·조회·삭제)")
    st.caption(
        "이 에이전트가 PostgreSQL·Neo4j 에 닿는 **유일 경로** = services/backend/ 의 HTTP 클라이언트(절대규칙 1). "
        "실제 backend 없이 BackendClient._request 한 겹만 mock 으로 교체해, save/query/provider/node 의 "
        "실제 코드 경로와 **degrade vs 정확보고** 계약(§4.2)을 눈으로 확인합니다."
    )
    st.sidebar.caption(f"BACKEND_BASE_URL = {config.BACKEND_BASE_URL}")
    st.sidebar.caption(
        f"timeout {config.BACKEND_TIMEOUT}s · retries {config.BACKEND_MAX_RETRIES} · backoff {config.BACKEND_RETRY_BACKOFF}s"
    )
    st.sidebar.caption("⚠️ 엔드포인트 경로는 잠정값(api_contract.md 확정 전, §8).")
    st.sidebar.info("mock: BackendClient._request 를 교체 — SQL·Cypher·네트워크 없음.")

    @contextlib.contextmanager
    def _mock_backend(result=None, error: Exception | None = None, recorder: list | None = None):
        """BackendClient._request 를 그 순간만 mock 으로 교체(테스트 monkeypatch 와 동일). 종료 시 원복.

        - result: 정상 응답(JSON 자리). error: 주면 raise(연결 실패·5xx 등 대역).
        - recorder: 호출(method·path·json·params)을 기록해 payload/파라미터를 화면에 보여준다.
        """
        orig = backend_client.BackendClient._request

        def fake(self, method, path, json=None, params=None):
            if recorder is not None:
                recorder.append({"method": method, "path": path, "json": json, "params": params})
            if error is not None:
                raise error
            return result

        backend_client.BackendClient._request = fake
        try:
            yield
        finally:
            backend_client.BackendClient._request = orig

    def _fail_exc():
        """조회/쓰기 실패 대역: client 계층이 변환해 올리는 BackendError(연결 실패·5xx 소진)."""
        return backend_client.BackendError("mock: backend 연결 실패(5xx/timeout)")

    _SCEN = {"정상 응답": False, "실패 (BackendError)": True}

    t_save, t_cleanup, t_prov, t_query, t_node = st.tabs(
        ["① save_batch", "② request_cleanup", "③ providers(조회 degrade)", "④ query_client", "⑤ save_node"]
    )

    # 데모 공통: 저장할 분석완료 기사 2건(url UNIQUE·news_id 없음) + 같은 배치 GraphBatch 델타(NewsRef=url).
    _DEMO_SAVE_ARTS = json.dumps(
        [
            {"url": "https://ex.com/1", "title": "삼성 HBM 공급 계약", "publisher": "매일경제",
             "summary": "삼성전자가 엔비디아에 HBM 공급 계약을 체결했다", "sentiment": "긍정",
             "sentiment_score": 0.94, "event_id": "evt-A"},
            {"url": "https://ex.com/2", "title": "SK 실적", "publisher": "한국경제",
             "summary": "SK하이닉스 실적 발표", "sentiment": "중립",
             "sentiment_score": 0.60, "event_id": "evt-B"},
        ],
        ensure_ascii=False, indent=2,
    )

    def _save_article(spec) -> Article:
        return Article(
            title=spec.get("title", "기사"), url=spec["url"], publisher=spec.get("publisher"),
            summary=spec.get("summary"),
            sentiment=(Sentiment(spec["sentiment"]) if spec.get("sentiment") else None),
            sentiment_score=spec.get("sentiment_score"),
            event_id=spec.get("event_id"),
            analysis_completed=True,
        )

    def _demo_graph_batch() -> GraphBatch:
        """같은 배치의 GraphBatch 델타(원자성 짝). NewsRef 는 url 키 — backend 가 저장 시 news_id 로 해소."""
        return GraphBatch(
            nodes=[
                GraphNode(label=NodeLabel.EVENT, key="evt-A",
                          properties={"canonical_title": "HBM 공급 계약", "importance": 2.31}),
                GraphNode(label=NodeLabel.COMPANY, key="삼성전자"),
                GraphNode(label=NodeLabel.NEWS_REF, key="https://ex.com/1"),
            ],
            relationships=[
                GraphRelationship(type=RelType.PARTICIPATES_IN, start_label=NodeLabel.COMPANY,
                                  start_key="삼성전자", end_label=NodeLabel.EVENT, end_key="evt-A"),
                GraphRelationship(type=RelType.HAS_NEWS, start_label=NodeLabel.EVENT,
                                  start_key="evt-A", end_label=NodeLabel.NEWS_REF, end_key="https://ex.com/1"),
            ],
        )

    # -----------------------------------------------------------------------
    # ① save_batch — 쓰기: 실패는 degrade 금지(ok=False 정확보고)
    # -----------------------------------------------------------------------
    with t_save:
        st.subheader("save_client.save_batch(articles, graph_batch) → SaveResponse")
        st.caption(
            "★ 원자성 계약(§3.3): articles(PostgreSQL) + graph_batch(Neo4j)는 같은 배치의 짝을 **한 요청**으로. "
            "news_id 는 에이전트가 만들지 않는다(backend 가 url 로 해소). 저장 실패는 degrade 금지 → ok=False."
        )
        scen = st.radio("backend 상태", list(_SCEN.keys()), horizontal=True, key="a08_save_scen")
        arts_raw = st.text_area("저장할 기사들(JSON)", _DEMO_SAVE_ARTS, height=240, key="a08_save_arts")
        if st.button("save_batch 실행", key="a08_save_btn"):
            try:
                specs = json.loads(arts_raw)
            except json.JSONDecodeError as exc:
                st.error(f"JSON 오류: {exc}")
            else:
                articles = [_save_article(s) for s in specs]
                graph = _demo_graph_batch()
                rec: list = []
                err = _fail_exc() if _SCEN[scen] else None
                ok_resp = {"ok": True, "saved": len(articles), "message": "upsert(url unique) + MERGE"}
                with _mock_backend(result=ok_resp, error=err, recorder=rec):
                    resp = save_client.save_batch(articles, graph)

                if resp.ok:
                    st.success(f"SaveResponse(ok=True, saved={resp.saved}) · {resp.message}")
                else:
                    st.error(f"SaveResponse(ok=False) — 저장 실패를 성공으로 위장하지 않음(§2-5): {resp.message}")

                if rec:
                    call = rec[0]
                    st.caption(f"→ {call['method']} {call['path']} (backend 호출 1회)")
                    payload = call["json"]
                    c1, c2 = st.columns(2)
                    c1.metric("articles", len(payload["articles"]))
                    c2.metric("graph nodes / rels",
                              f"{len(payload['graph_batch']['nodes'])} / {len(payload['graph_batch']['relationships'])}")
                    made_ids = [a.get("id") for a in payload["articles"]]
                    if all(i is None for i in made_ids):
                        st.caption("✅ payload 의 모든 article.id = None — 에이전트가 news_id 를 만들지 않음(backend 가 url→news_id 해소).")
                    else:
                        st.error(f"⚠️ payload 에 news_id 가 실림(환각 금지 위반): {made_ids}")
                    with st.expander("실제 전송 payload(JSON)"):
                        st.code(json.dumps(payload, ensure_ascii=False, indent=2), language="json")
                else:
                    st.caption("backend 호출 없음(전송 payload 없음).")

        st.divider()
        st.caption("대상 0건(기사·그래프 모두 비었음)이면 backend 를 부르지 않고 ok=True·saved=0 으로 통과합니다.")
        if st.button("0건 save_batch (backend 호출 없음 확인)", key="a08_save_zero"):
            rec = []
            with _mock_backend(result={"ok": True, "saved": 99}, recorder=rec):
                resp = save_client.save_batch([], GraphBatch())
            st.write(f"SaveResponse(ok={resp.ok}, saved={resp.saved}) · backend 호출 {len(rec)}회")
            st.caption("✅ saved=0 이고 호출 0회면 정상(없으면 없는 대로 — 환각 금지).")

    # -----------------------------------------------------------------------
    # ② request_cleanup — 7일 롤링 삭제 트리거(판정은 backend)
    # -----------------------------------------------------------------------
    with t_cleanup:
        st.subheader("save_client.request_cleanup() → CleanupResponse")
        st.caption(
            "7일 롤링 삭제를 **트리거만** 한다. 168h 판정·CASCADE(고아 Keyword/Person/Country 삭제·"
            "Company 유지)·importance 재계산은 backend(SCHEMA_SPEC §5). 요청 본문은 비어 있음(판정 안 함)."
        )
        scen = st.radio("backend 상태", list(_SCEN.keys()), horizontal=True, key="a08_clean_scen")
        if st.button("request_cleanup 실행", key="a08_clean_btn"):
            rec: list = []
            err = _fail_exc() if _SCEN[scen] else None
            ok_resp = {"ok": True, "deleted_articles": 12, "deleted_events": 3, "message": "168h CASCADE"}
            with _mock_backend(result=ok_resp, error=err, recorder=rec):
                resp = save_client.request_cleanup()
            if resp.ok:
                c1, c2 = st.columns(2)
                c1.metric("deleted_articles", resp.deleted_articles)
                c2.metric("deleted_events", resp.deleted_events)
                st.success(f"CleanupResponse(ok=True) · {resp.message}")
            else:
                st.error(f"CleanupResponse(ok=False) — 삭제 누락도 정확 보고(degrade 금지): {resp.message}")
            if rec:
                st.caption(f"→ {rec[0]['method']} {rec[0]['path']} · 요청 본문 = {rec[0]['json']} (에이전트는 삭제 판정을 하지 않음, 트리거만)")

    # -----------------------------------------------------------------------
    # ③ providers — 조회: 실패는 degrade([]/None), 예외로 배치 안 죽임
    # -----------------------------------------------------------------------
    with t_prov:
        st.subheader("배치 조회 Provider — 실패 시 degrade([] / None)")
        st.caption(
            "TASK 05/06 인터페이스의 backend 구현. 매핑만 하고 계산 안 함(centroid·가중치는 backend). "
            "HTTP 실패에도 예외로 배치를 죽이지 않고 degrade — 병합은 모두 신규, importance 는 배치만으로 근사(§4.2)."
        )
        sub_recent, sub_stats = st.tabs(["BackendRecentEventProvider (TASK 05)", "BackendEventArticleStatsProvider (TASK 06)"])

        with sub_recent:
            st.markdown("**get_recent_events(companies, within_days) → CandidateEvent[]**")
            scen = st.radio("backend 상태", list(_SCEN.keys()), horizontal=True, key="a08_recent_scen")
            companies = st.text_input("companies(쉼표)", "삼성전자, SK하이닉스", key="a08_recent_co")
            within = st.number_input("within_days", 1, 30, config.MERGE_CANDIDATE_WINDOW_DAYS, key="a08_recent_win")
            default_recent = json.dumps(
                [{"canonical_id": "evt-A", "companies": ["삼성전자"],
                  "embedding": [0.11, 0.22, 0.33], "event_time": "2026-07-06T09:00:00+09:00"}],
                ensure_ascii=False, indent=2,
            )
            resp_raw = st.text_area("backend 응답(CandidateEvent[] JSON)", default_recent, height=150, key="a08_recent_resp")
            if st.button("get_recent_events 실행", key="a08_recent_btn"):
                try:
                    body = json.loads(resp_raw)
                except json.JSONDecodeError as exc:
                    st.error(f"JSON 오류: {exc}")
                else:
                    rec: list = []
                    err = _fail_exc() if _SCEN[scen] else None
                    with _mock_backend(result=body, error=err, recorder=rec):
                        prov = backend_providers.BackendRecentEventProvider()
                        events = prov.get_recent_events(
                            [c.strip() for c in companies.split(",") if c.strip()], int(within))
                    if _SCEN[scen]:
                        st.warning(f"HTTP 실패 → **[] degrade**(예외 전파 안 함). 후보 {len(events)}개 → 모든 기사 신규.")
                    else:
                        st.success(f"CandidateEvent {len(events)}개 매핑")
                        st.dataframe(
                            [{"canonical_id": e.canonical_id, "companies": e.companies,
                              "embedding(centroid)": str(e.embedding), "event_time": str(e.event_time)}
                             for e in events],
                            use_container_width=True,
                        )
                        st.caption("✅ centroid(embedding)는 backend 값을 그대로 읽음 — 여기서 계산하지 않음.")
                    if rec:
                        st.caption(f"→ {rec[0]['method']} {rec[0]['path']} · params={rec[0]['params']}")

        with sub_stats:
            st.markdown("**get_event_article_stats(event_id) → EventArticleStats | None**")
            scen = st.radio("backend 상태", ["정상 응답", "미존재 (None)", "실패 (BackendError)"],
                            horizontal=True, key="a08_stats_scen")
            event_id = st.text_input("event_id", "evt-A", key="a08_stats_eid")
            default_stats = json.dumps(
                {"article_count": 4, "publishers": ["매일경제", "한국경제"],
                 "sentiment_magnitude_sum": 1.5, "sentiment_count": 3},
                ensure_ascii=False, indent=2,
            )
            stats_raw = st.text_area("backend 응답(EventArticleStats JSON)", default_stats, height=150, key="a08_stats_resp")
            if st.button("get_event_article_stats 실행", key="a08_stats_btn"):
                if scen == "실패 (BackendError)":
                    result, err = None, _fail_exc()
                elif scen == "미존재 (None)":
                    result, err = None, None
                else:
                    try:
                        result, err = json.loads(stats_raw), None
                    except json.JSONDecodeError as exc:
                        st.error(f"JSON 오류: {exc}")
                        result, err = None, None
                with _mock_backend(result=result, error=err):
                    prov = backend_providers.BackendEventArticleStatsProvider()
                    stats = prov.get_event_article_stats(event_id)
                if stats is None:
                    st.warning("None 반환 — 미존재/실패 모두 None 으로 degrade(편입은 배치만으로 근사, 신규는 영향 없음).")
                else:
                    st.success("EventArticleStats 매핑(원자료: publishers distinct·감성 합/개수)")
                    st.code(_model_json(stats), language="json")

    # -----------------------------------------------------------------------
    # ④ query_client — 질의(리포트) 조회: 실패는 전파(리포트가 데이터 제한)
    # -----------------------------------------------------------------------
    with t_query:
        st.subheader("query_client — 종목/공유이벤트/이벤트별 기사(importance순)")
        st.caption(
            "감성 게이지는 backend 실시간 집계값을 **받기만** 한다(ai 재집계 안 함, §5). 조회 실패는 degrade "
            "하지 않고 BackendError 를 전파해 리포트가 '데이터 제한'으로 처리한다(§4.2)."
        )
        q_subj, q_shared, q_arts = st.tabs(["get_events_by_subject", "get_shared_events", "get_articles_by_event"])

        _DEMO_SUBJECT_RESP = json.dumps(
            {
                "subject": "삼성전자", "subject_found": True,
                "events": [
                    {"event": {"canonical_id": "evt-A", "canonical_title": "HBM 공급 계약",
                               "importance": 2.31, "companies": ["삼성전자"]},
                     "article_count": 12,
                     "articles": [{"news_id": 101, "summary": "삼성전자 HBM 공급 계약 체결", "url": "https://ex.com/1"}],
                     "gauge": {"positive": 8, "neutral": 3, "negative": 1}},
                    {"event": {"canonical_id": "evt-B", "canonical_title": "실적 발표",
                               "importance": 1.05, "companies": ["삼성전자"]},
                     "article_count": 4,
                     "articles": [{"news_id": 205, "summary": "삼성전자 3분기 실적 발표", "url": "https://ex.com/9"}],
                     "gauge": {"positive": 1, "neutral": 2, "negative": 1}},
                ],
                "overall_gauge": {"positive": 9, "neutral": 5, "negative": 2},
            },
            ensure_ascii=False, indent=2,
        )

        def _render_subject(resp):
            st.write(f"subject_found = **{resp.subject_found}** (없는 종목 vs 뉴스 0건 구분)")
            g = resp.overall_gauge
            c1, c2, c3 = st.columns(3)
            c1.metric("🟢 긍정", g.positive); c2.metric("⚪ 중립", g.neutral); c3.metric("🔴 부정", g.negative)
            st.caption("overall_gauge 는 backend 집계값(sentiment=None 제외) — ai 는 재집계하지 않음.")
            st.dataframe(
                [
                    {"importance": ev.event.importance, "canonical_title": ev.event.canonical_title,
                     "article_count(총)": ev.article_count, "대표 ArticleRef(news_id)": [a.news_id for a in ev.articles],
                     "gauge(긍/중/부)": f"{ev.gauge.positive}/{ev.gauge.neutral}/{ev.gauge.negative}"}
                    for ev in resp.events
                ],
                use_container_width=True,
            )
            imps = [ev.event.importance for ev in resp.events]
            st.caption(f"✅ importance 내림차순 정렬 여부: {imps == sorted(imps, reverse=True)} · "
                       "대표 ArticleRef 에 news_id 가 있어 ④ 답변생성이 근거 사슬을 만든다.")

        with q_subj:
            st.markdown("**get_events_by_subject(companies, within_days) → SubjectQueryResponse**")
            scen = st.radio("backend 상태", list(_SCEN.keys()), horizontal=True, key="a08_subj_scen")
            companies = st.text_input("companies(쉼표)", "삼성전자", key="a08_subj_co")
            within = st.number_input("within_days", 1, 30, 7, key="a08_subj_win")
            resp_raw = st.text_area("backend 응답(SubjectQueryResponse JSON)", _DEMO_SUBJECT_RESP, height=280, key="a08_subj_resp")
            if st.button("get_events_by_subject 실행", key="a08_subj_btn"):
                rec: list = []
                if _SCEN[scen]:
                    with _mock_backend(error=_fail_exc(), recorder=rec):
                        try:
                            query_client.get_events_by_subject(
                                [c.strip() for c in companies.split(",") if c.strip()], int(within))
                            st.error("예외가 전파되지 않음 — 계약 위반")
                        except backend_client.BackendError as exc:
                            st.warning(f"BackendError 전파 ✅ — 리포트가 '데이터 제한'으로 처리(degrade 안 함): {exc}")
                else:
                    try:
                        body = json.loads(resp_raw)
                    except json.JSONDecodeError as exc:
                        st.error(f"JSON 오류: {exc}")
                    else:
                        with _mock_backend(result=body, recorder=rec):
                            resp = query_client.get_events_by_subject(
                                [c.strip() for c in companies.split(",") if c.strip()], int(within))
                        _render_subject(resp)
                if rec:
                    st.caption(f"→ {rec[0]['method']} {rec[0]['path']} · params={rec[0]['params']}")

        with q_shared:
            st.markdown("**get_shared_events(company_a, company_b, within_days) → SubjectQueryResponse (multi-hop)**")
            st.caption("두 회사가 함께 PARTICIPATES_IN 한 공유 이벤트(관계 질문 핵심). importance순.")
            ca = st.text_input("company_a", "삼성전자", key="a08_shared_a")
            cb = st.text_input("company_b", "SK하이닉스", key="a08_shared_b")
            within = st.number_input("within_days", 1, 30, 7, key="a08_shared_win")
            if st.button("get_shared_events 실행", key="a08_shared_btn"):
                rec: list = []
                with _mock_backend(result=json.loads(_DEMO_SUBJECT_RESP), recorder=rec):
                    resp = query_client.get_shared_events(ca, cb, int(within))
                _render_subject(resp)
                st.caption(f"→ multi-hop 파라미터 전송: params={rec[0]['params']}")

        with q_arts:
            st.markdown("**get_articles_by_event(event_id, limit) → ArticleRef[] (on-demand 근거)**")
            st.caption(
                "대표 소수(EventWithArticles.articles)를 넘는 깊은 근거가 필요할 때만 on-demand. limit 으로 "
                "Top-N 제어(DTO 재배포 없이). bare news_id 가 아니라 ArticleRef 를 돌려줘 왕복 없음."
            )
            event_id = st.text_input("event_id(canonical_id)", "evt-A", key="a08_arts_eid")
            limit = st.number_input("limit", 1, 50, 5, key="a08_arts_limit")
            default_refs = json.dumps(
                [{"news_id": 101, "summary": "삼성전자 HBM 공급 계약 체결", "url": "https://ex.com/1"},
                 {"news_id": 102, "summary": "엔비디아향 HBM 물량 확대", "url": "https://ex.com/2"}],
                ensure_ascii=False, indent=2,
            )
            refs_raw = st.text_area("backend 응답(ArticleRef[] JSON)", default_refs, height=160, key="a08_arts_resp")
            if st.button("get_articles_by_event 실행", key="a08_arts_btn"):
                try:
                    body = json.loads(refs_raw)
                except json.JSONDecodeError as exc:
                    st.error(f"JSON 오류: {exc}")
                else:
                    rec: list = []
                    with _mock_backend(result=body, recorder=rec):
                        refs = query_client.get_articles_by_event(event_id, int(limit))
                    st.success(f"ArticleRef {len(refs)}건")
                    st.dataframe(
                        [{"news_id": r.news_id, "summary": r.summary, "url": r.url} for r in refs],
                        use_container_width=True,
                    )
                    st.caption(f"→ {rec[0]['method']} {rec[0]['path']} · params={rec[0]['params']} "
                               f"(event_id 가 path 에 치환·limit 이 params 로 전송)")

    # -----------------------------------------------------------------------
    # ⑤ save_node — 얇은 노드: save_client 만 호출, 실패해도 루프 안 죽음
    # -----------------------------------------------------------------------
    with t_node:
        st.subheader("nodes/save.save_node(state) — 얇은 저장 노드")
        st.caption(
            "state['articles'] + state['graph_batch'] 를 save_client 로만 넘긴다(backend 직접 호출 없음, 절대규칙 1). "
            "결과는 state['save_result']. 실패해도 예외로 스케줄러 루프를 죽이지 않고 ok=False 로 통과(TASK 10 재시도)."
        )
        scen = st.radio("backend 상태", list(_SCEN.keys()), horizontal=True, key="a08_node_scen")
        arts_raw = st.text_area("state['articles'](JSON)", _DEMO_SAVE_ARTS, height=220, key="a08_node_arts")
        include_graph = st.checkbox("state['graph_batch'] 포함(같은 배치 델타)", value=True, key="a08_node_graph")
        if st.button("save_node 실행", key="a08_node_btn"):
            try:
                specs = json.loads(arts_raw)
            except json.JSONDecodeError as exc:
                st.error(f"JSON 오류: {exc}")
            else:
                articles = [_save_article(s) for s in specs]
                state = {"articles": articles, "graph_batch": _demo_graph_batch() if include_graph else GraphBatch()}
                rec: list = []
                err = _fail_exc() if _SCEN[scen] else None
                ok_resp = {"ok": True, "saved": len(articles), "message": "ok"}
                with _mock_backend(result=ok_resp, error=err, recorder=rec):
                    out = save_node(state)
                res = out.get("save_result")
                if res is None:
                    st.info("save_result 없음 — 대상 0건 통과(backend 호출 없음).")
                elif res.ok:
                    st.success(f"state['save_result'] = SaveResponse(ok=True, saved={res.saved})")
                else:
                    st.error(f"state['save_result'] = SaveResponse(ok=False) — 실패를 명확히 남김(루프 안 죽음): {res.message}")
                st.caption(f"backend 호출 {len(rec)}회 · 노드는 save_client 만 통해 접근(직접 HTTP 없음).")

        st.divider()
        if st.button("대상 0건 save_node (예외 없이 통과)", key="a08_node_zero"):
            rec: list = []
            with _mock_backend(result={"ok": True, "saved": 0}, recorder=rec):
                out = save_node({"articles": [], "graph_batch": GraphBatch()})
            st.write(f"save_result in state? {('save_result' in out)} · backend 호출 {len(rec)}회")
            st.caption("✅ 0건이면 save_result 미설정·호출 0회로 조용히 통과(환각 금지).")


# ===========================================================================
# TASK 09 — 질의·리포트 흐름: ①질문이해 → ②그래프탐색 → ④답변생성 → HTML 리포트
#   LLM(질문이해·답변생성)은 llm._chat_completion 한 겹만 mock 으로 교체(테스트와 동일 방식).
#   backend(그래프·근거 조회)는 BackendClient._request 한 겹만 mock — SQL·Cypher·네트워크 없음(절대규칙 1).
#   query_understanding/graph_query/answer_generator/report_renderer/노드는 '진짜 코드 경로' 를 그대로 탄다.
# ===========================================================================
elif TASK.startswith("TASK 09"):
    st.header("TASK 09 — 질의·리포트(질문 → HTML 리포트 하나)")
    st.caption(
        "저장된 데이터를 읽어 질문에 답하고 HTML 리포트 하나를 그립니다(수집·분석 안 함). ④ 답변은 별도 "
        "채널이 아니라 리포트 안 '뉴스 흐름 요약' 섹션 + 근거 이슈 칩으로 내장됩니다(CLAUDE.md §1)."
    )
    st.sidebar.caption(
        f"기본 기간 {config.QUERY_DEFAULT_PERIOD_DAYS}일 · TOP {config.REPORT_TOP_N} · "
        f"이벤트별 대표 {config.REPORT_MAX_ARTICLES_PER_EVENT}건 · 랭킹={config.REPORT_RANKING!r}(잠정 importance)"
    )
    st.sidebar.caption(f"별칭 사전 {len(config.COMPANY_ALIASES)}개(예: {', '.join(list(config.COMPANY_ALIASES)[:4])}…)")

    # -- mock 시임: LLM(질문이해·답변생성) --------------------------------------
    _KNOWN_CANON = ["삼성전자", "SK하이닉스", "엔비디아", "현대자동차",
                    "카카오게임즈", "네이버", "카카오", "LG에너지솔루션"]

    def _mock_understanding_payload(question: str) -> dict:
        """가짜 질문이해 LLM: 사전이 못 잡은 canonical 회사만 보완 + 기간·의도 파싱(억지 매핑 없음)."""
        import re
        comps = [c for c in _KNOWN_CANON if c in question]
        low = question.lower()
        if any(k in question for k in ("관계", "함께", "같이")) or "vs" in low:
            intent = "관계"
        elif any(k in question for k in ("왜", "이유", "때문")):
            intent = "이유"
        elif any(k in question for k in ("현황", "요즘", "상황")):
            intent = "현황"
        else:
            intent = "요약"
        period = None
        m = re.search(r"(\d+)\s*일", question)
        if m:
            period = int(m.group(1))
        elif "한 달" in question or "한달" in question:
            period = 30
        elif "주" in question:
            period = 7
        return {"companies": comps, "period_days": period, "intent": intent, "non_company_tokens": []}

    def _mock_answer_payload(user_content: str) -> dict:
        """가짜 답변 LLM: user 메시지의 근거 payload(JSON)만 파싱해 실제 news_id/event_id 로만 인용(환각 0)."""
        arr = []
        try:
            arr = json.loads(user_content[user_content.index("["):])
        except (ValueError, json.JSONDecodeError):
            arr = []
        news_ids, event_ids, titles = [], [], []
        for ev in arr:
            if ev.get("event_id"):
                event_ids.append(ev["event_id"])
            if ev.get("title"):
                titles.append(ev["title"])
            for a in ev.get("articles", []):
                news_ids.append(a["news_id"])
        body = ("최근 뉴스 흐름은 " + ", ".join(titles) + " 을(를) 중심으로 전개되었습니다. "
                "(데모용 생성 텍스트 — 감성은 판정하지 않고 게이지가 표시)")
        return {"text": body, "evidence_news_ids": news_ids, "cited_event_ids": event_ids,
                "data_limited": not news_ids}

    def _fake_chat(messages, tools=None, tool_choice="auto", **kwargs):
        """llm._chat_completion 대역: system 프롬프트로 질문이해/답변생성을 분기(OpenAI 응답 형태)."""
        system = messages[0]["content"] if messages else ""
        user = messages[-1]["content"] if messages else ""
        payload = _mock_understanding_payload(user) if "질의를 구조화" in system else _mock_answer_payload(user)
        return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}

    # -- mock 시임: backend(그래프·근거 조회) ----------------------------------
    @contextlib.contextmanager
    def _mock_backend_q(result=None, error: Exception | None = None, recorder: list | None = None):
        orig = backend_client.BackendClient._request

        def fake(self, method, path, json=None, params=None):
            if recorder is not None:
                recorder.append({"method": method, "path": path, "params": params})
            if error is not None:
                raise error
            return result

        backend_client.BackendClient._request = fake
        try:
            yield
        finally:
            backend_client.BackendClient._request = orig

    llm_mode = st.sidebar.radio("LLM 모드", ["Mock (가짜 Qwen3)", "실제 Qwen3 서버"], key="a09_mode")
    if llm_mode.startswith("Mock"):
        llm._chat_completion = _fake_chat   # 질문이해·답변생성 둘 다 llm.complete→_chat_completion 를 지남
        st.sidebar.success("Mock: 실제 모델을 부르지 않습니다(backend 도 mock).")
    else:
        llm._chat_completion = getattr(llm, "_orig_chat_completion")
        st.sidebar.info("실제 모드: QWEN_API_KEY 의 Qwen3 서버 호출(backend 는 여전히 mock).")

    # backend 조회 응답(SubjectQueryResponse) 기본값 — 이벤트별 대표 ArticleRef(news_id) 포함.
    _DEMO_QUERY_RESP = json.dumps(
        {
            "subject": "삼성전자", "subject_found": True,
            "events": [
                {"event": {"canonical_id": "evt-A", "canonical_title": "4분기 실적 발표",
                           "importance": 9.2, "companies": ["삼성전자"]},
                 "article_count": 28,
                 "articles": [{"news_id": 101, "summary": "영업이익 9.8조로 시장 기대 상회", "url": "https://ex.com/101"},
                              {"news_id": 102, "summary": "실적 발표 후 목표주가 상향", "url": "https://ex.com/102"}],
                 "gauge": {"positive": 22, "neutral": 2, "negative": 4}},
                {"event": {"canonical_id": "evt-B", "canonical_title": "HBM 공급 계약",
                           "importance": 6.9, "companies": ["삼성전자", "SK하이닉스"]},
                 "article_count": 16,
                 "articles": [{"news_id": 103, "summary": "엔비디아 HBM3E 12단 품질승인 통과", "url": "https://ex.com/103"}],
                 "gauge": {"positive": 13, "neutral": 2, "negative": 1}},
                {"event": {"canonical_id": "evt-C", "canonical_title": "메모리 가격 동향",
                           "importance": 4.1, "companies": ["삼성전자"]},
                 "article_count": 9,
                 "articles": [{"news_id": 104, "summary": "D램 현물가 3주째 약세", "url": "https://ex.com/104"}],
                 "gauge": {"positive": 3, "neutral": 4, "negative": 14}},
            ],
            "overall_gauge": {"positive": 41, "neutral": 31, "negative": 28},
        },
        ensure_ascii=False, indent=2,
    )

    def _resp_from_json(raw: str) -> SubjectQueryResponse:
        return SubjectQueryResponse.model_validate(json.loads(raw))

    t_understand, t_graph, t_answer, t_flow = st.tabs(
        ["① 질문이해", "② 그래프탐색(single/multi-hop)", "④ 답변생성(근거·환각필터)", "⑤ 전체 흐름 → HTML 리포트"]
    )

    # -----------------------------------------------------------------------
    # ① understand_query — Dictionary First → LLM 보완 → 저신뢰 제거
    # -----------------------------------------------------------------------
    with t_understand:
        st.subheader("understand_query — 사전 매칭 → Qwen3 보완 → Pydantic 강제")
        st.caption(
            "회사명은 LLM 단독이 아니라 config.COMPANY_ALIASES 최장일치(사전) 우선, 잔여만 LLM 보완(query_spec §①-1). "
            "종목 선택은 from_subject 프리셋(LLM 없이 intent=요약)."
        )
        question = st.text_input("질문 문장", "삼전닉스 최근 3일 관계 어때", key="a09_u_q")
        if st.button("질문이해 실행", key="a09_u_btn"):
            dict_comps, residual = query_understanding._match_aliases(question)
            st.write(f"**① 사전 매칭**: {dict_comps or '(없음)'} · 잔여 → LLM: `{residual.strip() or '(없음)'}`")
            try:
                u = query_understanding.understand_query(question)
            except Exception as exc:
                st.error(f"실패: {exc}")
            else:
                st.success(f"companies={u.companies} · period_days={u.period_days} · intent={u.intent.value}")
                st.code(_model_json(u), language="json")
                if u.dropped_tokens:
                    st.caption(f"버린 토큰(dropped_tokens, 사전 보강 대상): {u.dropped_tokens}")

        st.divider()
        st.markdown("**from_subject — 종목 선택(A) → 프리셋(B)**")
        subj = st.text_input("종목명", "삼성전자", key="a09_u_subj")
        if st.button("프리셋 생성", key="a09_u_preset"):
            u = query_understanding.from_subject(subj)
            st.success(f"is_preset={u.is_preset} · intent={u.intent.value} · original_question={u.original_question!r}")
            st.code(_model_json(u), language="json")

    # -----------------------------------------------------------------------
    # ② fetch_events — 회사 수·intent 로 single/multi-hop 분기(순회는 backend)
    # -----------------------------------------------------------------------
    with t_graph:
        st.subheader("graph_query.fetch_events — single(1개) / multi-hop(2개·관계)")
        st.caption("실제 Neo4j 순회는 backend(mock). 여기선 어떤 조회를 부를지 '설계'만 — Cypher·DB 드라이버 없음(절대규칙 1).")
        colL, colR = st.columns([2, 3])
        with colL:
            comps_raw = st.text_input("companies(쉼표 · 비우면 0개)", "삼성전자, SK하이닉스", key="a09_g_co")
            intent_label = st.selectbox("intent", [i.value for i in QueryIntent], index=0, key="a09_g_intent")
            days = st.number_input("period_days", 1, 60, 7, key="a09_g_days")
            scen = st.radio("backend 상태", ["정상 응답", "실패 (BackendError)"], horizontal=True, key="a09_g_scen")
        with colR:
            resp_raw = st.text_area("backend 응답(SubjectQueryResponse JSON)", _DEMO_QUERY_RESP, height=240, key="a09_g_resp")
        if st.button("fetch_events 실행", key="a09_g_btn"):
            comps = [c.strip() for c in comps_raw.split(",") if c.strip()]
            u = QueryUnderstanding(companies=comps, period_days=int(days),
                                   intent=QueryIntent(intent_label), original_question="(데모)")
            rec: list = []
            err = backend_client.BackendError("mock: backend 조회 실패") if scen.startswith("실패") else None
            try:
                body = None if err else json.loads(resp_raw)
            except json.JSONDecodeError as exc:
                st.error(f"JSON 오류: {exc}")
            else:
                with _mock_backend_q(result=body, error=err, recorder=rec):
                    resp = graph_query.fetch_events(u)
                hop = "0개(backend 미호출)" if not comps else ("multi-hop(shared)" if len(comps) >= 2 else "single-hop(subject)")
                st.write(f"분기: **{hop}** · subject_found=**{resp.subject_found}** · 이벤트 {len(resp.events)}개")
                if rec:
                    st.caption(f"→ {rec[0]['method']} {rec[0]['path']} · params={rec[0]['params']}")
                elif comps:
                    st.warning("BackendError → 빈/subject_found=False 로 degrade(리포트가 '데이터 제한', 예외 전파 안 함).")
                else:
                    st.caption("회사 0개 → backend 를 부르지 않고 데이터 제한 처리(호출 0회).")
                if resp.events:
                    st.dataframe(
                        [{"importance": e.event.importance, "이벤트": e.event.canonical_title,
                          "총 기사": e.article_count, "대표 news_id": [a.news_id for a in e.articles],
                          "gauge(긍/중/부)": f"{e.gauge.positive}/{e.gauge.neutral}/{e.gauge.negative}"}
                         for e in resp.events],
                        use_container_width=True,
                    )

    # -----------------------------------------------------------------------
    # ④ generate_answer — 근거 news_id 부착 + 근거 밖 값 필터(환각 방지)
    # -----------------------------------------------------------------------
    with t_answer:
        st.subheader("answer_generator.generate_answer — 뉴스 흐름 요약 본문 + 근거 news_id")
        st.caption(
            "LLM 은 텍스트만(감성 판정 없음, 절대규칙 4). 모든 주장에 근거 news_id 부착, 근거 밖 id 는 걸러냄(환각 방지). "
            "데이터 없으면 data_limited=True('데이터 제한')."
        )
        comps_raw = st.text_input("companies(쉼표)", "삼성전자", key="a09_a_co")
        intent_label = st.selectbox("intent", [i.value for i in QueryIntent], index=2, key="a09_a_intent")
        resp_raw = st.text_area("backend 응답(SubjectQueryResponse JSON)", _DEMO_QUERY_RESP, height=220, key="a09_a_resp")
        if st.button("generate_answer 실행", key="a09_a_btn"):
            try:
                resp = _resp_from_json(resp_raw)
            except (json.JSONDecodeError, ValidationError) as exc:
                st.error(f"입력 오류: {exc}")
            else:
                u = QueryUnderstanding(companies=[c.strip() for c in comps_raw.split(",") if c.strip()],
                                       intent=QueryIntent(intent_label), original_question="(데모)")
                valid = {a.news_id for ev in resp.events for a in ev.articles}
                with _mock_backend_q(result=[]):   # on-demand 근거 조회가 필요 없을 땐 안 불림
                    ans = answer_generator.generate_answer(u, resp)
                st.success(f"data_limited={ans.data_limited}")
                st.write(f"**뉴스 흐름 요약 본문**: {ans.text}")
                st.write(f"근거 news_id={ans.evidence_news_ids} · cited_event_ids={ans.cited_event_ids}")
                st.caption(f"✅ 근거 news_id 가 실제 조회된 집합 {sorted(valid)} 의 부분집합인지: "
                           f"{set(ans.evidence_news_ids) <= valid} (환각 필터).")

    # -----------------------------------------------------------------------
    # ⑤ query_node → report_node — 전체 흐름 → HTML 리포트 하나
    # -----------------------------------------------------------------------
    with t_flow:
        st.subheader("query_node → report_node — 질문 하나 → HTML 리포트 하나")
        st.caption(
            "①질문이해 → ②그래프탐색 → ④답변생성 → HTML 렌더 전체를 노드로 실행. ④ 답변은 '뉴스 흐름 요약' 섹션에 "
            "내장(별도 텍스트 없음). 한 단계 실패해도 예외 없이 '데이터 제한' 리포트로 통과(절대규칙 5)."
        )
        mode_in = st.radio("입력 방식", ["자유 질문", "종목 선택(프리셋)"], horizontal=True, key="a09_f_mode")
        if mode_in == "자유 질문":
            q_text = st.text_input("질문 문장", "삼전 최근 뉴스 요약해줘", key="a09_f_q")
            state_in = {"question": q_text}
        else:
            subj = st.text_input("종목명", "삼성전자", key="a09_f_subj")
            state_in = {"subject": subj}
        scen = st.radio("backend 상태", ["정상 응답", "실패 (BackendError)"], horizontal=True, key="a09_f_scen")
        resp_raw = st.text_area("backend 응답(SubjectQueryResponse JSON)", _DEMO_QUERY_RESP, height=220, key="a09_f_resp")
        if st.button("전체 흐름 실행", key="a09_f_btn"):
            err = backend_client.BackendError("mock: backend 조회 실패") if scen.startswith("실패") else None
            try:
                body = None if err else json.loads(resp_raw)
            except json.JSONDecodeError as exc:
                st.error(f"JSON 오류: {exc}")
            else:
                with _mock_backend_q(result=body, error=err):
                    state = query_node(dict(state_in))   # ①②④
                    state = report_node(state)           # HTML 렌더
                u, ans = state["understanding"], state["answer"]
                c1, c2, c3 = st.columns(3)
                c1.metric("companies", ", ".join(u.companies) or "(없음)")
                c2.metric("intent", u.intent.value)
                c3.metric("data_limited", str(ans.data_limited))
                st.write(f"**④ 답변(요약 섹션 본문)**: {ans.text}")
                st.write(f"근거 news_id={ans.evidence_news_ids} · 근거 칩(event)={ans.cited_event_ids}")
                html = state["html"]
                st.divider()
                st.markdown("**렌더된 HTML 리포트 (출력은 이 하나뿐)**")
                components.html(html, height=900, scrolling=True)
                st.download_button("HTML 다운로드", data=html, file_name="verith_report.html",
                                   mime="text/html", key="a09_f_dl")
                with st.expander("HTML 소스 보기"):
                    st.code(html, language="html")
