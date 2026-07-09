# demo_pipeline_app.py — 뉴스 에이전트 end-to-end 데모 (수집→추출→감성→임베딩→그래프→저장→검색→리포트)
"""실제 파이프라인을 눈으로 보는 Streamlit 데모.

실행:
    # backend(:8001 등)와 postgres/neo4j 가 떠 있어야 한다.
    BACKEND_BASE_URL=http://127.0.0.1:8001 \\
    uv run --project ai --with streamlit streamlit run ai/src/agents/news/demo_pipeline_app.py

이 앱은 배선(graph.py)을 우회해 노드를 **직접 순차 실행**하며 각 단계 산출을 화면에 보여준다
(사용자가 "실제로 돌아가는 걸 보고 싶다"는 요구에 맞춰 stage-by-stage 로 노출). 검색→리포트는
질의 서비스(understand → fetch → answer → report)를 직접 조합한다(종목 프리셋 경로 포함).
"""
from __future__ import annotations

import os
import sys
import time
from collections import Counter

# --- import 루트: ai/ (= src 패키지 위치)를 넣어 `src.agents.news.*` 패키지 경로로 import ---
# (news 4단계 상위 = news→agents→src→ai). streamlit 단독 실행에서도 패키지가 풀리게 shim.
_AI_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if _AI_ROOT not in sys.path:
    sys.path.insert(0, _AI_ROOT)

os.environ.setdefault("BACKEND_BASE_URL", "http://127.0.0.1:8001")

import streamlit as st  # noqa: E402

# 노드(배치) — graph.py 와 동일한 함수들을 직접 부른다
import src.agents.news.nodes.crawl as crawl_mod  # noqa: E402
from src.agents.news.nodes.crawl import crawl_node  # noqa: E402
from src.agents.news.nodes.embedding import embedding_node  # noqa: E402
from src.agents.news.nodes.extract import extract_node  # noqa: E402
from src.agents.news.nodes.graph_builder import graph_node  # noqa: E402
from src.agents.news.nodes.importance import importance_node  # noqa: E402
from src.agents.news.nodes.merge_event import merge_event_node  # noqa: E402
from src.agents.news.nodes.save import save_node  # noqa: E402
from src.agents.news.nodes.sentiment import sentiment_node  # noqa: E402

# 질의 서비스(리포트) — 직접 조합(배선 우회로 subject 프리셋도 사용)
import src.agents.news.services.answer_generator as ag  # noqa: E402
import src.agents.news.services.graph_query as gq  # noqa: E402
import src.agents.news.services.query_understanding as qu  # noqa: E402
import src.agents.news.services.report_renderer as rr  # noqa: E402
import src.agents.news.services.rss as rss_mod  # noqa: E402
from src.agents.news.services.backend.providers import (  # noqa: E402
    BackendEventArticleStatsProvider,
    BackendRecentEventProvider,
)

# 전체 RSS 후보(config 기본) / 금융 위주 서브셋
ALL_FEEDS = list(rss_mod.RSS_CANDIDATES)
FIN_FEEDS = [
    ("매일경제", "https://www.mk.co.kr/rss/40300001/"),
    ("한국경제", "https://www.hankyung.com/feed/all-news"),
    ("아시아경제", "https://view.asiae.co.kr/rss/all.htm"),
    ("파이낸셜뉴스", "https://www.fnnews.com/rss/r20/fn_realnews_all.xml"),
    ("디지털타임스", "https://www.dt.co.kr/rss/google/latest"),
]

st.set_page_config(page_title="뉴스 에이전트 데모", page_icon="📰", layout="wide")
st.title("📰 뉴스 에이전트 — 실시간 파이프라인 데모")
st.caption(
    "실제 언론사 RSS 수집 → Qwen3 추출 → KR-FinBert 감성 → arctic-embed 임베딩 → "
    "이벤트 병합/중요도 → Neo4j 지식그래프 저장 → 검색 시 리포트 생성"
)

if "batch" not in st.session_state:
    st.session_state.batch = None  # 마지막 배치 결과(state·요약)


# ---------------------------------------------------------------------------
# 사이드바 — 실행 설정
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 설정")
    backend_url = st.text_input("backend URL", os.environ["BACKEND_BASE_URL"])
    os.environ["BACKEND_BASE_URL"] = backend_url
    feed_choice = st.radio("수집 대상 피드", ["금융 위주(추천)", "전체"], index=0)
    cap = st.slider("분석할 최신 기사 수", 5, 40, 15, step=5,
                    help="Qwen 추출·크롤이 기사마다 돌아 시간이 늘어난다(대략 기사당 3~5초).")
    run_batch_clicked = st.button("▶ 뉴스 수집·분석 실행", type="primary", use_container_width=True)
    st.divider()
    st.markdown(
        "**주의**: 첫 실행은 FinBert·임베딩 모델 로드로 10~20초 더 걸립니다.\n\n"
        "backend·postgres·neo4j 가 떠 있어야 저장/검색이 됩니다."
    )


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------
def _providers():
    return BackendRecentEventProvider(), BackendEventArticleStatsProvider()


def run_pipeline_staged(cap_n: int, feeds) -> dict:
    """노드를 순차 실행하며 각 단계 산출을 화면에 노출. 최종 state 반환."""
    rss_mod.RSS_CANDIDATES = feeds
    crawl_mod.CRAWL_MAX_ARTICLES = cap_n
    recent_provider, stats_provider = _providers()

    state: dict = {}
    with st.status("파이프라인 실행 중…", expanded=True) as status:
        t0 = time.time()

        st.write("**①  뉴스 수집 (RSS)** — 실제 언론사 피드에서 최신 기사 메타 수집")
        state = crawl_node(state)
        arts = state.get("articles") or []
        st.write(f"　→ 분석 대상 **{len(arts)}건** 확정")

        st.write("**②  추출 (Qwen3)** — 기사 본문 온디맨드 크롤 + 요약·회사·이벤트·키워드 추출")
        state = extract_node(state)
        ex = state.get("extracts_by_url") or {}
        st.write(f"　→ 추출 성공 **{len(ex)}건**")

        st.write("**③  감성 분석 (KR-FinBert-SC)** — 긍/중/부 + 확신도")
        state = sentiment_node(state)
        senti = Counter(str(a.sentiment.value) for a in (state.get("articles") or []) if a.sentiment)
        st.write(f"　→ {dict(senti) or '판정 없음'}")

        st.write("**④  임베딩 (arctic-embed-l-v2.0-ko)** — 요약 벡터화(1024차원)")
        state = embedding_node(state)
        emb = sum(1 for a in (state.get("articles") or []) if a.embedding)
        st.write(f"　→ 임베딩 **{emb}건**")

        st.write("**⑤  이벤트 병합** — 유사도·회사·시간 가중으로 같은 사건 묶기")
        state = merge_event_node(state, provider=recent_provider)
        events = state.get("events_by_id") or {}
        st.write(f"　→ 신규/편입 이벤트 **{len(events)}개**")

        st.write("**⑥  중요도 계산** — 기사량·언론사·감성 강도")
        state = importance_node(state, provider=stats_provider)

        st.write("**⑦  지식그래프 조립 (GraphBatch 델타)**")
        state = graph_node(state)
        gb = state.get("graph_batch")
        if gb:
            lab = Counter(n.label.value for n in gb.nodes)
            st.write(f"　→ 노드 **{len(gb.nodes)}개** {dict(lab)} · 관계 **{len(gb.relationships)}개**")

        st.write("**⑧  저장 (backend → PostgreSQL + Neo4j MERGE)**")
        state = save_node(state)
        save = state.get("save_result")
        ok = getattr(save, "ok", False)
        st.write(f"　→ 저장 {'성공' if ok else '실패'} · saved=**{getattr(save,'saved','?')}**")

        status.update(label=f"완료 ({time.time()-t0:.0f}초)", state="complete")
    return state


def summarize_batch(state: dict) -> dict:
    arts = state.get("articles") or []
    events = state.get("events_by_id") or {}
    gb = state.get("graph_batch")
    save = state.get("save_result")
    companies = sorted({c for e in events.values() for c in (e.companies or [])})
    return {
        "articles": len(arts),
        "analyzed": sum(1 for a in arts if a.analysis_completed),
        "events": len(events),
        "nodes": len(gb.nodes) if gb else 0,
        "rels": len(gb.relationships) if gb else 0,
        "saved": getattr(save, "saved", 0),
        "ok": getattr(save, "ok", False),
        "companies": companies,
        "event_titles": [e.canonical_title for e in list(events.values())[:12]],
    }


def gauge_bar(g: dict) -> str:
    pos, neu, neg = g.get("positive_pct", 0), g.get("neutral_pct", 0), g.get("negative_pct", 0)
    def seg(w, color, txt):
        if w <= 0:
            return ""
        return (f'<div style="width:{w}%;background:{color};color:#fff;text-align:center;'
                f'line-height:24px;font-size:12px;white-space:nowrap;overflow:hidden">{txt}</div>')
    return (
        '<div style="display:flex;height:24px;border-radius:6px;overflow:hidden;'
        'border:1px solid rgba(0,0,0,.15)">'
        + seg(pos, "#2e7d32", f"긍정 {pos}%")
        + seg(neu, "#9e9e9e", f"중립 {neu}%")
        + seg(neg, "#c62828", f"부정 {neg}%")
        + "</div>"
    )


def render_daily_counts(daily: list[dict]) -> None:
    """날짜별 뉴스량(backend 집계값)을 막대그래프로. 리포트가 감성/순위 말고 '시간 흐름'도 보이게 한다."""
    if not daily:
        return
    st.markdown("**🗓️ 날짜별 뉴스량**")
    try:
        import pandas as pd
        df = pd.DataFrame(daily).rename(columns={"count": "뉴스 건수"}).set_index("date")
        st.bar_chart(df["뉴스 건수"], height=220)
    except Exception:  # pandas 미설치 등 → 표로 degrade(데모라 실패해도 멈추지 않게)
        st.table(daily)
    total = sum(int(d.get("count", 0)) for d in daily)
    st.caption(f"총 {total}건 · {len(daily)}일에 분포")


def dominant_label(g: dict) -> str:
    """기사 표본이 적어(1건) 비율 바가 무의미할 때 쓸 대표 감성 문구. 감성 없는 기사면 '감성 미분석'."""
    pairs = [("긍정", g.get("positive", 0)), ("중립", g.get("neutral", 0)), ("부정", g.get("negative", 0))]
    label, cnt = max(pairs, key=lambda x: x[1])
    return label if cnt > 0 else "감성 미분석"


def build_report(subject: str | None = None, question: str | None = None) -> dict:
    """질의 서비스 직접 조합 → report_json. subject(종목 프리셋) 또는 question(자유질문)."""
    if subject:
        u = qu.from_subject(subject)
    else:
        u = qu.understand_query(question or "")
    resp = gq.fetch_events(u)
    ans = ag.generate_answer(u, resp)
    model = rr.build_report_model(u, resp, ans)
    return model.model_dump(mode="json")


def render_report(rj: dict) -> None:
    g = rj.get("overall_gauge") or {}
    st.subheader(f"🔎 {rj.get('subject','')}")
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        st.markdown("**전체 여론 게이지**")
        st.markdown(gauge_bar(g), unsafe_allow_html=True)
    with c2:
        st.metric("종합", g.get("label", "-"))
    with c3:
        st.metric("순점수 / 기사", f"{g.get('score',0):+.2f} / {g.get('total',0)}")

    if rj.get("data_limited"):
        st.warning(rj.get("note") or "데이터 제한")

    if rj.get("answer_text"):
        st.markdown("**🧭 뉴스 흐름 요약**")
        st.info(rj["answer_text"])

    render_daily_counts(rj.get("daily_counts") or [])

    events = rj.get("top_events") or []
    if events:
        st.markdown(f"**📌 주요 이벤트 ({len(events)})**")
    for e in events:
        eg = e.get("gauge") or {}
        ac = e.get("article_count", 0)
        with st.expander(f"{e.get('canonical_title','(제목 없음)')}  ·  중요도 {e.get('importance',0):.2f}  ·  관련기사 {ac}건"):
            # 기사 1건짜리 이벤트는 비율 바가 곧 100%라 과장돼 보인다 → 표본 수 + 대표 감성 텍스트로 표시.
            if ac <= 1:
                st.markdown(f"기사 {ac}건 · **{dominant_label(eg)}** &nbsp;<span style='color:#888;font-size:12px'>(표본 1건 — 비율 생략)</span>", unsafe_allow_html=True)
            else:
                st.markdown(gauge_bar(eg), unsafe_allow_html=True)
            for a in (e.get("articles") or []):
                # 기사 제목 + (언론사·발행일) 헤더 + 요약 전문. 제목/언론사/발행일은 backend가 내려줄 때만 표시(없으면 생략).
                title = a.get("title") or a.get("summary", "")[:40]
                url = a.get("url", "")
                meta = []
                if a.get("publisher"):
                    meta.append("📰 " + str(a["publisher"]))
                if a.get("published_at"):
                    meta.append("🗓️ " + str(a["published_at"])[:10])  # YYYY-MM-DD
                st.markdown(f"**[{title}]({url})**" + ("　—　" + " · ".join(meta) if meta else ""))
                st.caption(a.get("summary", ""))


# ---------------------------------------------------------------------------
# 실행: 배치
# ---------------------------------------------------------------------------
if run_batch_clicked:
    feeds = FIN_FEEDS if feed_choice.startswith("금융") else ALL_FEEDS
    try:
        final_state = run_pipeline_staged(cap, feeds)
        st.session_state.batch = summarize_batch(final_state)
    except Exception as exc:  # 데모: 실패도 화면에 그대로 보여준다
        st.exception(exc)

# 배치 결과 요약
if st.session_state.batch:
    b = st.session_state.batch
    st.divider()
    st.subheader("✅ 수집·분석 결과")
    m = st.columns(6)
    m[0].metric("수집 기사", b["articles"])
    m[1].metric("분석 완료", b["analyzed"])
    m[2].metric("이벤트", b["events"])
    m[3].metric("그래프 노드", b["nodes"])
    m[4].metric("그래프 관계", b["rels"])
    m[5].metric("저장", b["saved"])
    if b["event_titles"]:
        st.caption("최근 이벤트: " + " · ".join(b["event_titles"]))


# ---------------------------------------------------------------------------
# 검색 → 리포트
# ---------------------------------------------------------------------------
st.divider()
st.subheader("🗞️ 검색 → 리포트")
st.caption("자유 질문은 **상장 종목**을 인식합니다(예: '삼성전자 최근 뉴스'). "
           "아래 칩은 방금 그래프에 들어간 회사를 종목 프리셋으로 바로 조회합니다.")

# 방금 배치에 등장한 회사 칩
picked_subject = None
if st.session_state.batch and st.session_state.batch["companies"]:
    st.markdown("**그래프에 있는 회사 바로 조회:**")
    chips = st.session_state.batch["companies"][:18]
    cols = st.columns(6)
    for i, name in enumerate(chips):
        if cols[i % 6].button(name, key=f"chip_{i}"):
            picked_subject = name

q = st.text_input("자유 질문", placeholder="예: 삼성전자 최근 뉴스 요약해줘")
search_clicked = st.button("리포트 생성", type="primary")

report_json = None
if picked_subject:
    with st.spinner(f"'{picked_subject}' 리포트 생성 중…"):
        report_json = build_report(subject=picked_subject)
elif search_clicked and q.strip():
    with st.spinner("리포트 생성 중…"):
        report_json = build_report(question=q.strip())

if report_json:
    render_report(report_json)
    with st.expander("🔧 원본 JSON (backend/frontend 계약)"):
        st.json(report_json)
