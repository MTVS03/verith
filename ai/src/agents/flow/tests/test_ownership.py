"""외국인 소진율(ownership) — 직렬화 + 게이트2 규칙7의 '거짓 차단' 검증.

원리: 규칙 7c(교차)는 유일하게 서로 다른 두 API(매매동향 df ↔ 소진율 Series)를
  맞대는 검사다. 단 두 출처는 측정 범위가 다른 물리량(장내 거래대금 vs 전체
  보유주수)이라 방향 불일치는 오염의 증거가 못 된다(장외·시간외·블록딜) —
  그래서 방향 상이는 차단이 아니라 '참고 주석'으로 기록되는지를 검증한다.
  거래일 불일치(같은 달력이어야 함)만 하드 실패다. 7a(범위)·7b(직렬화)와
  비대칭 사다리는 종전대로 '거짓 차단'을 겨냥한다.
"""

import copy
import sys
from pathlib import Path

import pandas as pd

# 네임스페이스 패키지(PEP 420) — src 를 경로에 넣어 agents.flow.* 를 import.
_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agents.flow.core import signals  # noqa: E402
from agents.flow.core import verify_rules  # noqa: E402

# 25거래일 fixture. 외국인은 매일 순매수(+20,000백만원) — 소진율 상승과 정합.
_IDX = pd.date_range("2026-06-01", periods=25, freq="B", name="날짜")
_df = pd.DataFrame(
    {"개인": -50000.0, "외국인": 20000.0, "기관": 30000.0, "거래대금": 1000000.0},
    index=_IDX,
)
# 정합 소진율: 매일 +0.01%p 상승 (46.00 → 46.24). 순매수(+)와 방향 일치.
_own = pd.Series([46.00 + 0.01 * i for i in range(25)], index=_IDX, name="외국인한도소진율")


def test_extract_ownership_serializes_last_5_and_falls_back_to_none():
    """직렬화: 최근 5일만, 오름차순, 값 그대로. 없으면 None(주장 안 함)."""
    claimed = signals.extract_ownership(_own)
    assert len(claimed) == 5
    assert claimed[-1]["date"] == _IDX[-1].date().isoformat()   # 최근이 마지막
    assert claimed[-1]["ratio"] == 46.24                        # 값 무변형
    assert claimed[0]["ratio"] == 46.20
    assert signals.extract_ownership(None) is None
    assert signals.extract_ownership(pd.Series([], dtype=float)) is None


def test_rule7_passes_on_consistent_data():
    """정합 데이터 → 규칙7 세 검사(범위·직렬화·교차) 모두 체크로 통과."""
    result = verify_rules.verify_signals(_df, signals.compute_signals(_df, _own), _own)
    assert result.passed is True
    assert any("소진율 범위" in c for c in result.checks)
    assert any("소진율 직렬화 정합" in c for c in result.checks)
    assert any("교차 정합" in c for c in result.checks)


def test_rule7a_catches_out_of_range():
    """소진율 130% → 지분 비율로 불가능 → 규칙 7a 실패."""
    broken = _own.copy()
    broken.iloc[3] = 130.0
    result = verify_rules.verify_signals(_df, signals.compute_signals(_df, broken), broken)
    assert result.passed is False
    assert any("소진율 범위" in f for f in result.failures)


def test_rule7b_catches_tampered_serialization():
    """주장 배열의 값을 훼손 → 규칙 7b(원본 대조)가 잡는다."""
    tampered = copy.deepcopy(signals.compute_signals(_df, _own))
    tampered["ownership"][-1]["ratio"] = 99.99
    result = verify_rules.verify_signals(_df, tampered, _own)
    assert result.passed is False
    assert any("소진율 직렬화 정합" in f for f in result.failures)


def test_rule7c_notes_direction_disagreement_without_blocking():
    """순매수(+)인데 소진율 하락 → 장내 밖 요인 가능 → 차단 아님, 주석으로 기록."""
    disagreeing = pd.Series(
        [47.00 - 0.05 * i for i in range(25)], index=_IDX, name="외국인한도소진율"
    )
    result = verify_rules.verify_signals(
        _df, signals.compute_signals(_df, disagreeing), disagreeing
    )
    assert result.passed is True                                  # 리포트는 막지 않는다
    assert not any("교차 정합" in f for f in result.failures)
    assert any("방향 상이" in c for c in result.checks)            # 정직한 주석은 남긴다


def test_rule7c_fails_on_calendar_mismatch():
    """소진율에 있는 거래일이 매매동향에 없음 → 두 API 달력 불일치 → 하드 실패."""
    df_missing_day = _df.drop(_IDX[-2])   # 표시 창(최근 5일) 안의 하루를 매매동향에서 제거
    result = verify_rules.verify_signals(
        df_missing_day, signals.compute_signals(df_missing_day, _own), _own
    )
    assert result.passed is False
    assert any("매매동향에 없는 거래일" in f for f in result.failures)


def test_rule7c_tolerates_rounding_wobble():
    """순매수(+)인데 Δ=-0.01%p 하루 — 소수 2자리 반올림 흔들림 → 허용(통과)."""
    wobble = _own.copy()
    wobble.iloc[-2] = wobble.iloc[-3] - 0.01   # 표시 창 안에서 한 번 -0.01
    result = verify_rules.verify_signals(_df, signals.compute_signals(_df, wobble), wobble)
    assert not any("교차 정합" in f for f in result.failures)


def test_rule7_asymmetric_ladder():
    """원본×주장 비대칭 사다리: 없음×없음=정합 / 한쪽만 있으면 실패."""
    # 없음 × 없음 → 정합(주장하지 않으면 표시도 없다)
    result = verify_rules.verify_signals(_df, signals.compute_signals(_df), None)
    assert result.passed is True
    assert any("주장 없음" in c for c in result.checks)

    # 원본 없는데 주장 → 실패 (출처 없는 숫자)
    tampered = copy.deepcopy(signals.compute_signals(_df))
    tampered["ownership"] = [{"date": "2026-07-03", "ratio": 46.72}]
    result = verify_rules.verify_signals(_df, tampered, None)
    assert result.passed is False
    assert any("원본이 없는데" in f for f in result.failures)

    # 원본 있는데 주장 없음 → 실패 (있는 팩트를 누락)
    tampered = copy.deepcopy(signals.compute_signals(_df, _own))
    tampered["ownership"] = None
    result = verify_rules.verify_signals(_df, tampered, _own)
    assert result.passed is False
    assert any("ownership 이 신호에 없음" in f for f in result.failures)
