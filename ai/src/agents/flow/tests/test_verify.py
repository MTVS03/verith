"""게이트2 검증 — "조작된 팩트를 잡아내는가".

원리: 검증 게이트의 가치는 '정상 통과'가 아니라 '거짓 차단'으로 증명된다.
  그래서 정상 1건 + 조작 3건을 넣고, 조작 케이스는 원본 df 는 그대로 둔 채
  신호 dict 만 훼손해 'df 엔 없는 주장'을 게이트2가 잡아내는지 확인한다.
"""

import copy
import sys
from pathlib import Path

# 네임스페이스 패키지(PEP 420) — src 를 경로에 넣어 agents.flow.* 를 import.
_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from fixtures import df_foreign_5day_streak  # noqa: E402

from agents.flow.core import signals  # noqa: E402
from agents.flow.core import verify_rules  # noqa: E402


def _clean_signals():
    """정상 df 로 실제 계산한, 원본과 정합한 신호 dict."""
    return signals.compute_signals(df_foreign_5day_streak)


def test_verify_passes_on_honest_signals():
    """정상 df + 정직한 signals → 통과, 실패 사유 없음."""
    result = verify_rules.verify_signals(df_foreign_5day_streak, _clean_signals())
    assert result.passed is True
    assert result.failures == []
    assert result.gate == 2


def test_verify_catches_tampered_strength():
    """외국인 강도를 원본과 안 맞는 엉뚱한 값으로 조작 → 실패로 잡힘."""
    tampered = copy.deepcopy(_clean_signals())
    tampered["strength"][signals.COL_FORE]["ratio"] = 0.999  # 원본 대조값 0.20 과 불일치
    result = verify_rules.verify_signals(df_foreign_5day_streak, tampered)
    assert result.passed is False
    assert result.failures  # 사유가 비어있지 않아야
    assert any("강도" in f for f in result.failures)


def test_verify_catches_tampered_alignment():
    """실제 '동반매수'인데 '엇갈림'으로 조작 → 실패로 잡힘."""
    tampered = copy.deepcopy(_clean_signals())
    assert tampered["alignment"] == "동반매수"      # 조작 전 사실 확인
    tampered["alignment"] = "엇갈림"
    result = verify_rules.verify_signals(df_foreign_5day_streak, tampered)
    assert result.passed is False
    assert any("구도" in f for f in result.failures)


def test_verify_catches_inflated_consecutive():
    """행 5개인데 연속일수를 99 로 부풀림 → 물리적으로 불가능, 실패로 잡힘."""
    tampered = copy.deepcopy(_clean_signals())
    tampered["consecutive"][signals.COL_FORE]["days"] = 99
    result = verify_rules.verify_signals(df_foreign_5day_streak, tampered)
    assert result.passed is False
    assert any("연속일수" in f for f in result.failures)
