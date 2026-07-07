"""지속성(persistence) — 계산 손검산 + 게이트2 규칙5의 '거짓 차단' 검증.

원리: 블록1(daily)과 같은 방식. 정직한 persistence 는 기존 정상 테스트가
  커버하고, 여기서는 (1) 계산이 손검산과 맞는지, (2) 5일·20일 방향이 다른
  케이스에서 consistent=False 가 나오는지, (3) 조작(합 훼손·판정 뒤집기·키
  삭제)을 규칙 5 가 잡는지 확인한다.
"""

import copy
import sys
from pathlib import Path

import pandas as pd

# 네임스페이스 패키지(PEP 420) — src 를 경로에 넣어 agents.flow.* 를 import.
_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from fixtures import df_foreign_5day_streak  # noqa: E402

from agents.flow.core import signals  # noqa: E402
from agents.flow.core import verify_rules  # noqa: E402


def _clean_signals():
    return signals.compute_signals(df_foreign_5day_streak)


# 10행 fixture — 외국인이 앞 5일 순매도(-100,000), 뒤 5일 순매수(+40,000).
# 손계산: 외국인 sum_5 = +200,000 (양수), sum_20(=10행 전부) = -500,000 + 200,000
#        = -300,000 (음수) → 부호 다름 → consistent False.
# 개인은 10일 내내 -50,000 → sum_5 = -250,000, sum_20 = -500,000 → True.
_df_direction_flip = pd.DataFrame(
    [[-50000, -100000, 10000, 1000000]] * 5 + [[-50000, 40000, 10000, 1000000]] * 5,
    columns=["개인", "외국인", "기관", "거래대금"],
    index=pd.date_range("2026-06-22", periods=10, freq="B", name="날짜"),
)


def test_persistence_matches_hand_calc():
    """5행 fixture: tail(20)=tail(5)라 두 합이 같고, 손계산 값과 일치."""
    p = _clean_signals()["persistence"]
    assert p["외국인"]["sum_5"] == 200000.0        # 40,000 × 5
    assert p["외국인"]["sum_20"] == 200000.0       # 행이 5개뿐이라 동일
    assert p["외국인"]["consistent"] is True
    assert p["개인"]["sum_5"] == -250000.0         # -50,000 × 5
    assert p["개인"]["consistent"] is True         # 둘 다 음수 → 일관
    assert p["기관"]["sum_5"] == 50000.0           # 30-10+20-5+15 (천 단위)


def test_persistence_detects_direction_flip():
    """5일은 순매수인데 20일은 순매도 → consistent False (방향 불일치 탐지)."""
    p = signals.calc_persistence(_df_direction_flip)
    assert p["외국인"]["sum_5"] == 200000.0
    assert p["외국인"]["sum_20"] == -300000.0
    assert p["외국인"]["consistent"] is False      # 부호 다름
    assert p["개인"]["consistent"] is True         # 내내 음수 → 일관


def test_verify_catches_tampered_persistence_sum():
    """sum_5 를 훼손 → 규칙 5(값 대조)가 잡는다."""
    tampered = copy.deepcopy(_clean_signals())
    tampered["persistence"]["외국인"]["sum_5"] = 999999.0
    result = verify_rules.verify_signals(df_foreign_5day_streak, tampered)
    assert result.passed is False
    assert any("지속성 정합" in f and "외국인" in f for f in result.failures)


def test_verify_catches_flipped_consistent_flag():
    """합은 그대로 두고 consistent 만 뒤집음 → 규칙 5(판정 대조)가 잡는다.

    df 유도값의 부호로 판정을 독립 검증하므로, 값이 멀쩡해도 판정 조작이 걸린다.
    """
    tampered = copy.deepcopy(_clean_signals())
    tampered["persistence"]["개인"]["consistent"] = False   # 실제로는 True
    result = verify_rules.verify_signals(df_foreign_5day_streak, tampered)
    assert result.passed is False
    assert any("지속성 판정 정합" in f for f in result.failures)


def test_verify_catches_missing_persistence():
    """persistence 자체가 없음 → 규칙 5 진입부가 잡는다."""
    tampered = copy.deepcopy(_clean_signals())
    del tampered["persistence"]
    result = verify_rules.verify_signals(df_foreign_5day_streak, tampered)
    assert result.passed is False
    assert any("persistence 가 신호에 없음" in f for f in result.failures)
