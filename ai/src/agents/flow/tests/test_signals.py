"""signals.py 검증 — "답을 아는 입력 → 예상 출력 assert".

원리: 계산 계층은 결정론적이므로, 손으로 계산한 기대값과 코드 출력이
  정확히 같아야 한다. fixtures.py의 값은 모두 암산 가능한 정수라
  아래 assert는 곧 "정의대로 구현됐다"는 증명이 된다.
"""

import sys
from pathlib import Path

import pytest

# 이 프로젝트는 __init__.py 없는 네임스페이스 패키지(PEP 420) 구조다.
# 테스트 실행 위치와 무관하게 `agents.flow.*` 를 import 하려면 src 를 경로에 넣는다.
# test_signals.py 위치: .../ai/src/agents/flow/tests/test_signals.py
#   parents[3] == .../ai/src
_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from fixtures import (  # noqa: E402
    df_alignment_cross,
    df_alignment_cross_reverse,
    df_foreign_5day_streak,
    df_foreign_streak_broken,
    df_zero_value,
)

from agents.flow import config  # noqa: E402
from agents.flow.core import signals  # noqa: E402


def test_consecutive_foreign_streak_is_5():
    """외국인 5일 연속 순매수 → days=5, signal=True."""
    result = signals.calc_consecutive(df_foreign_5day_streak)
    fore = result[signals.COL_FORE]
    assert fore["days"] == 5
    assert fore["signal"] is True


def test_strength_foreign_equals_hand_calc():
    """외국인 강도 = 200,000 / 1,000,000 = 0.20, threshold(0.12) 초과 → strong True."""
    result = signals.calc_strength(df_foreign_5day_streak)
    fore = result[signals.COL_FORE]
    assert fore["ratio"] == pytest.approx(0.20)
    assert fore["ratio"] >= config.STRENGTH_THRESHOLD
    assert fore["strong"] is True


def test_alignment_is_dongban_maesu():
    """외국인·기관 둘 다 5일 순매수 → '동반매수'."""
    assert signals.calc_alignment(df_foreign_5day_streak) == "동반매수"


def test_strength_falls_back_to_zero_when_value_is_zero():
    """거래대금 0 → 분모 0 방어. 강도가 크래시 없이 0.0으로 후퇴, strong False."""
    result = signals.calc_strength(df_zero_value)
    fore = result[signals.COL_FORE]
    assert fore["ratio"] == 0.0
    assert fore["strong"] is False


def test_consecutive_stops_when_streak_breaks():
    """최신 2일 순매수 후 직전 날 순매도 → 연속이 그 지점에서 멈춰 days=2."""
    result = signals.calc_consecutive(df_foreign_streak_broken)
    assert result[signals.COL_FORE]["days"] == 2


def test_alignment_cross_is_utgallim():
    """외국인 5일합 +100,000 / 기관 -100,000 → '엇갈림'."""
    assert signals.calc_alignment(df_alignment_cross) == "엇갈림"


def test_alignment_cross_reverse_is_also_utgallim():
    """부호를 뒤집어도(외국인 -100,000 / 기관 +100,000) 동반이 아니면 '엇갈림'."""
    assert signals.calc_alignment(df_alignment_cross_reverse) == "엇갈림"
