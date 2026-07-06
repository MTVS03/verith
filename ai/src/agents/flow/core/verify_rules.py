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

    # ── 규칙 4: 일별 배열 정합 ───────────────────────────
    # 대조 원칙: signals.extract_daily 를 다시 부르지 않는다(같은 코드를 재실행하면
    # 같은 버그가 양쪽에 실려 통과한다). 여기서는 df 에서 직접 날짜·값을 읽어
    # daily 가 '주장하는' 내용과 일치하는지만 확인한다.
    daily = signals.get("daily")
    recent_daily = df.tail(config.TREND_DAYS)
    expected_n = len(recent_daily)

    if daily is None:
        failures.append("일별 정합: daily 가 신호에 없음")
    elif len(daily) != expected_n:
        # 4a: 길이 — 행이 사라지거나 부풀지 않았나.
        failures.append(
            f"일별 길이 정합: daily {len(daily)}건이 원본 기준 {expected_n}건과 불일치"
        )
    else:
        checks.append(f"일별 길이 정합: {expected_n}건 일치")

        # 4b: 날짜 — 원본 index(오름차순)와 순서까지 그대로인가.
        expected_dates = [idx.date().isoformat() for idx in recent_daily.index]
        claimed_dates = [row.get("date") for row in daily]
        if claimed_dates != expected_dates:
            failures.append("일별 날짜 정합: daily 날짜열이 원본 index 와 불일치")
        else:
            checks.append("일별 날짜 정합: 날짜열·순서가 원본과 일치")

        # 4c: 값 — 각 날짜·각 주체 값이 원본과 일치하는가 (규칙 4의 본체).
        mismatches = [
            f"{row['date']} {subject}"
            for row, (_, orig) in zip(daily, recent_daily.iterrows())
            for subject in sig.SUBJECTS
            if not math.isclose(
                row.get(subject, float("nan")), float(orig[subject]),
                rel_tol=1e-9, abs_tol=1e-6,
            )
        ]
        if mismatches:
            failures.append(
                f"일별 값 정합: {len(mismatches)}개 셀이 원본과 불일치"
                f" (첫 건: {mismatches[0]})"
            )
        else:
            checks.append(f"일별 값 정합: {expected_n}일 × 3주체 전 셀이 원본과 일치")

        # 4d: 교차 정합 — daily 마지막 RECENT_DAYS 합이, 강도 계산이 쓴
        #     같은 창(recent)의 합과 맞는가. 차트(일별)와 게이지(강도)가
        #     서로 딴소리하는 것을 구조적으로 차단한다.
        window = daily[-len(recent):]
        cross_bad = [
            subject for subject in sig.SUBJECTS
            if not math.isclose(
                sum(row.get(subject, 0.0) for row in window),
                float(recent[subject].sum()),
                rel_tol=1e-9, abs_tol=1e-6,
            )
        ]
        if cross_bad:
            failures.append(
                f"일별-강도 교차 정합: {', '.join(cross_bad)} 의 {len(recent)}일 합이"
                " 강도 계산 창과 불일치"
            )
        else:
            checks.append(f"일별-강도 교차 정합: 3주체 {len(recent)}일 합 일치")

    # ── 규칙 5: 지속성 정합 ───────────────────────────────
    # 대조 원칙: calc_persistence 를 다시 부르지 않고, df 에서 두 창의 합을
    # 독립적으로 구해 주장(sum_5·sum_20)과 대조한다. consistent 는 '주장된
    # 합'이 아니라 df 유도값의 부호로 판정해 비교한다 — 주장으로 주장을
    # 검증하는 순환을 막고, 값뿐 아니라 판정까지 독립 검증한다.
    persistence = signals.get("persistence")
    trend = df.tail(config.TREND_DAYS)
    if persistence is None:
        failures.append("지속성 정합: persistence 가 신호에 없음")
    else:
        for subject in sig.SUBJECTS:
            claim = persistence.get(subject) or {}
            exp5 = float(recent[subject].sum())
            exp20 = float(trend[subject].sum())
            exp_consistent = (exp5 > 0 and exp20 > 0) or (exp5 < 0 and exp20 < 0)
            c5 = claim.get("sum_5")
            c20 = claim.get("sum_20")
            if c5 is None or not math.isclose(c5, exp5, rel_tol=1e-9, abs_tol=1e-6):
                failures.append(
                    f"지속성 정합: {subject} sum_5={c5} 가 원본 대조값 {exp5:.1f} 과 불일치"
                )
            elif c20 is None or not math.isclose(c20, exp20, rel_tol=1e-9, abs_tol=1e-6):
                failures.append(
                    f"지속성 정합: {subject} sum_20={c20} 가 원본 대조값 {exp20:.1f} 과 불일치"
                )
            elif bool(claim.get("consistent")) != exp_consistent:
                failures.append(
                    f"지속성 판정 정합: {subject} consistent={claim.get('consistent')} 가 "
                    f"원본 부호 판정 {exp_consistent} 과 불일치"
                )
            else:
                checks.append(f"지속성 정합: {subject} 5일·20일 합과 일관 판정이 원본과 일치")

    return GateResult(
        gate=2,
        passed=(len(failures) == 0),
        checks=checks,
        failures=failures,
    )
