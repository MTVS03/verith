"""render/builder.py — 신호·검증 → HTML 리포트 한 장.

원리: "render는 표시만 한다."
  계산·검증은 signals.py·verify_rules.py가 이미 끝냈다. 여기서는 그 결과를
  받아 사람이 읽을 화면으로 '그리기만' 한다 — 숫자를 다시 계산하거나 단위를
  바꾸지 않는다(진실은 한 곳). 허용되는 건 표시용 포맷(부호·백분율·막대 폭)과
  이미 있는 값의 재표현(분류·문구 조립)뿐. signals dict는 절대 수정하지 않는다.

입력:
  signals : compute_signals(df) 결과 dict
  gate2   : verify_signals(df, signals) 결과 GateResult
  meta    : {"stock_name","ticker","base_date"} 표시용 메타
  interpretation : 게이트3 통과분만 그래프가 넘김(없으면 None → placeholder)
출력:
  HTML 문자열 한 장 (자체 CSS 포함, 외부 링크 없음 — iframe 취합 대비).
"""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from .. import config
from ..core.signals import COL_FORE, COL_INST, INST_DETAIL, SUBJECTS
from ..schemas import GateResult

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TEMPLATE_NAME = "supply_demand.html"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _fact_rows(signals: dict) -> list[dict]:
    """signals dict → 3주체 표시 행. 값 변형 없음 — 재배치 + 표시용 포맷만.

    direction/pct/bar_w 는 전부 이미 있는 ratio 의 재표현이다:
      direction : ratio 부호 → 매수/매도/중립 (부호를 단어로)
      pct       : ratio 를 %문자열로 (표시 포맷)
      bar_w     : 3주체 |ratio| 중 최대를 50 으로 놓은 상대 막대 폭 (표시 스케일)
    """
    consecutive = signals.get("consecutive", {})
    strength = signals.get("strength", {})
    persistence = signals.get("persistence", {})

    ratios = {
        s: strength.get(s, {}).get("ratio") for s in SUBJECTS
    }
    max_abs = max((abs(r) for r in ratios.values() if r is not None), default=0.0)

    rows: list[dict] = []
    for subject in SUBJECTS:            # 개인 → 외국인 → 기관 순서 고정(단일 출처)
        c = consecutive.get(subject, {})
        r = ratios[subject]
        if r is None:
            direction, pct, bar_w = "중립", "N/A", 0.0
        else:
            direction = "매수" if r > 0 else "매도" if r < 0 else "중립"
            pct = f"{r * 100:+.1f}%"
            bar_w = (abs(r) / max_abs * 50.0) if max_abs else 0.0
        # amt: 강도와 같은 창(RECENT_DAYS)의 순매수 합 — persistence.sum_5 의
        # 재표현(게이트2 규칙5 검증분). 백만원→억원은 ratio→% 와 같은 표시용
        # 단위 재표현(값 자체는 signals 에 백만원 그대로). 없으면 None(구버전 방어).
        v5 = persistence.get(subject, {}).get("sum_5")
        amt = f"{v5 / 100:+,.1f}억원" if v5 is not None else None
        rows.append({
            "name": subject,
            "days": c.get("days"),
            "consec_signal": c.get("signal"),
            "ratio": r,
            "strong": strength.get(subject, {}).get("strong"),
            "direction": direction,
            "pct": pct,
            "amt": amt,
            "bar_w": round(bar_w, 1),
        })
    return rows


def _gauge(signals: dict) -> dict:
    """수급 종합 게이지의 표시용 분류 — 새 계산이 아니라 있는 값의 재표현.

    규칙(단순 고정): 외국인 강도 + 기관 강도 합의 부호.
      양수 → 매수 우위 / 음수 → 매도 우위 / 0 → 중립.
    이미 계산된 두 ratio 를 더해 부호만 보는 것이므로 파생 판정이 아니라
    alignment·강도의 재표현이다. 절대 signals 를 수정하지 않는다.
    """
    strength = signals.get("strength", {})
    fore = strength.get(COL_FORE, {}).get("ratio") or 0.0
    inst = strength.get(COL_INST, {}).get("ratio") or 0.0
    s = fore + inst

    if s > 0:
        return {"verdict": "매수 우위", "color": "#F04452",
                "arc": "M 140 30 A 110 110 0 0 1 237.1 88.4",
                "knob_x": 237.1, "knob_y": 88.4}
    if s < 0:
        return {"verdict": "매도 우위", "color": "#3182F6",
                "arc": "M 42.9 88.4 A 110 110 0 0 1 140 30",
                "knob_x": 42.9, "knob_y": 88.4}
    return {"verdict": "중립", "color": "#8B95A1",
            "arc": None, "knob_x": 140, "knob_y": 30}


def _daily_view(signals: dict) -> list[dict] | None:
    """일별 팩트 → 차트 표시용 뷰. 값 변형 없음 — 표시 스케일·포맷만.

    h 는 기간 내 최대 |값| 을 48%(트랙 반높이 여유분)로 놓은 상대 막대 높이
    — M1 게이지·강도 바와 같은 '표시 스케일' 범주다. 값 텍스트는 천단위
    콤마 포맷뿐, 단위는 팩트 그대로 백만원(변환 없음). daily 가 없으면
    None → 템플릿이 placeholder 로 후퇴(구버전 신호 dict 방어).
    """
    daily = signals.get("daily")
    if not daily:
        return None
    max_abs = max(
        (abs(row.get(s) or 0.0) for row in daily for s in SUBJECTS), default=0.0
    )
    view = []
    for row in daily:
        bars = []
        for s in SUBJECTS:
            v = row.get(s) or 0.0
            bars.append({
                "subject": s,
                "cls": "buy" if v > 0 else "sell",
                "h": round(abs(v) / max_abs * 48.0, 1) if max_abs and v else 0.0,
                "val": f"{v:+,.0f}",
            })
        iso = row.get("date", "")
        view.append({"iso": iso, "label": iso[5:].replace("-", "/"), "bars": bars})
    return view


def _persistence_view(signals: dict) -> dict | None:
    """지속성 팩트 → 표시용 뷰. 값 변형 없음 — 표시 스케일·포맷·문구 조립만.

    막대 폭은 기간 내 최대 |합| 대비 상대 스케일(표시 스케일). verdict 문구는
    persistence 의 검증된 부호·consistent 를 단어로 재표현해 조립할 뿐,
    새 판정을 만들지 않는다(render 는 표시만).
    """
    persistence = signals.get("persistence")
    if not persistence:
        return None
    vals = [
        abs(v) for s in SUBJECTS
        for v in (persistence.get(s, {}).get("sum_5"),
                  persistence.get(s, {}).get("sum_20"))
        if v is not None
    ]
    max_abs = max(vals, default=0.0)
    rows = []
    for s in SUBJECTS:
        p = persistence.get(s, {})
        row = {"name": s, "consistent": bool(p.get("consistent"))}
        for key, out in (("sum_5", "d5"), ("sum_20", "d20")):
            v = p.get(key) or 0.0
            row[out] = {
                "val": f"{v:+,.0f}",
                "cls": "buy" if v > 0 else "sell" if v < 0 else "mut",
                "w": round(abs(v) / max_abs * 100.0, 1) if max_abs else 0.0,
            }
        rows.append(row)
    # verdict: 검증된 부호·consistent 의 재표현(문구 조립만).
    cons_buy = [r["name"] for r in rows if r["consistent"] and r["d20"]["cls"] == "buy"]
    cons_sell = [r["name"] for r in rows if r["consistent"] and r["d20"]["cls"] == "sell"]
    inconsistent = [r["name"] for r in rows if not r["consistent"]]
    parts = []
    if cons_buy:
        parts.append(f"{'·'.join(cons_buy)}은 5일·20일 모두 순매수")
    if cons_sell:
        parts.append(f"{'·'.join(cons_sell)}은 5일·20일 모두 순매도")
    if inconsistent:
        parts.append(f"{'·'.join(inconsistent)}은 5일과 20일 방향이 다름")
    return {"rows": rows, "verdict": " · ".join(parts)}


def _ownership_view(signals: dict) -> dict | None:
    """한도소진율 팩트 → 표시용 뷰. 값 변형 없음 — 표시 스케일·포맷만.

    막대 높이는 min-max 상대 스케일 — 소진율은 하루 0.0x%p로 움직여 절대
    스케일로는 전부 같은 높이가 된다(목업 동일). 바닥 26px를 둬 최솟값도
    막대가 보인다. delta 는 창의 처음↔끝 차이 — 이미 검증된 두 값의 재표현
    (_gauge 가 두 ratio 를 더하는 것과 같은 범주). 없으면 None → placeholder.
    """
    ownership = signals.get("ownership")
    if not ownership:
        return None
    ratios = [row["ratio"] for row in ownership]
    lo, hi = min(ratios), max(ratios)
    span = hi - lo
    bars = []
    for row in ownership:
        iso = row.get("date", "")
        h = 26.0 + (row["ratio"] - lo) / span * 64.0 if span else 55.0
        bars.append({
            "iso": iso,
            "label": iso[5:].replace("-", "/"),   # "07/03" (daily 와 같은 포맷)
            "num": f"{row['ratio']:.2f}",         # KIS 원본이 소수 2자리 — 그대로
            "h": round(h, 1),
        })
    delta = ratios[-1] - ratios[0]
    return {
        "bars": bars,
        "latest": f"{ratios[-1]:.2f}%",
        "delta": f"{delta:+.2f}%p",
        "delta_cls": "buy" if delta > 0 else "sell" if delta < 0 else "mut",
        "delta_arrow": "▲" if delta > 0 else "▼" if delta < 0 else "―",
    }


# 표시용 라벨: KIS 공식명 기본 + 통칭 병기(확인 가능성 — 원본과 같은 이름).
_DETAIL_LABELS = {"기금": "기금(연기금)", "증권": "증권(금융투자)"}
# 목업이 보여주는 5개(검증은 7개 전체, 표시는 이 5개만).
_DETAIL_DISPLAY = ("기금", "증권", "투자신탁", "사모펀드", "보험")


def _inst_detail_view(signals: dict) -> dict | None:
    """기관 세부 팩트 → 표시용 뷰. 값 변형 없음 — 정렬·스케일·라벨만.

    5일 합(검증된 값) 내림차순 정렬로 '주도 주체'를 맨 위에. 막대 폭은 표시
    스케일, leader 문구는 최대값의 재표현일 뿐 새 판정이 아니다.
    """
    detail = signals.get("inst_detail")
    if not detail:
        return None
    shown = [(name, detail.get(name)) for name in _DETAIL_DISPLAY
             if detail.get(name) is not None]
    if not shown:
        return None
    shown.sort(key=lambda kv: kv[1], reverse=True)          # 5일 합 내림차순
    max_abs = max(abs(v) for _, v in shown) or 0.0
    rows = [{
        "label": _DETAIL_LABELS.get(name, name),
        "val": f"{v:+,.0f}",
        "cls": "buy" if v > 0 else "sell" if v < 0 else "mut",
        "w": round(abs(v) / max_abs * 100.0, 1) if max_abs else 0.0,
    } for name, v in shown]
    top_name, top_val = shown[0]
    leader = f"{_DETAIL_LABELS.get(top_name, top_name)} 주도" if top_val > 0 else "세부 전반 순매도"
    return {"rows": rows, "leader": leader}


def _price_table_view(signals: dict) -> list[dict] | None:
    """일자별 시세 팩트 → 날짜별 표(기준점) 뷰. 값 변형 없음 — 표시 포맷·순서만.

    최신이 위(내림차순)는 네이버 등 시세표의 읽기 관행 — 표시 순서 재배치일 뿐
    값은 price_daily(게이트2 규칙8 검증분) 그대로. ▲/▼와 색은 부호의 재표현.
    없으면 None → placeholder 후퇴.
    """
    price = signals.get("price_daily")
    if not price:
        return None
    def _qty(v: float | None) -> dict:
        """순매매량 셀 — 값이 없으면(출처 결손) '—' 로 정직하게 비운다."""
        if v is None:
            return {"txt": "—", "cls": "mut"}
        return {"txt": f"{v:+,.0f}",
                "cls": "buy" if v > 0 else "sell" if v < 0 else "mut"}

    rows = []
    for row in reversed(price):                     # 최신이 위 — 표시 순서만 뒤집음
        chg, rate = row["change"], row["change_rate"]
        chg_cls = "buy" if chg > 0 else "sell" if chg < 0 else "mut"
        rows.append({
            "label": row["date"][5:].replace("-", "/"),   # "07/04" (다른 블록과 동일)
            "close": f"{row['close']:,.0f}",
            "chg": ("▲ " if chg > 0 else "▼ " if chg < 0 else "― ") + f"{abs(chg):,.0f}",
            "chg_cls": chg_cls,
            "rate": f"{rate:+.2f}%",
            "vol": f"{row['volume']:,.0f}",
            "inst": _qty(row.get("inst_qty")),      # 기관 먼저 — 네이버 표 순서
            "fore": _qty(row.get("frgn_qty")),
        })
    return rows


# 해석 강조 마커(**…**) — 프롬프트가 1~2곳만 허용한 볼드 표시.
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _interpretation_html(text: str | None) -> Markup | None:
    """해석의 **강조** 마커 → <b> (표시용 마크업 변환만, 내용 불변).

    본문 전체를 escape 한 뒤 우리 마커만 태그로 바꾼다 — LLM 이 HTML 을
    흘려도 문자 그대로 보이고, 허용되는 마크업은 볼드 하나뿐이다.
    """
    if text is None:
        return None
    return Markup(_BOLD_RE.sub(r"<b>\1</b>", str(escape(text))))


def _header_price(signals: dict) -> dict | None:
    """헤더용 현재가 요약 — price_daily 마지막 행(기준일 종가)의 재표현.

    시세 표와 같은 검증분(게이트2 규칙8)에서 최신 하루만 크게 보여준다.
    값 변형 없음 — 포맷·부호 색만. 없으면 None → 헤더는 종전대로.
    """
    price = signals.get("price_daily")
    if not price:
        return None
    last = price[-1]
    chg, rate = last["change"], last["change_rate"]
    return {
        "close": f"{last['close']:,.0f}",
        "chg": ("▲ " if chg > 0 else "▼ " if chg < 0 else "― ") + f"{abs(chg):,.0f}",
        "rate": f"({rate:+.2f}%)",
        "cls": "buy" if chg > 0 else "sell" if chg < 0 else "mut",
    }


def _headline(rows: list[dict]) -> str:
    """요약 헤드라인 — 각 주체 direction(이미 확정된 부호의 단어)을 문구로 조립.

    표시용 문구 조립일 뿐, 방향 자체는 rows 의 direction 을 그대로 쓴다.
    """
    buyers = [r["name"] for r in rows if r["direction"] == "매수"]
    sellers = [r["name"] for r in rows if r["direction"] == "매도"]
    if buyers and sellers:
        return f"{'·'.join(buyers)}이 사고, {'·'.join(sellers)}이 파는 국면"
    if buyers:
        return f"{'·'.join(buyers)} 매수 국면"
    if sellers:
        return f"{'·'.join(sellers)} 매도 국면"
    return "방향이 뚜렷하지 않은 국면"


def build_report(
    signals: dict,
    gate2: GateResult,
    meta: dict,
    interpretation: str | None = None,
    gate1: GateResult | None = None,   # 게이트1(입력 검증) — None이면 배지 생략(구버전 호환)
) -> str:
    """신호·게이트2·메타(+선택적 해석)를 받아 HTML 리포트 문자열을 반환한다.

    render는 표시 전용: interpretation은 '있으면 그대로 그리고 없으면 placeholder'.
    "게이트3 통과분만 넘긴다"는 판정은 그래프가 하고, 여기선 판단·가공하지 않는다.
    """
    rows = _fact_rows(signals)
    context = {
        "meta": meta,
        "market": meta.get("market"),       # KIS 대표 시장명 원본. None → 템플릿이 칩 생략
        "gate1": gate1,                     # None이면 템플릿이 배지 생략
        "gate2": gate2,
        "rows": rows,
        "alignment": signals.get("alignment"),
        "gauge": _gauge(signals),
        "headline": _headline(rows),
        "interpretation": interpretation,   # None이면 템플릿이 placeholder로 후퇴
        "interpretation_html": _interpretation_html(interpretation),  # **…** → <b>
        "daily": _daily_view(signals),      # None이면 템플릿이 placeholder로 후퇴
        "persistence": _persistence_view(signals),  # None이면 placeholder로 후퇴
        "inst_detail": _inst_detail_view(signals),  # None이면 placeholder로 후퇴
        "ownership": _ownership_view(signals),      # None이면 placeholder로 후퇴
        "price_table": _price_table_view(signals),  # None이면 placeholder로 후퇴
        "price_days": config.PRICE_TABLE_DAYS,
        "header_price": _header_price(signals),     # None이면 헤더는 종전대로
        # 임계값 표기는 config 를 '표시'하는 것(재계산 아님).
        "consec_threshold": config.CONSECUTIVE_THRESHOLD,
        "strength_threshold": f"{config.STRENGTH_THRESHOLD * 100:.0f}%",
        "recent_days": config.RECENT_DAYS,
        "trend_days": config.TREND_DAYS,
        "disclaimer": "본 리포트는 투자 자문이 아니며 과거 수급 데이터 기반 참고 자료입니다.",
    }
    template = _env.get_template(_TEMPLATE_NAME)
    return template.render(**context)
