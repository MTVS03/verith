# streamlit_supervisor_news_lab.py — 수퍼바이저에 "검색"하면 뉴스 리포트가 나오는지 눈으로 보는 테스트 랩
"""Supervisor 진입점(planning → execution → news adapter → run_query)을 그대로 태워,
질문 하나로 **뉴스 리포트 JSON** 이 나오는지 확인하는 Streamlit 데모.

핵심: 이 앱은 news 서비스를 직접 조합하지 않는다. `src.supervisor.runtime.run_analysis` 를 불러
**실제 수퍼바이저 배선**(질문 해석 → 5 task 생성 → executor fan-out → NewsAdapter.run → run_query)을
통과한 결과에서 news 결과만 뽑아 렌더한다. 즉 "supervisor 에 붙은 news 가 리포트를 내는가" 를 검증한다.

실행:
    # 검색→리포트가 실제로 뜨려면 backend(:8001 등)+postgres+neo4j 가 떠 있어야 한다.
    BACKEND_BASE_URL=http://127.0.0.1:8001 \\
    uv run --project ai --with streamlit \\
        streamlit run ai/src/supervisor/devtools/streamlit_supervisor_news_lab.py

실행 범위(사이드바):
  - "뉴스만(빠름)"  : news adapter 만 등록 → 나머지 4개는 호출 없이 NoAdapter 로 격리(빠름·네트워크 최소).
  - "전체 5개 에이전트": default_adapters() 로 실제 fan-out(technical/fundamental/flow/industry 는
                       deps·backend 없으면 각자 실패로 격리됨 — 부분 성공 구조 확인용, 느림).
"""
from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime

# --- import 루트: ai/ (= src 패키지 위치)를 sys.path 에 넣어 `src.*` 패키지 경로로 import ---
# devtools → supervisor → src → ai (3단계 상위). streamlit 단독 실행에서도 패키지가 풀리게 shim.
_AI_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if _AI_ROOT not in sys.path:
    sys.path.insert(0, _AI_ROOT)

os.environ.setdefault("BACKEND_BASE_URL", "http://127.0.0.1:8001")

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

from src.supervisor.execution.adapters import ExecutionDeps, NewsAdapter, default_adapters  # noqa: E402
from src.supervisor.runtime import run_analysis  # noqa: E402
from src.supervisor.schemas import SupervisorInput  # noqa: E402

st.set_page_config(page_title="Supervisor · 뉴스 리포트 랩", page_icon="🛰️", layout="wide")
st.title("🛰️ Supervisor → 📰 뉴스 리포트 테스트 랩")
st.caption(
    "질문을 넣으면 **수퍼바이저 배선**(질문 해석 → 5 task 생성 → executor → NewsAdapter → run_query)을 "
    "그대로 태워, news 결과의 리포트 JSON 을 렌더합니다. news 서비스를 직접 조합하지 않습니다."
)


# ---------------------------------------------------------------------------
# 사이드바 — 실행 설정
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 설정")
    backend_url = st.text_input("backend URL", os.environ["BACKEND_BASE_URL"])
    os.environ["BACKEND_BASE_URL"] = backend_url
    scope = st.radio(
        "실행 범위",
        ["뉴스만(빠름)", "전체 5개 에이전트"],
        index=0,
        help="'뉴스만'은 news adapter 만 등록해 나머지 4개는 호출 없이 NoAdapter 로 격리합니다(빠름).",
    )
    st.divider()
    st.markdown(
        "**주의**: 첫 검색은 Qwen3·임베딩 모델 로드로 10~20초 더 걸립니다.\n\n"
        "검색→리포트가 실제로 뜨려면 backend·postgres·neo4j 가 떠 있어야 합니다."
    )


# ---------------------------------------------------------------------------
# 수퍼바이저 실행
# ---------------------------------------------------------------------------
def _adapters(scope_label: str):
    """'뉴스만'이면 news adapter 만 등록(나머지는 executor 가 NoAdapter 로 격리). 아니면 전체 5개."""
    if scope_label.startswith("뉴스만"):
        return {"news": NewsAdapter()}
    return default_adapters()


def run_supervisor_query(question: str, scope_label: str):
    """run_analysis 를 태워 ExecutionResult 를 돌려준다(endpoint wiring 을 스크립트에서 재현)."""
    rid = "lab-" + datetime.now(UTC).strftime("%H%M%S")
    deps = ExecutionDeps(request_id=rid, trace_id="lab-trace", now=datetime.now(UTC))
    inp = SupervisorInput(query=question, request_id=rid, trace_id="lab-trace")
    # resolver 미주입(None): 종목 resolve 를 시도하지 않아도 news 는 실행된다(비종목 경로 허용).
    return run_analysis(inp, resolver=None, adapters=_adapters(scope_label), deps=deps)


def news_result(execution):
    for r in execution.results:
        if r.agent_type == "news":
            return r
    return None


# ---------------------------------------------------------------------------
# 리포트 렌더 — templates/report.html(veriθ 목업)의 디자인·톤·색을 st.html 로 재현.
# report_json(ReportModel.model_dump) 을 그대로 주입하되, 없는 값은 지어내지 않는다(절대규칙 5).
# 모든 CSS 는 `.vr-report` 루트로 스코프해 Streamlit 자체 스타일과 부딪히지 않게 한다.
# ---------------------------------------------------------------------------
import html as _html  # noqa: E402


def _esc(x) -> str:
    return _html.escape(str(x if x is not None else ""))


# veriθ 팔레트(목업 :root 그대로).
_REPORT_CSS = """
<style>
html,body{margin:0;padding:0;background:#e7e9ef;}
.vr-report{--brand-50:#eef3ff;--brand-500:#3b66f5;--brand-600:#2451e6;--brand-700:#1c3fc9;
  --ink-50:#f6f7f9;--ink-100:#eceef2;--ink-200:#dde1e8;--ink-300:#c3c9d4;--ink-400:#959cac;
  --ink-500:#69707f;--ink-700:#363c48;--ink-800:#23272f;--ink-900:#13151b;
  --pos:#0fa372;--neg:#ef3e6a;--neu:#aeb4c0;
  font-family:'Pretendard',system-ui,-apple-system,sans-serif;color:var(--ink-900);
  background:radial-gradient(1200px 600px at 50% -10%,#fff 0%,#eef0f4 55%,#e7e9ef 100%);
  padding:32px 16px;border-radius:22px;}
.vr-report *{margin:0;padding:0;box-sizing:border-box;}
.vr-report .wrap{width:100%;max-width:960px;margin:0 auto;}
.vr-report .num{font-variant-numeric:tabular-nums;letter-spacing:-.01em;}
.vr-report h1,.vr-report h2,.vr-report h3{letter-spacing:-.02em;}
.vr-report .lbl{font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-400);}
.vr-report .breadcrumb{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--ink-500);margin:0 4px 20px;}
.vr-report .breadcrumb b{color:var(--ink-800);}
.vr-report article{background:#fff;border:1px solid var(--ink-100);border-radius:22px;
  box-shadow:0 20px 60px -12px rgba(19,21,27,.18);overflow:hidden;}
.vr-report header.hero{padding:36px 36px 32px;}
.vr-report .badge{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;font-weight:600;
  color:var(--brand-700);background:var(--brand-50);border-radius:999px;padding:4px 10px;}
.vr-report h1.title{font-size:30px;font-weight:700;color:var(--ink-900);margin-top:12px;line-height:1.2;}
.vr-report h1.title .sep{color:var(--ink-300);font-weight:500;}
.vr-report .meta{font-size:13px;color:var(--ink-500);margin-top:8px;}
.vr-report .meta b{color:var(--ink-700);}
.vr-report section{padding:28px 36px;border-top:1px solid var(--ink-100);}
.vr-report .overview{display:grid;grid-template-columns:300px 1fr;gap:32px;align-items:center;border-top:none;padding-top:0;}
@media (max-width:720px){.vr-report .overview{grid-template-columns:1fr;}}
.vr-report .gauge-score{font-size:40px;font-weight:700;line-height:1;}
.vr-report .gauge-bar{height:12px;border-radius:999px;overflow:hidden;display:flex;background:var(--ink-100);margin:14px 0 8px;}
.vr-report .gauge-bar>span{display:block;height:100%;}
.vr-report .legend{display:flex;gap:16px;font-size:12px;font-weight:500;margin-top:6px;}
.vr-report .legend .dot{display:inline-block;width:10px;height:10px;border-radius:999px;vertical-align:middle;margin-right:5px;}
.vr-report .stat{border:1px solid var(--ink-100);border-radius:16px;padding:22px;}
.vr-report .stat .big{font-size:34px;font-weight:700;color:var(--ink-900);line-height:1;margin-top:10px;}
.vr-report .flow{background:rgba(246,247,249,.6);}
.vr-report .flow .card{border:1px solid var(--ink-100);background:#fff;border-radius:16px;padding:20px;}
.vr-report .flow p.body{font-size:14.5px;color:var(--ink-700);line-height:1.8;white-space:pre-line;}
.vr-report .chips{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:16px;padding-top:14px;border-top:1px solid var(--ink-50);}
.vr-report .chips .chip{font-size:12px;font-weight:500;color:var(--ink-700);background:var(--ink-50);
  border:1px solid var(--ink-100);border-radius:999px;padding:4px 10px;text-decoration:none;}
.vr-report .issue{border:1px solid var(--ink-100);background:#fff;border-radius:16px;padding:16px;margin-bottom:10px;}
.vr-report .issue .row{display:flex;align-items:flex-start;gap:16px;}
.vr-report .issue .rank{width:32px;text-align:center;font-size:19px;font-weight:700;color:var(--ink-300);}
.vr-report .issue .rank.top{color:var(--brand-600);}
.vr-report .issue h3{font-size:16px;font-weight:600;color:var(--ink-900);display:inline;}
.vr-report .pill{display:inline-flex;align-items:center;font-size:11px;font-weight:600;border-radius:999px;padding:2px 8px;margin-left:8px;}
.vr-report .dist{display:flex;align-items:center;gap:12px;margin-top:12px;}
.vr-report .counts{font-size:11.5px;font-weight:500;}
.vr-report .counts .p{color:var(--pos);} .vr-report .counts .u{color:var(--ink-400);} .vr-report .counts .n{color:var(--neg);}
.vr-report .lead{font-size:12.5px;color:var(--ink-400);margin-top:10px;}
.vr-report .art-list{list-style:none;margin-top:10px;display:flex;flex-direction:column;gap:6px;}
.vr-report .art-list li{font-size:12.5px;color:var(--ink-500);}
.vr-report .art-list a{color:var(--ink-700);text-decoration:none;}
.vr-report .limit{margin:18px 36px;padding:14px 16px;border-radius:16px;background:#fff7ed;
  border:1px solid #fed7aa;color:#9a3412;font-size:13px;display:flex;gap:10px;align-items:flex-start;}
.vr-report footer{padding:20px 36px;border-top:1px solid var(--ink-100);font-size:12.5px;color:var(--ink-500);}
.vr-report .foot-note{text-align:center;font-size:11.5px;color:var(--ink-400);margin-top:20px;}
</style>
"""


def _gauge_html(g: dict) -> str:
    """긍/중/부 3분할 게이지 바(목업 .gauge-bar). pct 는 report 의 computed 필드를 그대로 쓴다."""
    pos, neu, neg = g.get("positive_pct", 0), g.get("neutral_pct", 0), g.get("negative_pct", 0)
    return (
        '<div class="gauge-bar">'
        f'<span style="width:{pos}%;background:var(--pos)"></span>'
        f'<span style="width:{neu}%;background:var(--ink-200)"></span>'
        f'<span style="width:{neg}%;background:var(--neg)"></span>'
        "</div>"
    )


def _pill_color(label: str) -> str:
    if label == "대체로 긍정":
        return "var(--pos)"
    if label == "대체로 부정":
        return "var(--neg)"
    return "#c2820a"


def _event_html(ev: dict, rank: int) -> str:
    g = ev.get("gauge") or {}
    label = g.get("label", "")
    title = _esc(ev.get("canonical_title", "(제목 없음)"))
    top = " top" if rank <= 3 else ""
    arts = ""
    if ev.get("articles"):
        lis = "".join(
            f'<li>· <a href="{_esc(a.get("url",""))}" target="_blank">'
            f'{_esc(a.get("title") or a.get("summary","")) }</a></li>'
            for a in ev["articles"]
        )
        arts = f'<ul class="art-list">{lis}</ul>'
    return f"""
    <div class="issue" id="issue-{rank}">
      <div class="row">
        <div class="rank{top} num">{rank}</div>
        <div style="flex:1;min-width:0">
          <div>
            <h3>{title}</h3>
            <span class="pill" style="color:{_pill_color(label)};background:var(--ink-50)">{_esc(label)}</span>
            <span class="lead" style="margin-left:8px">기사 <b class="num">{ev.get('article_count',0)}</b>건
              · 중요도 <span class="num">{ev.get('importance',0):.1f}</span></span>
          </div>
          <div class="dist">
            {_gauge_html(g).replace('class="gauge-bar"', 'class="gauge-bar" style="flex:1;margin:0"')}
            <div class="counts num">
              <span class="p">긍 {g.get('positive',0)}</span>
              <span class="u">중 {g.get('neutral',0)}</span>
              <span class="n">부 {g.get('negative',0)}</span>
            </div>
          </div>
          {arts}
        </div>
      </div>
    </div>"""


def report_html(rj: dict) -> str:
    """report_json → veriθ 목업 디자인 HTML 한 덩어리(st.html 로 렌더)."""
    g = rj.get("overall_gauge") or {}
    subject = _esc(rj.get("subject", "") or "(대상 미상)")
    score = g.get("score", 0.0)
    score_color = "var(--pos)" if score > 0 else "var(--neg)" if score < 0 else "var(--ink-500)"
    total = g.get("total", 0)

    # 헤더 메타(있는 값만 — period_days·기사수 없으면 지어내지 않음).
    meta_bits = []
    if rj.get("period_days"):
        meta_bits.append(f"최근 {rj['period_days']}일 집계")
    if rj.get("generated_at"):
        meta_bits.append(f"{_esc(str(rj['generated_at'])[:16].replace('T',' '))} 업데이트")
    if total:
        meta_bits.append(f'분석 기사 <b class="num">{total}</b>건')
    meta = " · ".join(meta_bits)

    events = rj.get("top_events") or []

    # 데이터 제한 배너
    limit = ""
    if rj.get("data_limited"):
        note = _esc(rj.get("note") or "근거가 부족한 부분은 추정으로 채우지 않습니다.")
        limit = f'<div class="limit"><span>⚠️</span><div><b>데이터 제한</b> — {note}</div></div>'

    # 근거 이슈 칩: cited_event_ids 를 top_events(canonical_id)에 링크해 #rank·제목으로 표시.
    rank_by_cid = {e.get("canonical_id"): i + 1 for i, e in enumerate(events) if e.get("canonical_id")}
    title_by_cid = {e.get("canonical_id"): e.get("canonical_title", "") for e in events}
    chip_html = ""
    chips = [cid for cid in (rj.get("cited_event_ids") or []) if cid in rank_by_cid]
    if chips:
        items = "".join(
            f'<a class="chip" href="#issue-{rank_by_cid[c]}">#{rank_by_cid[c]} {_esc(title_by_cid[c])}</a>'
            for c in chips
        )
        chip_html = (
            '<div class="chips"><span style="font-size:11px;font-weight:600;color:var(--ink-400)">근거 이슈</span>'
            f"{items}</div>"
        )

    # 뉴스 흐름 요약 섹션(answer_text 없으면 섹션 자체 생략)
    flow = ""
    if rj.get("answer_text"):
        flow = f"""
    <section class="flow">
      <h2 style="font-size:16px;color:var(--ink-900);margin-bottom:16px">뉴스 흐름 요약</h2>
      <div class="card"><p class="body">{_esc(rj['answer_text'])}</p>{chip_html}</div>
    </section>"""

    # TOP 이슈
    if events:
        issues = "".join(_event_html(ev, i + 1) for i, ev in enumerate(events))
    else:
        issues = '<p class="lead">표시할 이슈가 없습니다 (데이터 제한).</p>'

    legend = (
        '<div class="legend num">'
        f'<span><span class="dot" style="background:var(--pos)"></span>긍정 {g.get("positive_pct",0)}%</span>'
        f'<span><span class="dot" style="background:var(--neu)"></span>중립 {g.get("neutral_pct",0)}%</span>'
        f'<span><span class="dot" style="background:var(--neg)"></span>부정 {g.get("negative_pct",0)}%</span>'
        "</div>"
    )

    return _REPORT_CSS + f"""
<div class="vr-report"><div class="wrap">
  <div class="breadcrumb"><b>veriθ</b> · 집중 리포트 · 뉴스 · 심리</div>
  <article>
    <header class="hero">
      <span class="badge">News · Sentiment Worker</span>
      <h1 class="title">{subject} <span class="sep">·</span> 최근 뉴스 여론</h1>
      <p class="meta">{meta}</p>
    </header>
    {limit}
    <section class="overview">
      <div>
        <div class="lbl">전체 감성</div>
        <div class="gauge-score num" style="color:{score_color}">{score:+.2f}</div>
        {_gauge_html(g)}
        {legend}
      </div>
      <div class="stat">
        <div class="lbl">분석 기사 수</div>
        <div class="big num">{total}<span style="font-size:15px;color:var(--ink-400)"> 건</span></div>
        <div class="lead" style="margin-top:8px">중복 제거 후 감성 집계 대상</div>
      </div>
    </section>
    {flow}
    <section>
      <h2 style="font-size:16px;color:var(--ink-900)">주요 이슈 TOP {len(events)}</h2>
      <p class="lead" style="margin:6px 0 18px">중요도(importance) 순 · 감성은 단정하지 않고 분포로 표시합니다.</p>
      {issues}
    </section>
    <footer>이 데이터는 뉴스 여론 요약이며 <b>투자 권유가 아닙니다</b>. 모든 수치는 출처 기사에 연결되어 검증됩니다.</footer>
  </article>
  <p class="foot-note">veriθ · Multi-agent Research · News/Sentiment Worker</p>
</div></div>"""


def _report_height(rj: dict) -> int:
    """iframe 높이 추정(내용에 맞춰). 넉넉히 잡고, 모자라면 scrolling 으로 흡수."""
    h = 560  # breadcrumb + hero + overview + footer + 여백
    if rj.get("data_limited"):
        h += 80
    if rj.get("answer_text"):
        h += 130 + 20 * (len(rj["answer_text"]) // 55)  # 줄바꿈 추정
        if rj.get("cited_event_ids"):
            h += 44
    for ev in (rj.get("top_events") or []):
        h += 120 + 22 * len(ev.get("articles") or [])
    return h


def render_report(rj: dict) -> None:
    # iframe(components.html)로 렌더 — 격리돼서 목업 CSS 가 그대로 적용된다(st.html 의 DOMPurify 회피).
    components.html(report_html(rj), height=_report_height(rj), scrolling=True)


def render_pipeline(execution, elapsed: float) -> None:
    """수퍼바이저가 무엇을 했는지 (해석·rewrite·5 결과)를 투명하게 보여준다."""
    res = execution.resolution
    st.caption(
        f"⏱️ {elapsed:.1f}초 · 종목 resolve: used={res.used_stock_resolver} status={res.status}"
    )
    news = news_result(execution)
    if news is not None:
        st.markdown(f"**수퍼바이저가 news 에 넘긴 질문(rewritten):** `{news.rewritten_query}`")

    with st.expander("🔧 5개 에이전트 실행 상태 (수퍼바이저 fan-out)"):
        rows = [
            {
                "agent": r.agent_type,
                "status": r.status,
                "reason": r.reason,
                "can_run": r.can_run,
                "error": (f"{r.error.type}: {r.error.message}" if r.error else ""),
            }
            for r in execution.results
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# 검색 UI
# ---------------------------------------------------------------------------
st.divider()
q = st.text_input("수퍼바이저에 검색", placeholder="예: 삼성전자 최근 뉴스 요약해줘")
search_clicked = st.button("리포트 생성", type="primary")

if search_clicked and q.strip():
    try:
        with st.spinner("수퍼바이저 실행 중… (planning → executor → news)"):
            t0 = time.time()
            execution = run_supervisor_query(q.strip(), scope)
            elapsed = time.time() - t0
    except Exception as exc:  # 데모: 실패도 화면에 그대로 보여준다
        st.exception(exc)
    else:
        render_pipeline(execution, elapsed)
        news = news_result(execution)
        if news is None:
            st.error("news 결과가 없습니다 (수퍼바이저 배선 확인 필요).")
        elif news.status == "success":
            report_json = news.output or {}
            st.divider()
            render_report(report_json)
            with st.expander("🔧 원본 리포트 JSON (backend/frontend 계약)"):
                st.json(report_json)
        elif news.status == "skipped":
            st.warning(f"news 가 skipped 되었습니다 — reason={news.reason}")
        else:  # failed
            st.error(
                f"news 실행 실패 — {news.error.type if news.error else '?'}: "
                f"{news.error.message if news.error else ''}"
            )
elif search_clicked:
    st.info("질문을 입력하세요.")
