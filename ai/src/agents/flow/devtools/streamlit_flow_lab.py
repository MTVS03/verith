"""수급(flow) 에이전트 — 개발용 수동 시각 QA 도구 (Streamlit lab).

목적(자동 테스트 아님): 프론트/슈퍼바이저 연결 전에, 실제 사용자가 보게 될
리포트를 브라우저에서 **사람이 눈으로** 확인한다 — 수치가 실데이터와 맞는지,
디자인·표시 내용이 쓸 만한지. technical lab 과 같은 관행을 따른다.

  KIS  : real 호출 (core/kis_client — 조회 GET 만, 주문 API 는 코드에 없음)
  LLM  : real 호출 (gpt-5.4-mini — 게이트3 포함 전 구간을 실제 경로로 확인)
  진입점: production 진입점인 agent.run() 을 그대로 호출한다(우회 없음).
        supervisor 미구현은 장애물이 아니다 — lab 은 에이전트를 직접 부른다.
  저장  : 디스크 미기록. st.download_button 으로 HTML/JSON 만 내려받는다.
  secret: 화면에 절대 표시하지 않는다 (존재 여부만 OK/MISSING).

⚠ 실행할 때마다 KIS·OpenAI 를 실제로 호출한다(LLM 은 건당 소액 비용).
  render/builder.py 등 코드를 고친 뒤에는 Streamlit 리런만으로는 모듈이
  갱신되지 않으니 앱을 재시작(Ctrl+C 후 재실행)하고 다시 실행한다.

실행:
  cd ai
  uv run streamlit run src/agents/flow/devtools/streamlit_flow_lab.py

pytest/CI 에는 포함하지 않는다 (real KIS·OpenAI env 필요, 호출 비용 발생).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from dotenv import find_dotenv, load_dotenv

# 네임스페이스 패키지(PEP 420) — src 를 경로에 넣어 agents.flow.* 를 import.
_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agents.flow import agent, config  # noqa: E402

st.set_page_config(page_title="flow lab — 수급 리포트 QA", layout="wide")
st.title("수급(flow) 에이전트 — 수동 QA lab")

# ── 1. 환경 상태 (존재 여부만 — 값은 절대 출력하지 않는다) ─────────────
load_dotenv(find_dotenv(usecwd=False))
_REQUIRED_ENV = ["KIS_API_KEY", "KIS_API_SECRET", "KIS_BASE_URL", "OPENAI_API_KEY"]
_missing = [k for k in _REQUIRED_ENV if not os.getenv(k)]

with st.expander("1. 환경 상태", expanded=bool(_missing)):
    for key in _REQUIRED_ENV:
        st.write(f"- `{key}` : {'OK' if os.getenv(key) else '**MISSING**'}")
    st.caption("※ 존재 여부만 표시합니다. secret 값은 화면에 출력하지 않습니다.")
if _missing:
    st.error(f"환경 변수 누락: {', '.join(_missing)} — ai/.env 확인 후 새로고침하세요.")
    st.stop()

# ── 2. 입력 ────────────────────────────────────────────────────────────
st.header("2. 입력")
col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    stock_name = st.text_input("종목명", value=config.TARGET_NAME,
                               help="이름만 넣으면 게이트1이 KIS 종목 마스터로 티커를 찾습니다")
with col2:
    ticker_raw = st.text_input("티커 (6자리 · 비우면 자동)", value="")
    ticker = ticker_raw.strip() or None
with col3:
    auto_date = st.checkbox("기준일 자동 (게이트1의 18시 규칙)", value=True)
    base_date = None if auto_date else st.date_input("기준일", value=date.today())

# ── 3. 실행 — production 경로 그대로 (agent.run 한 번) ─────────────────
if st.button("리포트 생성 (KIS·LLM 실호출)", type="primary"):
    with st.spinner("게이트1 → 수집 → 신호 → 게이트2 → LLM 해석 → 게이트3 → 렌더 ..."):
        try:
            st.session_state["flow_out"] = agent.run(
                stock_name=stock_name, ticker=ticker, base_date=base_date
            )
        except Exception as e:  # noqa: BLE001 — 규약: 첫 에러를 그대로 보여주고 멈춘다.
            st.session_state.pop("flow_out", None)
            st.error(f"{type(e).__name__}: {e}")
            st.stop()

out = st.session_state.get("flow_out")
if out is None:
    st.info("입력을 확인하고 [리포트 생성]을 누르세요.")
    st.stop()

# ── 4. 결과 — 게이트 배지 → HTML 리포트 → payload(JSON) ───────────────
st.header("3. 결과")
payload = out.payload or {}
meta = payload.get("meta") or out.meta
st.caption(
    f"report_id `{out.report_id}` · 확정 기준일 **{meta.get('base_date')}** · "
    f"market {meta.get('market') or '—'}"
)

# 게이트 배지: verification 이 "검증된 데이터" 정체성의 운반체 — 눈에 먼저 보이게.
gates = payload.get("verification") or {}
cols = st.columns(3)
for i, name in enumerate(("gate1", "gate2", "gate3")):
    g = gates.get(name)
    passed = g.get("passed") if isinstance(g, dict) else None
    label = {"gate1": "게이트1 입력", "gate2": "게이트2 팩트↔데이터",
             "gate3": "게이트3 해석↔팩트"}[name]
    with cols[i]:
        if passed is True:
            st.success(f"{label} — 통과")
        elif passed is False:
            st.error(f"{label} — 실패")
        else:
            st.warning(f"{label} — 기록 없음")
if payload.get("interpretation") is None:
    st.warning("해석 없음 — 게이트3 미통과(재시도 상한 초과) 시의 안전 후퇴입니다. 팩트만 표시됩니다.")

tab_html, tab_json = st.tabs(["HTML 리포트 (사용자 화면)", "payload (JSON 출구)"])
with tab_html:
    height = st.slider("표시 높이(px)", 600, 3000, 1600, step=100)
    components.html(out.html, height=height, scrolling=True)
    st.download_button("HTML 내려받기", out.html,
                       file_name=f"flow_report_{meta.get('ticker')}_{meta.get('base_date')}.html",
                       mime="text/html")
with tab_json:
    st.json(payload)
    st.download_button("JSON 내려받기",
                       json.dumps(payload, ensure_ascii=False, indent=2),
                       file_name=f"flow_payload_{meta.get('ticker')}_{meta.get('base_date')}.json",
                       mime="application/json")
