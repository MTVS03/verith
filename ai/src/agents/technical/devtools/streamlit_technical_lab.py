"""기술적 분석 에이전트 — 개발용 수동 시각 QA 도구 (Streamlit lab).

목적(자동 테스트 아님): 프론트 구현 전에 KIS D/W/M 시세와 `run_technical_agent()` 출력·
chart payload 가 화면에서 쓸 만한 구조인지 **사람이 눈으로** 확인한다.

  KIS : real 호출 (services/kis_client.fetch_multi_timeframe_ohlcv — 이 파일은 KIS API 직접 호출 없음)
  LLM : fake (payload-aware — 프롬프트의 코드 확정 라벨을 읽어 검증 ③ 1차 통과 문장 생성, 우회 없음)
  진입점 : 공식 agent.run_technical_agent() 만 호출 (production 로직·노드 직접 호출 없음)
  저장 : 디스크 미기록. st.download_button 으로 output JSON 만 내려받는다.
  secret : 화면에 절대 표시하지 않는다 (존재 여부만 OK/MISSING).

⚠ Streamlit session_state 는 production cache(Redis/cache_service)가 아니라 **수동 QA용 임시 상태**다.

실행:
  cd ai
  uv run streamlit run src/agents/technical/devtools/streamlit_technical_lab.py

pytest/CI 에는 포함하지 않는다(real KIS env 필요).
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd
import streamlit as st

try:  # altair 는 streamlit 번들 의존성 — 없거나 실패하면 close line fallback 으로 동작.
    import altair as alt
except ImportError:  # pragma: no cover - 환경 방어용
    alt = None

# 스탠드얼론 스크립트라 ai/ 를 sys.path 에 올려 `src...` import 가 되게 한다(smoke script 와 동일).
_AI_ROOT = Path(__file__).resolve().parents[4]
if str(_AI_ROOT) not in sys.path:
    sys.path.insert(0, str(_AI_ROOT))

from src.agents.technical.agent import run_technical_agent  # noqa: E402
from src.agents.technical.config import (  # noqa: E402
    BATTERY_TICKERS,
    REQUIRED_ENV_KEYS,
    load_kis_settings,
)
from src.agents.technical.observability.keyword_rules import (  # noqa: E402
    CONFIDENCE_LABELS,
    CONSENSUS_LABELS,
    INDICATOR_LABELS,
    REGIME_LABELS,
    RISK_LABELS,
    SIGNAL_LABELS,
)
from src.agents.technical.schemas.chart import ChartData  # noqa: E402
from src.agents.technical.schemas.contracts import (  # noqa: E402
    ChartPayload,
    TechnicalAgentInput,
    TechnicalAgentOutput,
)
from src.agents.technical.schemas.enums import (  # noqa: E402
    AlignmentFlag,
    ConfidenceLevel,
    Consensus,
    IndicatorType,
    Regime,
    RiskFlag,
    Signal,
)
from src.agents.technical.schemas.intraday import (  # noqa: E402
    IntradayCandle,
    IntradayChartData,
    IntradayContext,
)
from src.agents.technical.schemas.ohlcv import OHLCV  # noqa: E402
from src.agents.technical.charts.intraday_chart_builder import (  # noqa: E402
    build_intraday_chart_payload,
)
from src.agents.technical.charts.intraday_context_builder import (  # noqa: E402
    build_intraday_context,
)
from src.agents.technical.synthesis.intraday_alignment import (  # noqa: E402
    apply_intraday_hint_to_context,
)
from src.agents.technical.synthesis.intraday_adjustment import (  # noqa: E402
    apply_intraday_adjustments,
)
from src.agents.technical.services.kis_client import (  # noqa: E402
    KisApiError,
    OutOfScopeTickerError,
    fetch_minute_ohlcv,
    fetch_multi_timeframe_ohlcv,
)

_FOCUS_RESPONSE = json.dumps(
    {
        "analysis_focus": ["trend", "momentum", "volume", "support_resistance", "risk"],
        "focus_summary": "추세·모멘텀·거래량·지지저항·리스크 관찰점을 함께 확인합니다.",
    },
    ensure_ascii=False,
)


# ─────────────────────────────────────────────────────────────────────────────
# payload-aware fake LLM (self-contained)
# smoke script(scripts/smoke_technical_agent.py)의 fake 와 분기·문장 계약을 맞추되,
# 정책상 cross-import 하지 않는다(각 도구가 독립 실행 가능하도록 의도된 중복).
# 라벨 사전은 observability.keyword_rules 를 공용 import 하므로 계약의 단일 출처는 유지된다.
# ─────────────────────────────────────────────────────────────────────────────
class LabFakeLlm:
    """프롬프트 종류에 따라 응답을 분기하는 fake. 실제 LLM/네트워크 호출 없음.

    분기 기준은 프롬프트가 요구하는 출력 스키마 키:
      - "interpretation_text" → interpret_report / regenerate_report (payload 확정 라벨 echo)
      - "analysis_focus"      → focus_analysis (정적 정상 응답)
      - "normalized_question" → normalize_question (ticker 회사명 포함)
    검증기를 우회하지 않으며 금지어·매수/매도/추천/확실/보장/목표주가 표현을 쓰지 않는다.
    """

    def __init__(self, company_name: str) -> None:
        self._company = company_name

    def complete(self, prompt: str) -> str:
        if "interpretation_text" in prompt:  # interpret_report / regenerate_report
            return _build_interpretation(_extract_payload(prompt))
        if "analysis_focus" in prompt:  # focus_analysis
            return _FOCUS_RESPONSE
        if "normalized_question" in prompt:  # normalize_question
            return json.dumps(
                {"normalized_question": (
                    f"{self._company}의 최근 시세·거래량·기술적 신호를 중심으로 "
                    f"현재 차트 국면과 리스크 관찰점을 분석합니다."
                )},
                ensure_ascii=False,
            )
        raise RuntimeError("알 수 없는 프롬프트 유형(fake LLM 분기 실패)")


def _extract_payload(prompt: str) -> dict:
    """interpret 프롬프트에 렌더된 코드 확정값 payload(JSON)를 뽑는다.

    프롬프트 안의 ```json 블록 중 `final_regime` 키를 가진 것(= 실제 payload)을 고른다.
    (출력 형식 예시 블록에는 final_regime 이 없다.)
    """
    for block in re.findall(r"```json\s*(.*?)\s*```", prompt, re.DOTALL):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "final_regime" in data:
            return data
    raise RuntimeError("interpret 프롬프트에서 payload 를 찾지 못했습니다")


def _build_interpretation(payload: dict) -> str:
    """확정 라벨을 자연어로 echo. 검증 ③(라벨 대표어·신호·confidence·risk 언급)을 1차 통과하도록.

    코드 확정값을 바꾸지 않고 문장만 만든다. 금지어·매수/매도 표현 없음.
    """
    final_regime = Regime(payload["final_regime"])
    consensus = Consensus(payload["consensus"])
    conf_level = ConfidenceLevel(payload["confidence_level"])
    alignment = AlignmentFlag(payload["alignment_flag"])
    risk_flags = [RiskFlag(item["flag"]) for item in payload.get("risk_items", [])]

    parts = [
        f"현재 차트는 {REGIME_LABELS[final_regime]} 국면으로 관찰되며, "
        f"종합 신호는 {CONSENSUS_LABELS[consensus]} 수준으로 해석됩니다.",
        f"신뢰도는 {CONFIDENCE_LABELS[conf_level]} 수준입니다.",
    ]
    if alignment == AlignmentFlag.ALIGNED:
        parts.append("상위 추세와 정합합니다.")
    elif alignment == AlignmentFlag.COUNTER_TREND:
        parts.append("상위 추세와 역행합니다.")
    if risk_flags:
        parts.append(
            "주요 관찰 요인으로 " + "·".join(RISK_LABELS[f] for f in risk_flags)
            + "이(가) 함께 확인됩니다."
        )
    parts.append("이 내용은 투자 판단을 대신하지 않으며, 기술적 지표 기반 참고 정보입니다.")

    details = [
        {
            "indicator": s["indicator"],
            "detail": (
                f"{INDICATOR_LABELS[IndicatorType(s['indicator'])]} 지표는 "
                f"{SIGNAL_LABELS[Signal(s['signal'])]} 신호로 확인됩니다."
            ),
        }
        for s in payload["technical_signals"]
    ]
    return json.dumps(
        {"interpretation_text": " ".join(parts), "details": details}, ensure_ascii=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# chart payload(ChartData) → pandas DataFrame 변환 (built-in st.*_chart 용)
# ─────────────────────────────────────────────────────────────────────────────
def _price_ma_df(cd: ChartData) -> pd.DataFrame:
    """종가 + 이동평균선. index=date(ISO str), columns=close/MA{window}."""
    df = pd.DataFrame(
        {"close": [c.close for c in cd.candles]},
        index=[c.date for c in cd.candles],
    )
    for ma in cd.overlays.moving_average:
        series = pd.Series({p.date: p.value for p in ma.points}, name=f"MA{ma.window}")
        df = df.join(series)
    return df


def _sr_rows(cd: ChartData) -> list[dict]:
    """support/resistance 표시용 행(수평선 근사는 표로 대체)."""
    return [
        {
            "type": sr.type,
            "price": sr.price,
            "from": sr.from_,
            "to": sr.to,
            "touch_count": sr.touch_count,
        }
        for sr in cd.overlays.support_resistance
    ]


def _ma_long_df(cd: ChartData) -> pd.DataFrame:
    """MA overlay 를 long-form(date/window/value)으로 — altair color=window 용."""
    rows = [
        {"date": p.date, "window": f"MA{ma.window}", "value": p.value}
        for ma in cd.overlays.moving_average
        for p in ma.points
    ]
    return pd.DataFrame(rows)


def _candlestick_chart(cd: ChartData) -> "alt.LayerChart":
    """candles → altair candlestick(wick+body) + MA line overlay + SR horizontal rule.

    OHLC·MA·SR 는 chart payload 값만 사용한다(재계산 없음). 상승봉=빨강, 하락봉=파랑(국내 관례).
    필드 결손·빈 candles 는 예외를 던져 호출부에서 close line fallback 으로 넘어가게 한다.
    """
    if not cd.candles:
        raise ValueError("candles 가 비어 candlestick 을 그릴 수 없습니다")
    df = pd.DataFrame(
        [
            {"date": c.date, "open": c.open, "high": c.high, "low": c.low, "close": c.close}
            for c in cd.candles
        ]
    )
    df["is_up"] = df["close"] >= df["open"]
    # 상승(빨강)/하락(파랑) 최소 색상만 — QA용 시각 구분(과도한 스타일링 없음).
    up_down = alt.Color(
        "is_up:N",
        scale=alt.Scale(domain=[True, False], range=["#d62728", "#1f77b4"]),
        legend=None,
    )
    base = alt.Chart(df).encode(x=alt.X("date:T", title="date"))
    wick = base.mark_rule().encode(y=alt.Y("low:Q", title="price"), y2="high:Q", color=up_down)
    body = base.mark_bar().encode(
        y="open:Q", y2="close:Q", color=up_down,
        tooltip=["date:T", "open:Q", "high:Q", "low:Q", "close:Q"],
    )
    layers = [wick, body]

    ma_df = _ma_long_df(cd)
    if not ma_df.empty:
        layers.append(
            alt.Chart(ma_df).mark_line().encode(
                x="date:T", y="value:Q", color=alt.Color("window:N", title="MA"),
                tooltip=["date:T", "window:N", "value:Q"],
            )
        )

    sr_df = pd.DataFrame(
        [{"type": sr.type, "price": sr.price} for sr in cd.overlays.support_resistance]
    )
    if not sr_df.empty:
        layers.append(
            alt.Chart(sr_df).mark_rule(strokeDash=[4, 4]).encode(
                y="price:Q", color=alt.Color("type:N", title="S/R"),
                tooltip=["type:N", "price:Q"],
            )
        )

    return alt.layer(*layers).resolve_scale(color="independent").properties(height=420)


def _rsi_df(cd: ChartData) -> pd.DataFrame:
    """RSI line + overbought/oversold 기준선(상수 컬럼)."""
    rsi = cd.subcharts.rsi
    df = pd.DataFrame(
        {"RSI": [p.value for p in rsi.points]},
        index=[p.date for p in rsi.points],
    )
    df["overbought"] = rsi.overbought
    df["oversold"] = rsi.oversold
    return df


def _volume_df(cd: ChartData) -> pd.DataFrame:
    """거래량 + 평균 거래량."""
    vol = cd.subcharts.volume
    return pd.DataFrame(
        {
            "volume": [b.volume for b in vol.bars],
            "avg_volume": [b.avg_volume for b in vol.bars],
        },
        index=[b.date for b in vol.bars],
    )


def _annotation_rows(cd: ChartData) -> list[dict]:
    return [
        {
            "id": a.id,
            "kind": a.kind,
            "date": a.date,
            "price": a.price,
            "importance": a.importance,
            "label": a.label,
            "source": a.source,
        }
        for a in cd.annotations
    ]


def _raw_summary_rows(raw: dict[str, list[OHLCV]]) -> list[dict]:
    """KIS raw D/W/M 요약(건수·기간·최근값). secret 무관, 시세만."""
    rows: list[dict] = []
    for unit, bars in raw.items():
        if not bars:
            rows.append({"unit": unit, "rows": 0, "from": "-", "to": "-", "last_close": "-"})
            continue
        last = bars[-1]
        rows.append(
            {
                "unit": unit,
                "rows": len(bars),
                "from": bars[0].date,
                "to": last.date,
                "last_close": last.close,
                "last_volume": last.volume,
                "last_trading_value": last.trading_value,
            }
        )
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 상태 서명(session_state stale 방지)
#   - KIS 캐시 유효성 : ticker + as_of(날짜)      — KIS 조회는 query 와 무관.
#   - Agent 출력 유효성 : ticker + as_of + query   — query 변경도 반드시 stale 로 판단.
# ─────────────────────────────────────────────────────────────────────────────
def _kis_sig(ticker: str, as_of_date: date) -> str:
    return f"{ticker}@{as_of_date.isoformat()}"


def _agent_sig(ticker: str, as_of_dt: datetime, query: str) -> str:
    return f"{ticker}@{as_of_dt.isoformat()}@{query}"


# ─────────────────────────────────────────────────────────────────────────────
# Streamlit 화면 구간별 render (top→bottom, session_state 로 재실행 간 재사용)
# ─────────────────────────────────────────────────────────────────────────────
def _render_env_section() -> bool:
    """1. Environment / KIS 상태. secret 값은 표시하지 않고 존재 여부만 OK/MISSING."""
    st.header("1. Environment / KIS 상태")
    try:
        load_kis_settings()  # .env 로딩 + fail-fast(누락 키 이름만 메시지, secret 노출 없음)
        env_ok = True
        env_error = None
    except RuntimeError as exc:
        env_ok = False
        env_error = str(exc)  # 누락 키 이름만 포함(값 없음)

    env_rows = [
        {"env_key": key, "status": "OK" if os.getenv(key) else "MISSING"}
        for key in REQUIRED_ENV_KEYS
    ]
    st.dataframe(pd.DataFrame(env_rows), use_container_width=True, hide_index=True)
    st.caption("※ 존재 여부만 표시합니다. secret 값은 화면에 출력하지 않습니다.")
    if env_ok:
        st.success("KIS 인증정보 로딩 OK — real KIS 호출이 가능합니다.")
    else:
        st.error(f"KIS 인증정보가 없어 실제 조회를 실행할 수 없습니다: {env_error}")
        st.info("ai/.env 에 KIS_API_KEY / KIS_API_SECRET / KIS_BASE_URL 을 설정한 뒤 새로고침하세요.")
    return env_ok


def _render_ticker_section() -> tuple[str, str]:
    """2. 종목 선택. (ticker, company) 반환."""
    st.header("2. 종목 선택")
    ticker = st.selectbox(
        "종목 (MVP allowlist)",
        options=list(BATTERY_TICKERS.keys()),
        format_func=lambda t: f"{t} · {BATTERY_TICKERS[t]}",
    )
    return ticker, BATTERY_TICKERS[ticker]


def _render_query_section(company: str) -> tuple[str, date, datetime]:
    """3. 조회 조건. (query, as_of_date, as_of_dt) 반환."""
    st.header("3. 조회 조건")
    col_q, col_d = st.columns([3, 1])
    with col_q:
        query = st.text_input("질의(query)", value=f"{company} 기술적 흐름을 분석해줘")
    with col_d:
        as_of_date: date = st.date_input("as_of (기준일)", value=date.today(), max_value=date.today())
    as_of_dt = datetime.combine(as_of_date, time(15, 30))  # naive — smoke 와 동일 계열
    st.caption(f"기준일 {as_of_date.isoformat()} → as_of={as_of_dt.isoformat()} (KIS end_date 동일 기준)")
    return query, as_of_date, as_of_dt


def _render_kis_raw_section(
    ticker: str, as_of_date: date, env_ok: bool,
) -> dict[str, list[OHLCV]] | None:
    """4. Raw KIS D/W/M. 버튼 클릭 시에만 real KIS 호출. 현재 조건과 일치하는 raw 만 반환."""
    st.header("4. Raw KIS D/W/M 데이터 확인")
    st.caption(
        "[KIS 데이터 가져오기] 버튼을 눌렀을 때만 real KIS 를 호출합니다. "
        "Streamlit rerun(기간 변경·tab·JSON 확인)에서는 재호출하지 않고 session_state 를 재사용합니다."
    )
    if st.button("KIS 데이터 가져오기 (real KIS)", disabled=not env_ok, type="primary"):
        with st.spinner("real KIS 호출 중 (D/W/M)..."):
            try:
                raw = fetch_multi_timeframe_ohlcv(ticker, end_date=as_of_date)
                st.session_state["kis_data"] = raw
                st.session_state["kis_data_sig"] = _kis_sig(ticker, as_of_date)
                # 조건이 바뀌었으니 이전 agent 출력·서명 무효화
                st.session_state.pop("agent_output", None)
                st.session_state.pop("agent_sig", None)
                st.success("KIS 데이터 가져오기 완료 — session_state 에 저장했습니다.")
            except Exception as exc:  # noqa: BLE001 - QA 도구: 원인 메시지를 화면에 그대로 노출
                st.exception(exc)

    raw_cached: dict[str, list[OHLCV]] | None = st.session_state.get("kis_data")
    raw_sig = st.session_state.get("kis_data_sig")
    current_sig = _kis_sig(ticker, as_of_date)
    if raw_cached is None:
        st.info("먼저 [KIS 데이터 가져오기]를 눌러 주세요.")
        return None

    matched = raw_sig == current_sig
    if not matched:
        st.warning(
            f"저장된 KIS 데이터는 다른 조건({raw_sig})입니다. "
            f"현재 조건({current_sig})으로 [KIS 데이터 가져오기]를 다시 눌러 주세요."
        )
    st.dataframe(pd.DataFrame(_raw_summary_rows(raw_cached)), use_container_width=True, hide_index=True)
    with st.expander("타임프레임별 최근 봉 미리보기"):
        for unit, bars in raw_cached.items():
            st.markdown(f"**{unit}** (최근 10봉)")
            tail = [b.model_dump() for b in bars[-10:]]
            st.dataframe(pd.DataFrame(tail), use_container_width=True, hide_index=True)

    return raw_cached if matched else None  # agent 는 현재 조건과 일치할 때만 사용


def _render_agent_summary_section(
    *, ticker: str, company: str, query: str,
    as_of_dt: datetime, usable_raw: dict[str, list[OHLCV]] | None,
) -> TechnicalAgentOutput | None:
    """5. Agent Output Summary. 실행 + stale 가드 + 요약. 현재 조건 출력만 반환."""
    st.header("5. Agent Output Summary")
    st.caption(
        "run_technical_agent() 을 fake LLM + injected fetcher(§4 캐시 재사용)로 실행합니다. "
        "→ KIS 이중 호출 없음."
    )
    current_sig = _agent_sig(ticker, as_of_dt, query)
    can_run = usable_raw is not None
    if not can_run:
        st.info("먼저 KIS 데이터를 가져와 주세요 (§4). 그래야 Agent 를 실행할 수 있습니다.")

    if st.button("Agent 실행 (fake LLM)", disabled=not can_run):
        cached = usable_raw

        def cached_fetcher(_ticker: str, *, end_date: object = None) -> dict[str, list[OHLCV]]:
            """§4 에서 받은 raw 를 그대로 반환 — 파이프라인이 KIS 를 다시 부르지 않게 한다."""
            return cached

        agent_input = TechnicalAgentInput(
            ticker=ticker,
            query=query,
            request_id=f"lab_{uuid.uuid4().hex[:12]}",
            as_of=as_of_dt,
        )
        with st.spinner("run_technical_agent 실행 중..."):
            try:
                output = run_technical_agent(
                    agent_input,
                    llm_client=LabFakeLlm(company_name=company),
                    fetcher=cached_fetcher,
                )
                st.session_state["agent_output"] = output
                st.session_state["agent_sig"] = current_sig  # 이 출력이 어떤 조건 결과인지 기록
                st.success("agent 실행 완료.")
            except Exception as exc:  # noqa: BLE001 - QA 도구: 원인 메시지 노출
                st.exception(exc)

    output: TechnicalAgentOutput | None = st.session_state.get("agent_output")
    if output is None:
        return None
    # stale 가드: 저장된 출력의 조건 서명이 현재(ticker+as_of+query)와 다르면 표시하지 않는다.
    if st.session_state.get("agent_sig") != current_sig:
        st.info("조회 조건이 변경되었습니다. Agent를 다시 실행해 주세요.")
        return None

    _render_summary_metrics(output)
    _render_technical_signals_table(output)
    return output


def _render_technical_signals_table(output: TechnicalAgentOutput) -> None:
    """5. technical_signals 요약 표(§5 하단). production 계산값을 그대로 표시(재계산 없음).

    chart 가 비어도(data_limited) 5지표 계산 여부를 여기서 확인할 수 있게 §5 에 둔다.
    value=None 은 0 으로 바꾸지 않고 "—" 로 표시한다(honest scoping).
    """
    st.markdown("**technical_signals** (5지표 계산 결과 — production 계산값 그대로)")
    signals = output.technical_signals
    if not signals:
        st.caption("technical_signals 없음 (regime_unavailable / data_limited 등)")
        return
    rows = [
        {
            "indicator": s.indicator.value,
            "signal": s.signal.value,
            "value": "—" if s.value is None else s.value,
            "weight": s.weight,
            "detail_source": s.detail_source.value,
            "detail": s.detail,
        }
        for s in signals
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    present = {s.indicator.value for s in signals}
    expected = [indicator.value for indicator in IndicatorType]  # 정본 enum 순서 그대로
    missing = [e for e in expected if e not in present]
    if missing:
        st.caption(f"포함 지표: {sorted(present)} · 누락: {missing}")
    else:
        st.caption(f"{len(expected)}지표({'·'.join(expected)}) 모두 포함")


def _render_summary_metrics(output: TechnicalAgentOutput) -> None:
    """5. 요약 카드 + interpretation.text (계약 필드명 기준)."""
    signal = output.signal
    risk_count = len(output.risk.items) if output.risk else 0
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("final_regime", output.regime.final_regime.value)
    m2.metric("consensus", signal.consensus.value if signal else "-")
    m3.metric("signal_score", f"{signal.signal_score:.3f}" if signal else "-")
    m4.metric("confidence", f"{signal.confidence:.3f}" if signal else "-")
    m5, m6, m7, m8 = st.columns(4)
    m5.metric("data_status", output.data_status.value)
    m6.metric("source", output.source)
    m7.metric("verification", output.verification.outcome.value)
    m8.metric("regen_count", output.verification.regen_count)
    st.caption(
        f"technical_signals={len(output.technical_signals)} · risk_flags={risk_count} · "
        f"charts={len(output.charts)} · interpretation.source={output.interpretation.source.value}"
    )
    st.markdown("**interpretation.text**")
    st.write(output.interpretation.text)


def _render_price_chart(cd: ChartData, view_mode: str) -> None:
    """Candlestick(altair) 우선, 불가/실패/사용자가 Close line 선택 시 close line fallback.

    KIS 재조회·OHLC 재계산 없이 chart payload 의 candles·MA overlay 만 사용한다.
    """
    if view_mode == "Candlestick":
        if alt is None:
            st.warning("Candlestick view is unavailable. Showing close line fallback.")
        else:
            try:
                st.altair_chart(_candlestick_chart(cd), use_container_width=True)
                return
            except Exception as exc:  # noqa: BLE001 - fallback + 원인은 expander 로 노출(숨기지 않음)
                st.warning("Candlestick view is unavailable. Showing close line fallback.")
                with st.expander("candlestick 렌더 오류 상세"):
                    st.exception(exc)
    # Close line fallback (close + MA line)
    st.line_chart(_price_ma_df(cd))


def _render_chart_section(output: TechnicalAgentOutput) -> tuple[str, ChartPayload] | None:
    """6~9. 기간 선택 + Price/MA + Volume/RSI + Annotation. (period_key, payload) 반환."""
    if not output.charts:
        st.warning("charts 가 비어 있어 §6~9 차트 검수를 건너뜁니다(data_limited 등).")
        return None

    # 6. Chart Period Selector
    st.header("6. Chart Period Selector")
    period_map = {p.period.value: p for p in output.charts}
    period_key = st.radio("기간", options=list(period_map.keys()), horizontal=True)
    payload = period_map[period_key]
    cd = payload.chart_data
    st.caption(
        f"period={payload.period.value} · candle_unit={cd.candle_unit} · candles={len(cd.candles)} · "
        f"MA={len(cd.overlays.moving_average)} · SR={len(cd.overlays.support_resistance)} · "
        f"RSI={len(cd.subcharts.rsi.points)} · volume={len(cd.subcharts.volume.bars)} · "
        f"annotations={len(cd.annotations)}"
    )

    # 7. Price / Moving Average Chart (Candlestick 기본, Close line fallback)
    st.header("7. Price / Moving Average Chart")
    view_mode = st.radio(
        "Price chart view", ["Candlestick", "Close line"], horizontal=True, key="price_view_mode",
    )
    _render_price_chart(cd, view_mode)
    sr_rows = _sr_rows(cd)
    if sr_rows:
        st.markdown(
            "**support / resistance** — 표로 확인"
            + (" (candlestick view 에서는 점선 수평선으로 근사 표시)" if view_mode == "Candlestick" else "")
        )
        st.dataframe(pd.DataFrame(sr_rows), use_container_width=True, hide_index=True)
    else:
        st.caption("support_resistance 없음")

    # 8. Volume / RSI Chart
    st.header("8. Volume / RSI Chart")
    vol_df = _volume_df(cd)
    st.markdown("**volume** (bar)")
    st.bar_chart(vol_df[["volume"]])
    st.markdown("**avg_volume** (line)")
    st.line_chart(vol_df[["avg_volume"]])
    spikes = [b for b in cd.subcharts.volume.bars if b.is_spike]
    st.caption(f"volume spike(is_spike=True): {len(spikes)}건")
    if spikes:
        with st.expander("volume spike 상세"):
            st.dataframe(
                pd.DataFrame(
                    [{"date": b.date, "volume": b.volume, "avg_volume": b.avg_volume} for b in spikes]
                ),
                use_container_width=True, hide_index=True,
            )
    st.markdown("**RSI** (+ overbought / oversold 기준선)")
    st.line_chart(_rsi_df(cd))

    # 9. Annotation Table
    st.header("9. Annotation Table")
    ann_rows = _annotation_rows(cd)
    if ann_rows:
        st.dataframe(pd.DataFrame(ann_rows), use_container_width=True, hide_index=True)
        kind_counts = pd.Series([r["kind"] for r in ann_rows]).value_counts()
        st.caption("kind 별 개수: " + ", ".join(f"{k}={v}" for k, v in kind_counts.items()))
    else:
        st.caption("annotation 없음")

    return period_key, payload


def _render_raw_json_section(
    output: TechnicalAgentOutput, chart_selection: tuple[str, ChartPayload] | None,
) -> None:
    """10. Raw JSON Viewer + download_button (디스크 미기록, secret 미포함)."""
    st.header("10. Raw JSON Viewer")
    st.caption("secret 값은 출력에 포함되지 않습니다(시세·분석 결과만).")
    st.download_button(
        "output JSON 다운로드",
        data=output.model_dump_json(indent=2),
        file_name=f"{output.ticker}_{output.as_of.strftime('%Y%m%d')}_{output.request_id}.json",
        mime="application/json",
    )
    with st.expander("전체 output JSON"):
        st.json(output.model_dump(mode="json"))
    if chart_selection is not None:
        period_key, payload = chart_selection
        with st.expander(f"선택 기간({period_key}) chart_data JSON"):
            st.json(payload.model_dump(mode="json"))


# ─────────────────────────────────────────────────────────────────────────────
# 오케스트레이션
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# 11. 1D Intraday QA (fixture/manual 기반 — KIS 무관, production 재구현 없음)
# ─────────────────────────────────────────────────────────────────────────────
_SAMPLE_MANUAL_JSON = json.dumps(
    [
        {"timestamp": "2026-07-06T09:00:00", "open": 100, "high": 101, "low": 99.5,
         "close": 100.5, "volume": 120, "interval": "1min"},
        {"timestamp": "2026-07-06T09:01:00", "open": 100.5, "high": 101.2, "low": 100.1,
         "close": 101.0, "volume": 150, "interval": "1min"},
        {"timestamp": "2026-07-06T09:02:00", "open": 101.0, "high": 101.5, "low": 100.8,
         "close": 101.3, "volume": 600, "interval": "1min"},
    ],
    ensure_ascii=False, indent=2,
)


def _sample_intraday_candles() -> list[IntradayCandle]:
    """데모용 30개 1분봉(완만한 상승 + 후반 거래량 급증). 결정론적(랜덤 없음)."""
    candles: list[IntradayCandle] = []
    for i in range(30):
        close = 100 + i * 0.08  # 완만한 상승(마지막 ≈+2.3% <3%) → upward_intraday 데모
        candles.append(
            IntradayCandle(
                timestamp=f"2026-07-06T09:{i:02d}:00",
                open=close - 0.1, high=close + 0.3, low=close - 0.3, close=close,
                volume=600 if i == 25 else 120, interval="1min",
            )
        )
    return candles


def _parse_manual_candles(raw: str) -> list[IntradayCandle]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("JSON 최상위는 IntradayCandle 객체의 리스트여야 합니다")
    return [IntradayCandle(**item) for item in data]


def _intraday_price_df(cd: IntradayChartData) -> pd.DataFrame:
    df = pd.DataFrame({"close": [c.close for c in cd.candles]},
                      index=[c.timestamp for c in cd.candles])
    if cd.short_ma:
        df = df.join(pd.Series({p.timestamp: p.value for p in cd.short_ma}, name="short_ma"))
    if cd.previous_close is not None:
        df["previous_close"] = cd.previous_close
    return df


def _intraday_volume_df(cd: IntradayChartData) -> pd.DataFrame:
    return pd.DataFrame({"volume": [c.volume for c in cd.candles]},
                        index=[c.timestamp for c in cd.candles])


def _intraday_vwap_df(points: list) -> pd.DataFrame:
    """IntradayPoint 리스트(예: context.vwap) → line_chart용 DataFrame."""
    return pd.DataFrame({"vwap": [p.value for p in points]},
                        index=[p.timestamp for p in points])


def _intraday_candlestick_chart(cd: IntradayChartData) -> "alt.LayerChart":
    """intraday candlestick + short MA + previous_close/day_high/day_low 수평선(altair)."""
    if not cd.candles:
        raise ValueError("intraday candles 가 비어 candlestick 을 그릴 수 없습니다")
    df = pd.DataFrame(
        [{"timestamp": c.timestamp, "open": c.open, "high": c.high, "low": c.low, "close": c.close}
         for c in cd.candles]
    )
    df["is_up"] = df["close"] >= df["open"]
    up_down = alt.Color("is_up:N", scale=alt.Scale(domain=[True, False], range=["#d62728", "#1f77b4"]),
                        legend=None)
    base = alt.Chart(df).encode(x=alt.X("timestamp:T", title="time"))
    wick = base.mark_rule().encode(y=alt.Y("low:Q", title="price"), y2="high:Q", color=up_down)
    body = base.mark_bar().encode(
        y="open:Q", y2="close:Q", color=up_down,
        tooltip=["timestamp:T", "open:Q", "high:Q", "low:Q", "close:Q"],
    )
    layers = [wick, body]
    if cd.short_ma:
        ma_df = pd.DataFrame([{"timestamp": p.timestamp, "value": p.value} for p in cd.short_ma])
        layers.append(alt.Chart(ma_df).mark_line(color="#ff7f0e").encode(x="timestamp:T", y="value:Q"))
    for yval, color in ((cd.previous_close, "#888888"), (cd.day_high, "#2ca02c"), (cd.day_low, "#9467bd")):
        if yval is not None:
            layers.append(
                alt.Chart(pd.DataFrame({"y": [yval]})).mark_rule(strokeDash=[4, 4], color=color).encode(y="y:Q")
            )
    return alt.layer(*layers).resolve_scale(color="independent").properties(height=380)


def _render_intraday_price(cd: IntradayChartData, view_mode: str) -> None:
    if view_mode == "Candlestick":
        if alt is None:
            st.warning("Candlestick view is unavailable. Showing close line fallback.")
        else:
            try:
                st.altair_chart(_intraday_candlestick_chart(cd), use_container_width=True)
                return
            except Exception as exc:  # noqa: BLE001 - fallback + 원인은 expander
                st.warning("Candlestick view is unavailable. Showing close line fallback.")
                with st.expander("candlestick 렌더 오류 상세"):
                    st.exception(exc)
    st.line_chart(_intraday_price_df(cd))


def _render_intraday_context_metrics(context: IntradayContext) -> None:
    def _fmt(v: object, digits: int = 2) -> str:
        return f"{v:.{digits}f}" if isinstance(v, float) else ("—" if v is None else str(v))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("status", context.status)
    m2.metric("latest_price", _fmt(context.latest_price))
    m3.metric("intraday_return_pct", _fmt(context.intraday_return_pct))
    m4.metric("day_range_position", _fmt(context.day_range_position))
    n1, n2, n3, n4 = st.columns(4)
    n1.metric("cumulative_volume", _fmt(context.cumulative_volume))
    n2.metric("volume_spike", str(context.volume_spike))
    n3.metric("intraday_regime_hint", context.intraday_regime_hint or "—")
    n4.metric("regime_alignment", context.regime_alignment or "—")
    st.caption(
        f"latest_timestamp={context.latest_timestamp} · short_ma_trend={context.short_ma_trend} · "
        f"day_high={context.day_high} · day_low={context.day_low} · previous_close={context.previous_close} · "
        f"confidence_adj={context.confidence_adjustment} · signal_score_adj={context.signal_score_adjustment}"
    )
    if context.risk_notes:
        st.caption("risk_notes: " + " · ".join(context.risk_notes))
    else:
        st.caption("risk_notes: (없음)")


def _intraday_fixture_source(source: str) -> tuple[list | None, float | None]:
    """Sample/Manual 소스 — 버튼으로 candles 로드. (candles, previous_close) 반환."""
    previous_close = st.number_input("previous_close", value=100.0, step=1.0, key="intraday_prev_close")
    manual_raw = None
    if source == "Manual JSON":
        manual_raw = st.text_area("IntradayCandle JSON 리스트", value=_SAMPLE_MANUAL_JSON,
                                  height=180, key="intraday_manual_json")
    if st.button("1D Intraday 생성/로드", key="intraday_build", type="primary"):
        try:
            candles = (_sample_intraday_candles() if source == "Sample fixture"
                       else _parse_manual_candles(manual_raw or ""))
            st.session_state["intraday_candles"] = candles
            st.success(f"IntradayCandle {len(candles)}개 로드 완료.")
        except Exception as exc:  # noqa: BLE001 - QA: 파싱 오류를 화면에 노출
            st.exception(exc)
    candles = st.session_state.get("intraday_candles")
    if not candles:
        st.info("[1D Intraday 생성/로드]를 눌러 sample 또는 manual candles 를 로드하세요.")
        return None, None
    return candles, previous_close


def _intraday_real_kis_source(ticker: str, as_of_dt: datetime) -> tuple[list | None, float | None, dict | None]:
    """Real KIS 소스 — 버튼 클릭 시에만 fetch_minute_ohlcv 호출. (candles, previous_close, fetch_meta)."""
    c1, c2 = st.columns(2)
    with c1:
        limit = st.selectbox("limit", [30, 120, 390], index=1, key="intraday_limit")
    with c2:
        raw_hour = st.text_input("input_hour (HHMMSS, 선택 — 비우면 기본)", value="", key="intraday_input_hour")
    input_hour = raw_hour.strip() or None
    current_sig = f"{ticker}@{as_of_dt.isoformat()}@{input_hour}@{limit}"
    st.caption("real KIS는 [Fetch] 버튼을 눌렀을 때만 호출합니다 — 자동 refresh·WebSocket·polling 없음.")

    if st.button("Fetch real KIS intraday", key="intraday_fetch_real", type="primary"):
        with st.spinner("real KIS 분봉 조회 중..."):
            try:
                result = fetch_minute_ohlcv(ticker, as_of=as_of_dt, input_hour=input_hour, limit=int(limit))
                st.session_state["intraday_real"] = {
                    "candles": result.candles, "previous_close": result.previous_close,
                    "latest_price": result.latest_price, "cumulative_volume": result.cumulative_volume,
                    "cumulative_trading_value": result.cumulative_trading_value, "sig": current_sig,
                }
                if not result.candles:
                    st.warning("빈 candles 응답입니다(장전/장후/휴장/데이터 없음 가능).")
                else:
                    st.success(f"real KIS intraday {len(result.candles)}개 로드.")
            except OutOfScopeTickerError as exc:
                st.error(f"allowlist 밖 종목입니다: {exc}")
            except KisApiError as exc:
                st.error(f"KIS API 오류: {exc}")
            except RuntimeError as exc:  # load_kis_settings — KIS env 누락 등
                st.error(f"KIS 설정/환경 오류(env 누락 가능): {exc}")
            except Exception as exc:  # noqa: BLE001 - QA: 원인 노출(lab은 죽지 않음)
                st.exception(exc)

    stored = st.session_state.get("intraday_real")
    if not stored:
        st.info("[Fetch real KIS intraday]를 눌러 조회하세요.")
        return None, None, None
    if stored["sig"] != current_sig:
        st.warning("조건(ticker/as_of/input_hour/limit)이 바뀌었습니다. 다시 [Fetch] 하세요(재호출 없음).")
    candles = stored["candles"]
    if not candles:
        st.warning("candles 가 비어 1d 차트를 그릴 수 없습니다(빈 응답).")
        return None, None, None
    meta = {k: stored[k] for k in
            ("previous_close", "latest_price", "cumulative_volume", "cumulative_trading_value")}
    return candles, stored["previous_close"], meta


def _render_intraday_fetch_meta(meta: dict, cd: IntradayChartData) -> None:
    """Fetch metadata(IntradayFetchResult) 표시 — candle count·first/last timestamp 포함."""
    ts = [c.timestamp for c in cd.candles]
    st.subheader("Fetch metadata (IntradayFetchResult)")
    st.dataframe(
        pd.DataFrame([{
            "previous_close": meta["previous_close"], "latest_price": meta["latest_price"],
            "cumulative_volume": meta["cumulative_volume"],
            "cumulative_trading_value": meta["cumulative_trading_value"],
            "candle_count": len(ts),
            "first_timestamp": ts[0] if ts else None, "last_timestamp": ts[-1] if ts else None,
        }]),
        use_container_width=True, hide_index=True,
    )


def _render_intraday_qa_section(ticker: str, as_of_dt: datetime) -> None:
    """11. 1D Intraday QA — sample/manual/real KIS 소스로 intraday 순수 로직을 표시."""
    st.header("11. 1D Intraday QA")
    st.caption(
        "intraday 순수 로직(build_intraday_chart_payload / build_intraday_context / "
        "apply_intraday_hint_to_context / apply_intraday_adjustments)을 표시만 합니다(재구현 없음). "
        "Real KIS는 버튼 클릭 시에만 호출 — 자동 refresh·WebSocket·polling 없음. 공식 output.charts 와 별개(period=\"1d\")."
    )
    source = st.radio("데이터 소스", ["Sample fixture", "Manual JSON", "Real KIS intraday"],
                      horizontal=True, key="intraday_source")
    regimes = [r.value for r in Regime]
    final_regime_v = st.selectbox(
        "final_regime (alignment 확인용 · D/W/M 판단 무관)",
        options=regimes, index=regimes.index(Regime.UPTREND_INTACT.value), key="intraday_final_regime",
    )

    fetch_meta = None
    if source == "Real KIS intraday":
        candles, previous_close, fetch_meta = _intraday_real_kis_source(ticker, as_of_dt)
    else:
        candles, previous_close = _intraday_fixture_source(source)
    if not candles:
        return

    # 이미 만든 builder/helper 호출(재구현 없음). final_regime 은 라이브 QA 컨트롤.
    payload = build_intraday_chart_payload(candles, previous_close=previous_close)
    context = build_intraday_context(candles, previous_close=previous_close, as_of=as_of_dt)
    context = apply_intraday_hint_to_context(context, Regime(final_regime_v))
    context = apply_intraday_adjustments(context)  # confidence_adjustment·risk_notes 채움(context 내부만)
    cd = payload.chart_data
    st.caption(
        f"period={payload.period.value} · candle_unit={cd.candle_unit} · candles={len(cd.candles)} · "
        f"short_ma={len(cd.short_ma)} · vwap={len(cd.vwap)}"
    )

    st.subheader("Price / Short MA")
    view_mode = st.radio("Price chart view", ["Candlestick", "Close line"], horizontal=True,
                         key="intraday_view_mode")
    _render_intraday_price(cd, view_mode)
    st.caption(f"previous_close={cd.previous_close} · day_high={cd.day_high} · day_low={cd.day_low}")

    st.subheader("Volume / VWAP")
    st.bar_chart(_intraday_volume_df(cd))
    if context.vwap:  # VWAP은 chart payload가 아니라 context에서 계산됨(build_intraday_context)
        st.markdown("**VWAP** (context 계산값)")
        st.line_chart(_intraday_vwap_df(context.vwap))
    else:
        st.caption("vwap 없음")

    st.subheader("IntradayContext")
    _render_intraday_context_metrics(context)

    st.subheader("Raw")
    st.download_button(
        "1d chart payload JSON 다운로드", data=payload.model_dump_json(indent=2),
        file_name="intraday_1d_payload.json", mime="application/json", key="intraday_dl",
    )
    with st.expander("1d chart payload JSON"):
        st.json(payload.model_dump(mode="json"))
    with st.expander("intraday_context JSON"):
        st.json(context.model_dump(mode="json"))
    with st.expander("candles table"):
        st.dataframe(pd.DataFrame([c.model_dump() for c in cd.candles]),
                     use_container_width=True, hide_index=True)

    if fetch_meta is not None:  # Real KIS 소스일 때만 fetch 메타데이터 표시
        _render_intraday_fetch_meta(fetch_meta, cd)


def main() -> None:
    st.set_page_config(page_title="Technical Agent Lab", layout="wide")
    st.title("기술적 분석 에이전트 — 수동 시각 QA (Streamlit lab)")
    st.caption(
        "real KIS + fake LLM 으로 chart payload·출력 구조를 눈으로 검수하는 개발용 도구입니다. "
        "자동 테스트가 아니며, 아래 session_state 는 production cache 가 아니라 수동 QA용 임시 상태입니다."
    )

    env_ok = _render_env_section()
    ticker, company = _render_ticker_section()
    query, as_of_date, as_of_dt = _render_query_section(company)
    usable_raw = _render_kis_raw_section(ticker, as_of_date, env_ok)
    output = _render_agent_summary_section(
        ticker=ticker, company=company, query=query,
        as_of_dt=as_of_dt, usable_raw=usable_raw,
    )
    # §6~10(D/W/M 차트·JSON)은 유효한 agent 출력이 있을 때만. 없으면 건너뛴다(동작 유지).
    if output is not None:
        chart_selection = _render_chart_section(output)
        _render_raw_json_section(output, chart_selection)

    # §11 1D Intraday QA — 항상 렌더(agent 무관). Real KIS 소스는 버튼 클릭 시에만 호출.
    _render_intraday_qa_section(ticker, as_of_dt)


if __name__ == "__main__":
    main()
