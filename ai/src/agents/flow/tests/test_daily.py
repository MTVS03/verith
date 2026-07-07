"""일별 팩트(daily) — 추출 정확성 + 게이트2 규칙4의 '거짓 차단' 검증.

원리: 게이트2 테스트와 같은 방식 — 정직한 daily 는 통과하고(기존
  test_verify_passes_on_honest_signals 가 이미 커버), 조작된 daily(값 훼손·
  날짜 바꿔치기·행 누락)를 규칙 4 가 잡아내는지 확인한다.
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
    return signals.compute_signals(df_foreign_5day_streak)


def test_daily_extraction_matches_source():
    """추출(직렬화)이 원본 df 를 그대로 옮겼는가 — 손으로 검산 가능한 값으로."""
    daily = _clean_signals()["daily"]
    assert len(daily) == 5                                # fixture 5행 전부
    assert daily[0]["date"] == "2026-06-30"               # date_range 시작일
    assert daily[-1]["외국인"] == 40000.0                  # 마지막 행 그대로
    assert daily[1]["기관"] == -10000.0                    # 중간 행 그대로
    dates = [row["date"] for row in daily]
    assert dates == sorted(dates)                          # 오름차순 유지


def test_verify_catches_tampered_daily_value():
    """일별 값 하나를 훼손 → 규칙 4c(값 정합)가 잡는다."""
    tampered = copy.deepcopy(_clean_signals())
    tampered["daily"][2]["외국인"] = 99999.0               # 원본 40000.0 훼손
    result = verify_rules.verify_signals(df_foreign_5day_streak, tampered)
    assert result.passed is False
    assert any("일별 값" in f for f in result.failures)


def test_verify_catches_swapped_daily_dates():
    """날짜 두 개를 맞바꿈 → 규칙 4b(날짜 정합)가 잡는다."""
    tampered = copy.deepcopy(_clean_signals())
    d = tampered["daily"]
    d[0]["date"], d[1]["date"] = d[1]["date"], d[0]["date"]
    result = verify_rules.verify_signals(df_foreign_5day_streak, tampered)
    assert result.passed is False
    assert any("일별 날짜" in f for f in result.failures)


def test_verify_catches_dropped_daily_row():
    """행 하나를 누락 → 규칙 4a(길이 정합)가 잡는다."""
    tampered = copy.deepcopy(_clean_signals())
    del tampered["daily"][0]
    result = verify_rules.verify_signals(df_foreign_5day_streak, tampered)
    assert result.passed is False
    assert any("일별 길이" in f for f in result.failures)


def test_verify_catches_missing_daily():
    """daily 자체가 없음 → 규칙 4 진입부가 잡는다(구버전 신호 dict 방어)."""
    tampered = copy.deepcopy(_clean_signals())
    del tampered["daily"]
    result = verify_rules.verify_signals(df_foreign_5day_streak, tampered)
    assert result.passed is False
    assert any("daily 가 신호에 없음" in f for f in result.failures)
