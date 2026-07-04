"""게이트2 — 팩트↔원본 데이터 정합성 대조.

원리: "재계산이 아니라 대조."
  signals.py 를 다시 호출해 비교하면, 같은 버그가 양쪽에 똑같이 반영돼
  틀린 채로 통과한다(검증이 무의미). 그래서 여기서는 signals 를 부르지 않고,
  원본 df 에서 **독립적으로 최소 산술만** 다시 뽑아, 신호 dict 가 주장하는
  값과 일치하는지만 확인한다. 계산의 주인은 signals, 대조의 주인은 여기.

입력:
  df      : 원본 수급 DataFrame (signals.py 와 같은 스키마)
  signals : compute_signals(df) 가 낸 신호 dict
출력:
  GateResult(gate=2, passed, checks, failures)
"""

from __future__ import annotations

import math

import pandas as pd

from . import signals as sig
from .. import config
from ..schemas import GateResult


def _alignment_from_df(df: pd.DataFrame) -> str:
    """원본 df 에서 구도를 독립 판정(대조용). signals.calc_alignment 와
    같은 정의를 쓰되, 검증은 '같은 정의로 다시 재현되는가'를 보는 것이므로
    의도적으로 같은 규칙을 적용한다(입력이 df 하나뿐이라 우회 불가)."""
    recent = df.tail(config.RECENT_DAYS)
    fore = recent[sig.COL_FORE].sum()
    inst = recent[sig.COL_INST].sum()
    if fore > 0 and inst > 0:
        return "동반매수"
    if fore < 0 and inst < 0:
        return "동반매도"
    return "엇갈림"


def verify_signals(df: pd.DataFrame, signals: dict) -> GateResult:
    """신호 dict 의 팩트가 원본 df 와 정합한지 대조한다."""
    checks: list[str] = []
    failures: list[str] = []

    n_rows = len(df)
    recent = df.tail(config.RECENT_DAYS)
    avg_value = recent[sig.COL_VALUE].mean()

    # ── 규칙 1: 강도 정합 ────────────────────────────────
    strength = signals.get("strength", {})
    for subject in sig.SUBJECTS:
        claimed = strength.get(subject, {}).get("ratio")
        net_sum = recent[subject].sum()
        if not avg_value or pd.isna(avg_value):
            expected = 0.0                      # signals 의 분모 0 후퇴 계약과 동일
        else:
            expected = float(net_sum) / float(avg_value)

        if claimed is None:
            failures.append(f"강도 정합: {subject} ratio 가 신호에 없음")
        elif math.isclose(claimed, expected, rel_tol=1e-6, abs_tol=1e-9):
            checks.append(f"강도 정합: {subject} ratio={claimed:.6f} 가 원본 대조와 일치")
        else:
            failures.append(
                f"강도 정합: {subject} ratio={claimed} 이(가) 원본 대조값 {expected:.6f} 과 불일치"
            )

    # ── 규칙 2: 연속일수 범위 ────────────────────────────
    consecutive = signals.get("consecutive", {})
    for subject in sig.SUBJECTS:
        days = consecutive.get(subject, {}).get("days")
        if days is None:
            failures.append(f"연속일수 범위: {subject} days 가 신호에 없음")
        elif days > n_rows:
            failures.append(
                f"연속일수 범위: {subject} days={days} 가 데이터 행 수 {n_rows} 를 초과(불가능)"
            )
        else:
            checks.append(f"연속일수 범위: {subject} days={days} 가 행 수 {n_rows} 이내")

    # ── 규칙 3: 구도 부호 정합 ───────────────────────────
    claimed_alignment = signals.get("alignment")
    expected_alignment = _alignment_from_df(df)
    if claimed_alignment is None:
        failures.append("구도 부호 정합: alignment 가 신호에 없음")
    elif claimed_alignment == expected_alignment:
        checks.append(f"구도 부호 정합: alignment='{claimed_alignment}' 가 원본 부호와 일치")
    else:
        failures.append(
            f"구도 부호 정합: alignment='{claimed_alignment}' 가 "
            f"원본 부호 판정 '{expected_alignment}' 과 불일치"
        )

    return GateResult(
        gate=2,
        passed=(len(failures) == 0),
        checks=checks,
        failures=failures,
    )
