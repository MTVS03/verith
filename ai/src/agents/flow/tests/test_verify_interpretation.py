"""게이트3 검증 — "팩트와 어긋난 해석을 잡아내는가".

원리: 게이트2 테스트와 같은 방식 — 정상 통과 1건 + 조작 3종 실패로 '거짓 차단'을
  증명한다. 여기에 더해, 규칙 1의 '구간 나누기'가 어순이 꼬인 정상 문장을
  오탐(거짓 양성)하지 않는지까지 확인한다(자연어 검증의 견고성 핵심).
"""

import sys
from pathlib import Path

# 네임스페이스 패키지(PEP 420) — src 를 경로에 넣어 agents.flow.* 를 import.
_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agents.flow.core import signals  # noqa: E402
from agents.flow.core import verify_interpretation as vi  # noqa: E402


def _facts():
    """삼성전자 2026-07-03 실제 구도를 본뜬 팩트 dict:
    개인=순매수(+), 외국인=순매도(-), 기관=순매수(+), 구도=엇갈림(외국인·기관)."""
    return {
        "consecutive": {
            signals.COL_INDI: {"days": 0, "signal": False},
            signals.COL_FORE: {"days": 0, "signal": False},
            signals.COL_INST: {"days": 1, "signal": False},
        },
        "strength": {
            signals.COL_INDI: {"ratio": 0.566, "strong": True},
            signals.COL_FORE: {"ratio": -0.766, "strong": False},
            signals.COL_INST: {"ratio": 0.181, "strong": True},
        },
        "alignment": "엇갈림",
    }


def test_gate3_passes_on_honest_interpretation():
    """세 주체 방향·구도가 모두 팩트와 맞는 정상 해석 → 통과, 실패 사유 없음."""
    text = ("외국인은 순매도 흐름을 보였고 기관은 순매수하며 개인도 매수에 나섰다. "
            "외국인과 기관은 서로 엇갈린 구도다.")
    result = vi.verify_interpretation(text, _facts())
    assert result.gate == 3
    assert result.passed is True
    assert result.failures == []


def test_gate3_catches_flipped_foreign_direction():
    """팩트는 외국인 순매도(-)인데 문장이 외국인을 '매수'로 뒤집음 → 실패(규칙1)."""
    text = "외국인이 매수세를 보이며 적극적으로 사들이고 있다."
    result = vi.verify_interpretation(text, _facts())
    assert result.passed is False
    assert any("방향" in f and "외국인" in f for f in result.failures)


def test_gate3_catches_personal_misattribution():
    """구도(외국인·기관 관계)에 개인을 당사자로 끌어들임 → 실패(규칙3)."""
    text = "개인과 외국인 간에 엇갈린 모습을 보이고 있다."
    result = vi.verify_interpretation(text, _facts())
    assert result.passed is False
    assert any("오귀속" in f for f in result.failures)


def test_gate3_catches_opposite_alignment():
    """팩트는 '엇갈림'인데 문장이 '동반매수'로 서술 → 실패(규칙2)."""
    text = "외국인과 기관은 동반매수 흐름을 이어갔다."
    result = vi.verify_interpretation(text, _facts())
    assert result.passed is False
    assert any("구도 값" in f for f in result.failures)


def test_gate3_no_false_positive_on_complex_word_order():
    """어순 복잡 정상 문장 — 외국인 매도·기관 매수를 뒤섞어 서술.
    규칙1 구간 나누기가 각 주체에 방향을 올바로 귀속해 오탐이 없어야 한다."""
    text = "외국인이 팔았지만 기관이 받아 매수한 하루였다."
    result = vi.verify_interpretation(text, _facts())
    assert result.passed is True, result.failures
    assert result.failures == []
