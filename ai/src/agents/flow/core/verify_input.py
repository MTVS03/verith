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

종목명→티커 해석·정합(2026-07-07): 종목정보 API(CTPF1002R) 권한 대기와
무관하게 KIS 종목 마스터 파일(stock_master.py, 권한 불필요)로 구현.
마스터는 I/O 라 호출부(validate_node)가 로드해 주입한다 — 이 함수는 순수.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .. import config
from . import stock_master
from ..schemas import AgentInput, GateResult

# 6자리 종목코드. 형식 불량은 실전 API 호출 하나를 태우고 알 수 없는 KIS
# 에러로 나타나므로 호출 전에 차단한다 (조각2의 run() 방어를 게이트로 승격).
_TICKER_RE = re.compile(r"\d{6}")
_KST = ZoneInfo("Asia/Seoul")


def verify_input(
    agent_input: AgentInput,
    base_date: date | None,
    now: datetime | None = None,
    master: Mapping[str, str] | None = None,   # {종목명: 티커} — 없으면 해석·정합 생략
) -> tuple[GateResult, date, str | None]:
    """입력을 검증하고 (게이트1 결과, 사용할 base_date, 확정 티커)를 반환한다.

    base_date=None 이면 18시 규칙으로 후보일을 산출한다(자동 — 기본 경로).
    명시된 base_date 는 그대로 쓰되 다음이면 실패:
      - 미래 날짜 (없는 데이터)
      - 오늘인데 18시 전 (장중 미확정 — 실측 ②의 위험을 여기서 차단)
    티커: 없으면 master 로 종목명→티커 해석(실패 시 게이트1 실패). 있으면
      형식 검사 + (master 있을 때) 상장 확인·종목명↔티커 모순 검사 — 모순은
      명백할 때만 잡는다(별칭 입력은 스킵, 게이트3의 '애매하면 통과' 원칙).
    now 는 테스트 주입용. master 는 I/O 경계라 호출부가 주입한다(이 함수는 순수).
    """
    now = now or datetime.now(_KST)
    checks: list[str] = []
    failures: list[str] = []

    # ── 검사 1: 티커 — 해석(이름→코드)·형식·상장·정합 ────
    ticker = agent_input.ticker
    name = " ".join((agent_input.stock_name or "").split())
    if not ticker:
        if master is None:
            failures.append(
                f"티커 해석: 티커가 없고 종목 마스터도 없어 {name!r} 을 해석할 수 없음"
            )
        elif (resolved := stock_master.resolve(master, name)) is None:
            failures.append(
                f"티커 해석: 종목명 {name!r} 을 상장 목록(KOSPI·KOSDAQ)에서 찾지 못함"
                " — 정확한 종목명 또는 6자리 코드가 필요"
            )
        else:
            ticker = resolved
            checks.append(f"티커 해석: {name!r} → {ticker} (KIS 종목 마스터)")

    if ticker and not _TICKER_RE.fullmatch(str(ticker)):
        failures.append(f"티커 형식: 6자리 종목코드가 아님 (받은 값: {ticker!r})")
        ticker = None
    elif ticker and master is not None:
        official = stock_master.name_of(master, str(ticker))
        if official is None:
            failures.append(f"티커 확인: {ticker} 는 상장 목록(KOSPI·KOSDAQ)에 없음")
        elif name and name in master and master[name] != str(ticker):
            # 명백한 모순만 실패 — 이름이 마스터의 '다른 종목'을 정확히 가리킬 때.
            # (마스터에 없는 이름은 별칭·변형일 수 있어 스킵 — 오탐 방지)
            failures.append(
                f"종목명↔티커 모순: {name!r} 은 {master[name]} 인데 티커는 {ticker}"
            )
        else:
            checks.append(f"티커 확인: {ticker} = {official} (KIS 종목 마스터 대조)")
    elif ticker:
        checks.append(f"티커 형식: {ticker} — 6자리 종목코드 (마스터 미로드 — 상장 확인 생략)")

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
    return gate1, base_date, (str(ticker) if ticker else None)
