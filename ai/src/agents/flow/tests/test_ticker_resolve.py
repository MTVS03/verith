"""종목명→티커 해석·정합 (게이트1 확장 + stock_master 파서) — 오프라인 검증.

원리: 티커 확정은 결정론적 사전 lookup — LLM·퍼지 매칭 금지(비슷한 이름을
  잘못 확정하는 것이 미해석보다 나쁘다: 엉뚱한 종목 리포트). 여기서는
  (1) mst 고정폭 파싱이 실물 포맷대로 동작하는지, (2) 해석·상장 확인·
  명백 모순 차단·별칭 스킵의 사다리를 가짜 master 주입으로 검증한다.
  네트워크 0 — 마스터는 dict 로 주입한다(verify_input 은 순수 함수).
"""

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# 네임스페이스 패키지(PEP 420) — src 를 경로에 넣어 agents.flow.* 를 import.
_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agents.flow.core import stock_master  # noqa: E402
from agents.flow.core.verify_input import verify_input  # noqa: E402
from agents.flow.schemas import AgentInput  # noqa: E402

_KST = ZoneInfo("Asia/Seoul")
_NOW = datetime(2026, 7, 6, 19, 0, tzinfo=_KST)
_BD = date(2026, 7, 3)
_MASTER = {"삼성전자": "005930", "SK하이닉스": "000660", "NAVER": "035420"}


def _inp(name, ticker=None):
    return AgentInput(query="", stock_name=name, ticker=ticker)


def _run(name, ticker=None, master=_MASTER):
    return verify_input(_inp(name, ticker), _BD, now=_NOW, master=master)


# ── stock_master 파서 (실물 포맷의 축소판: 코드9 + 표준12 + 이름 + 꼬리) ──
def test_parse_keeps_only_6digit_stocks():
    tail = 20
    lines = [
        "005930   KR7005930003삼성전자" + " " * tail,          # 주식 → 채택
        "F7010002 KR5701000261한투글로벌펀드" + " " * tail,     # 펀드 → 제외
    ]
    parsed = stock_master._parse("\n".join(lines), tail)
    assert parsed == {"삼성전자": "005930"}


def test_resolve_exact_and_case_but_no_fuzzy():
    assert stock_master.resolve(_MASTER, "삼성전자") == "005930"
    assert stock_master.resolve(_MASTER, " 삼성전자 ") == "005930"
    assert stock_master.resolve(_MASTER, "naver") == "035420"   # 영문 대소문자만
    assert stock_master.resolve(_MASTER, "삼성") is None        # 부분 일치 금지
    assert stock_master.name_of(_MASTER, "000660") == "SK하이닉스"
    assert stock_master.name_of(_MASTER, "999999") is None


# ── 게이트1 확장: 해석·상장·모순의 사다리 ──────────────────
def test_resolves_name_to_ticker():
    """티커 없이 종목명만 → 마스터 lookup 으로 확정, 체크에 기록."""
    gate1, _, ticker = _run("SK하이닉스")
    assert gate1.passed is True and ticker == "000660"
    assert any("티커 해석" in c for c in gate1.checks)


def test_unknown_name_fails():
    """마스터에 없는 이름 → 임의 확정 없이 실패(엉뚱한 종목 리포트 차단)."""
    gate1, _, ticker = _run("없는종목")
    assert gate1.passed is False and ticker is None
    assert any("찾지 못함" in f for f in gate1.failures)


def test_unlisted_ticker_fails():
    """형식은 6자리지만 상장 목록에 없는 코드 → 실패."""
    gate1, _, _ = _run("삼성전자", ticker="999999")
    assert gate1.passed is False
    assert any("상장 목록" in f for f in gate1.failures)


def test_name_ticker_contradiction_fails_but_alias_skips():
    """명백 모순(이름이 마스터의 다른 종목)만 실패 — 별칭(마스터에 없음)은 스킵."""
    gate1, _, _ = _run("삼성전자", ticker="000660")     # 삼성전자 ≠ 000660 → 모순
    assert gate1.passed is False
    assert any("모순" in f for f in gate1.failures)

    gate1, _, ticker = _run("하이닉스", ticker="000660")  # 별칭 — 마스터에 없음 → 스킵
    assert gate1.passed is True and ticker == "000660"
    assert any("티커 확인" in c for c in gate1.checks)


def test_no_master_skips_when_ticker_given_fails_when_missing():
    """마스터 없음: 티커 있으면 확인 생략(통과), 없으면 해석 불가(실패)."""
    gate1, _, ticker = _run("삼성전자", ticker="005930", master=None)
    assert gate1.passed is True and ticker == "005930"
    assert any("생략" in c for c in gate1.checks)

    gate1, _, _ = _run("삼성전자", master=None)
    assert gate1.passed is False
