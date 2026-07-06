"""render/builder.py — 신호·검증 → HTML 리포트 한 장.

원리: "render는 표시만 한다."
  계산·검증은 signals.py·verify_rules.py가 이미 끝냈다. 여기서는 그 결과를
  받아 사람이 읽을 표로 '그리기만' 한다 — 숫자를 다시 계산하거나 단위를
  바꾸지 않는다(진실은 한 곳). 허용되는 건 표시용 포맷(천단위 콤마·소수 자릿수·
  백분율 등)뿐. 내부 팩트(ratio 등)는 손대지 않는다.

입력:
  signals : compute_signals(df) 결과 dict
  gate2   : verify_signals(df, signals) 결과 GateResult
  meta    : {"stock_name","ticker","base_date"} 표시용 메타
출력:
  HTML 문자열 한 장 (자체 CSS 포함, 외부 링크 없음 — iframe 취합 대비).
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..core.signals import SUBJECTS
from ..schemas import GateResult

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TEMPLATE_NAME = "supply_demand.html"

# Jinja2 환경은 모듈 로드 시 1회 구성(템플릿 디렉터리 고정).
# autoescape: 값에 <, & 등이 섞여도 HTML이 깨지지 않게(표시 안전).
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _fact_rows(signals: dict) -> list[dict]:
    """signals dict → 3주체 팩트 행 리스트(표시용). 값 변형 없음, 재배치만."""
    consecutive = signals.get("consecutive", {})
    strength = signals.get("strength", {})
    rows: list[dict] = []
    for subject in SUBJECTS:            # 개인 → 외국인 → 기관 순서 고정(단일 출처)
        c = consecutive.get(subject, {})
        s = strength.get(subject, {})
        rows.append({
            "name": subject,
            "days": c.get("days"),
            "consec_signal": c.get("signal"),
            "ratio": s.get("ratio"),
            "strong": s.get("strong"),
        })
    return rows


def build_report(signals: dict, gate2: GateResult, meta: dict) -> str:
    """신호·게이트2·메타를 받아 HTML 리포트 문자열을 반환한다.

    render는 표시 전용: signals/gate2가 준 값을 재배치·포맷만 하고 그대로 그린다.
    """
    context = {
        "meta": meta,                       # stock_name, ticker, base_date
        "gate2": gate2,                     # passed / checks / failures (그대로 표시)
        "rows": _fact_rows(signals),        # 3주체 팩트 표
        "alignment": signals.get("alignment"),
        "disclaimer": "본 리포트는 투자 자문이 아니며 과거 수급 데이터 기반 참고 자료입니다.",
    }
    template = _env.get_template(_TEMPLATE_NAME)
    return template.render(**context)
