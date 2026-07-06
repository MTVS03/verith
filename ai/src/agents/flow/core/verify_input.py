"""게이트1 — 입력 검증 + base_date 산출 (수집 전 관문).

원리: 게이트2·3은 실패 시 후퇴(placeholder)라는 출구가 있지만, 게이트1 실패는
만들 리포트 자체가 없다 — 그래서 후퇴가 아니라 명확한 예외로 멈춘다(판정은
그래프의 validate 노드). 통과 시 GateResult 가 검증 카드에 배지로 실린다.

base_date 원리 (2026-07-06 실물 확인, 셋 다 실측):
  ① KIS는 휴장일 요청을 마지막 거래일로 클램프한다 (토요일 요청 → 금요일 행).
  ② 오늘(장중) 요청은 에러가 아니라 미확정 행을 조용히 준다 — M1 메모
     ("TIME LIMIT 에러")는 낡았다. KIS는 안 걸러준다. 우리가 막아야 한다.
  ③ 당일 데이터 확정은 18시 KST (config.DATA_FINALIZED_HOUR_KST).
  그래서 자동 산출: 후보일 = (지금 ≥ 18시) ? 오늘 : 어제. 주말·휴일은 ①이 처리하고,
  실제 확정 거래일은 수집 응답의 마지막 행에서 확정한다(collect_node).

보류(팀 액션 대기): 종목명→티커 해석, stock_name↔ticker 정합 — 종목정보
API(CTPF1002R)가 현재 키 권한으로 막혀 있다(EGW02004). CLAUDE.md 참고.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .. import config
from ..schemas import AgentInput, GateResult

# 6자리 종목코드. 형식 불량은 실전 API 호출 하나를 태우고 알 수 없는 KIS
# 에러로 나타나므로 호출 전에 차단한다 (조각2의 run() 방어를 게이트로 승격).
_TICKER_RE = re.compile(r"\d{6}")
_KST = ZoneInfo("Asia/Seoul")


def verify_input(
    agent_input: AgentInput,
    base_date: date | None,
    now: datetime | None = None,
) -> tuple[GateResult, date]:
    """입력을 검증하고 (게이트1 결과, 사용할 base_date)를 반환한다.

    base_date=None 이면 18시 규칙으로 후보일을 산출한다(자동 — 기본 경로).
    명시된 base_date 는 그대로 쓰되 다음이면 실패:
      - 미래 날짜 (없는 데이터)
      - 오늘인데 18시 전 (장중 미확정 — 실측 ②의 위험을 여기서 차단)
    now 는 테스트 주입용. 기본은 KST 현재 시각(서버 TZ 무관).
    """
    now = now or datetime.now(_KST)
    checks: list[str] = []
    failures: list[str] = []

    # ── 검사 1: 티커 형식 ─────────────────────────────────
    ticker = agent_input.ticker
    if not ticker or not _TICKER_RE.fullmatch(str(ticker)):
        failures.append(f"티커 형식: 6자리 종목코드가 아님 (받은 값: {ticker!r})")
    else:
        checks.append(f"티커 형식: {ticker} — 6자리 종목코드")

    # ── 검사 2: 기준일 — 자동 산출 또는 명시값 검증 ───────
    today = now.date()
    finalized_today = now.hour >= config.DATA_FINALIZED_HOUR_KST
    if base_date is None:
        base_date = today if finalized_today else today - timedelta(days=1)
        checks.append(
            f"기준일 자동 산출: {base_date.isoformat()} "
            f"(18시 규칙 · 휴장일은 KIS가 마지막 거래일로 클램프)"
        )
    elif base_date > today:
        failures.append(f"기준일: {base_date.isoformat()} 는 미래 — 없는 데이터")
    elif base_date == today and not finalized_today:
        failures.append(f"기준일: 오늘({base_date.isoformat()})은 18시 전 — 장중 미확정")
    else:
        checks.append(f"기준일: {base_date.isoformat()} — 확정 범위")

    gate1 = GateResult(gate=1, passed=(len(failures) == 0),
                       checks=checks, failures=failures)
    return gate1, base_date
