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

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import config
from ..core.signals import COL_FORE, COL_INST, SUBJECTS
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
        rows.append({
            "name": subject,
            "days": c.get("days"),
            "consec_signal": c.get("signal"),
            "ratio": r,
            "strong": strength.get(subject, {}).get("strong"),
            "direction": direction,
            "pct": pct,
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
) -> str:
    """신호·게이트2·메타(+선택적 해석)를 받아 HTML 리포트 문자열을 반환한다.

    render는 표시 전용: interpretation은 '있으면 그대로 그리고 없으면 placeholder'.
    "게이트3 통과분만 넘긴다"는 판정은 그래프가 하고, 여기선 판단·가공하지 않는다.
    """
    rows = _fact_rows(signals)
    context = {
        "meta": meta,
        "market": "KOSPI",                  # M1 고정(삼성전자). 일반화는 M2.
        "gate2": gate2,
        "rows": rows,
        "alignment": signals.get("alignment"),
        "gauge": _gauge(signals),
        "headline": _headline(rows),
        "interpretation": interpretation,   # None이면 템플릿이 placeholder로 후퇴
        "daily": _daily_view(signals),      # None이면 템플릿이 placeholder로 후퇴
        # 임계값 표기는 config 를 '표시'하는 것(재계산 아님).
        "consec_threshold": config.CONSECUTIVE_THRESHOLD,
        "strength_threshold": f"{config.STRENGTH_THRESHOLD * 100:.0f}%",
        "recent_days": config.RECENT_DAYS,
        "trend_days": config.TREND_DAYS,
        "disclaimer": "본 리포트는 투자 자문이 아니며 과거 수급 데이터 기반 참고 자료입니다.",
    }
    template = _env.get_template(_TEMPLATE_NAME)
    return template.render(**context)
