"""기관 세부(inst_detail) — 계산 손검산 + 게이트2 규칙6의 '거짓 차단' 검증.

원리: 규칙 6a(항등식: 세부 7 합 ≈ 기관계)는 데이터가 스스로 보증하는 관계라
  가장 강한 검증이다. 허용오차(±5백만원)가 KIS 반올림은 흡수하되 진짜 훼손은
  잡는지 경계 양쪽을 확인하고, 6b(값 대조)와 주장-원본 불일치 케이스도 겨냥한다.
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

# 세부 7주체 포함 fixture. 손계산: 세부 합 = 10000+8000+5000+2000+3000+1000+1000
# = 30000 = 기관 → 항등식 정확 성립. 5일 동일 행 반복.
_ROW = {
    "개인": -50000, "외국인": 20000, "기관": 30000, "거래대금": 1000000,
    "증권": 10000, "투자신탁": 8000, "사모펀드": 5000, "은행": 2000,
    "보험": 3000, "종금": 1000, "기금": 1000,
}
_df_detail = pd.DataFrame(
    [_ROW] * 5, index=pd.date_range("2026-06-30", periods=5, freq="B", name="날짜")
)


def test_inst_detail_matches_hand_calc():
    """세부 5일 합이 손계산과 일치. 세부 컬럼 없으면 None(주장 안 함)."""
    detail = signals.calc_inst_detail(_df_detail)
    assert detail["증권"] == 50000.0          # 10,000 × 5
    assert detail["기금"] == 5000.0           # 1,000 × 5
    assert len(detail) == 7
    assert signals.calc_inst_detail(df_foreign_5day_streak) is None  # 세부 없음


def test_identity_tolerance_absorbs_rounding_but_catches_tampering():
    """항등식 허용오차: 반올림 수준(±1)은 통과, 진짜 훼손(+50)은 실패."""
    # 반올림 흉내: 기관계를 1백만원 어긋나게 → 허용오차(5) 안 → 통과해야 함
    rounded = _df_detail.copy()
    rounded.loc[rounded.index[0], "기관"] = 30001
    sig_r = signals.compute_signals(rounded)
    result = verify_rules.verify_signals(rounded, sig_r)
    assert not any("항등식" in f for f in result.failures)

    # 진짜 훼손: 세부 하나를 +50 → 항등식 깨짐 → 실패해야 함
    broken = _df_detail.copy()
    broken.loc[broken.index[0], "증권"] = 10050
    sig_b = signals.compute_signals(broken)
    result = verify_rules.verify_signals(broken, sig_b)
    assert result.passed is False
    assert any("항등식" in f for f in result.failures)


def test_verify_catches_tampered_detail_sum():
    """주장된 세부 5일 합을 훼손 → 규칙 6b(값 대조)가 잡는다."""
    tampered = copy.deepcopy(signals.compute_signals(_df_detail))
    tampered["inst_detail"]["기금"] = 99999.0
    result = verify_rules.verify_signals(_df_detail, tampered)
    assert result.passed is False
    assert any("기관 세부 정합" in f and "기금" in f for f in result.failures)


def test_verify_catches_missing_detail_claim():
    """원본에 세부가 있는데 신호에서 inst_detail 을 지움 → 실패."""
    tampered = copy.deepcopy(signals.compute_signals(_df_detail))
    tampered["inst_detail"] = None
    result = verify_rules.verify_signals(_df_detail, tampered)
    assert result.passed is False
    assert any("inst_detail 이 신호에 없음" in f for f in result.failures)


def test_verify_catches_claim_without_source():
    """원본(fixture)에 세부 컬럼이 없는데 세부를 주장 → 실패 (출처 없는 숫자)."""
    tampered = copy.deepcopy(signals.compute_signals(df_foreign_5day_streak))
    assert tampered["inst_detail"] is None                 # 정상은 주장 없음
    tampered["inst_detail"] = {name: 1000.0 for name in signals.INST_DETAIL}
    result = verify_rules.verify_signals(df_foreign_5day_streak, tampered)
    assert result.passed is False
    assert any("세부 컬럼이 없는데" in f for f in result.failures)
