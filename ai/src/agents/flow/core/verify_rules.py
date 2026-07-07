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

# 규칙 6a 항등식 허용오차(백만원). KIS 필드별 반올림 관측치 ±1 → 여유 5.
_DETAIL_IDENTITY_TOL = 5.0

# 규칙 7c 반올림 허용(%p). KIS 소진율은 소수 2자리 반올림이라
# 참값 변화가 0 근처일 때 표시값 Δ가 ±0.01 로 흔들릴 수 있다.
_EHRT_ROUND_TOL = 0.01


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


def verify_signals(
    df: pd.DataFrame,
    signals: dict,
    ownership: pd.Series | None = None,   # M2: 소진율 원본(별도 API) — 없으면 규칙7은 "주장 없음" 검사만
) -> GateResult:
    """신호 dict 의 팩트가 원본 df(+소진율 Series)와 정합한지 대조한다."""
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

    # ── 규칙 6: 기관 세부 정합 ────────────────────────────
    # 6a 항등식: 세부 7주체 합 ≈ 기관계 — "우리가 만든 기준"이 아니라 데이터가
    #    스스로 보증하는 관계(실물 확인). KIS 가 필드별 반올림하므로 정확 일치가
    #    아니라 허용오차로 흡수한다(관측 ±1백만원 → 여유 있게 ±5백만원).
    # 6b 값 정합: 주장된 세부 5일 합을 df 에서 독립 합산해 대조(재계산 아닌 대조,
    #    calc_inst_detail 재호출 없음).
    inst_detail = signals.get("inst_detail")
    has_detail_cols = all(name in df.columns for name in sig.INST_DETAIL)
    if not has_detail_cols:
        if inst_detail is None:
            checks.append("기관 세부: 원본에 세부 컬럼 없음 → 주장 없음(정합, 표시도 없음)")
        else:
            failures.append("기관 세부 정합: 원본에 세부 컬럼이 없는데 신호가 세부를 주장")
    elif inst_detail is None:
        failures.append("기관 세부 정합: 원본에 세부가 있는데 inst_detail 이 신호에 없음")
    else:
        window = df.tail(config.RECENT_DAYS)
        # 6a: 일별 항등식 (표시 창과 같은 최근 RECENT_DAYS일)
        bad_days = [
            idx.date().isoformat()
            for idx, row in window.iterrows()
            if not math.isclose(
                sum(float(row[name]) for name in sig.INST_DETAIL),
                float(row[sig.COL_INST]),
                abs_tol=_DETAIL_IDENTITY_TOL,
            )
        ]
        if bad_days:
            failures.append(
                f"기관 세부 항등식: {len(bad_days)}일에서 세부 합≠기관계 (첫 건 {bad_days[0]})"
            )
        else:
            checks.append(
                f"기관 세부 항등식: {len(window)}일 모두 세부 7주체 합 ≈ 기관계"
                f"(±{_DETAIL_IDENTITY_TOL:.0f}백만원, 반올림 흡수)"
            )
        # 6b: 값 정합
        bad_names = [
            name for name in sig.INST_DETAIL
            if inst_detail.get(name) is None or not math.isclose(
                inst_detail[name], float(window[name].sum()),
                rel_tol=1e-9, abs_tol=1e-6,
            )
        ]
        if bad_names:
            failures.append(
                f"기관 세부 정합: {', '.join(bad_names)} 의 5일 합이 원본과 불일치"
            )
        else:
            checks.append(f"기관 세부 정합: 7주체 {len(window)}일 합이 원본과 일치")

    # ── 규칙 7: 외국인 소진율 정합 ────────────────────────
    # 원본이 별도 API(Series)라 df 가 아닌 ownership 과 대조한다.
    # 비대칭 처리(규칙 6과 동일한 사다리): 원본 없음×주장 없음=정합 /
    # 한쪽만 있으면 실패 / 둘 다 있으면 7a~7c 본검사.
    claimed_own = signals.get("ownership")
    if ownership is None or ownership.empty:
        if claimed_own is None:
            checks.append("소진율: 원본 없음 → 주장 없음(정합, 표시도 없음)")
        else:
            failures.append("소진율 정합: 원본이 없는데 신호가 소진율을 주장")
    elif claimed_own is None:
        failures.append("소진율 정합: 원본이 있는데 ownership 이 신호에 없음")
    else:
        # 7a 범위: 소진율은 한도 대비 비율 — 0~100% 밖이면 데이터 자체가 손상.
        out_of_range = ownership[(ownership < 0) | (ownership > 100)]
        if len(out_of_range):
            failures.append(
                f"소진율 범위: {len(out_of_range)}일이 0~100% 밖"
                f" (첫 건 {out_of_range.index[0].date().isoformat()})"
            )
        else:
            checks.append(f"소진율 범위: {len(ownership)}일 모두 0~100% 이내")

        # 7b 직렬화 정합: 주장 배열 ↔ 원본 tail(RECENT_DAYS).
        # extract_ownership 을 재호출하지 않는다(재계산이 아니라 대조).
        recent_own = ownership.tail(config.RECENT_DAYS)
        expected_dates = [idx.date().isoformat() for idx in recent_own.index]
        claimed_dates = [row.get("date") for row in claimed_own]
        claimed_vals = [row.get("ratio") for row in claimed_own]
        if claimed_dates != expected_dates:
            failures.append("소진율 직렬화 정합: 날짜열이 원본과 불일치")
        elif any(
            v is None or not math.isclose(v, float(o), rel_tol=1e-9, abs_tol=1e-6)
            for v, o in zip(claimed_vals, recent_own)
        ):
            failures.append("소진율 직렬화 정합: 값이 원본과 불일치")
        else:
            checks.append(f"소진율 직렬화 정합: {len(recent_own)}일 날짜·값이 원본과 일치")

        # 7c 교차(출처가 다른 두 API 대조) — 판정이 아니라 '주석'이다.
        # 매매동향(장내 거래대금)과 소진율(전체 보유주수)은 측정 범위가 다른
        # 물리량이라, 방향 불일치가 데이터 오염의 증거가 못 된다 — 장외·시간외·
        # 블록딜은 매매동향에 안 잡힌다(하이닉스 2026-07-01 실측: 장내 -114억원
        # vs 보유 Δ+0.04%p ≈ 29만주 ≈ 575억원어치). 그래서 방향 상이는 실패가
        # 아니라 참고로 기록해 리포트에 정직하게 남긴다(라벨 정직성 — SKT 소진율
        # 교훈과 동일). 단 '거래일 자체가 안 맞음'은 두 API 가 같은 달력을 줘야
        # 한다는 진짜 정합 조건이라 실패 유지. Δ=0·±반올림(소수 2자리)은
        # 상이로 세지 않는다. Δ는 원본 Series 에서 직접 계산(7b 로 주장==원본
        # 이 이미 확인됨).
        cross_missing: list[str] = []
        cross_notes: list[str] = []
        for idx in recent_own.index:
            pos = ownership.index.get_loc(idx)
            if pos == 0:
                continue                      # 전일 값 없음 → Δ 계산 불능(검사 생략)
            if idx not in df.index:
                cross_missing.append(idx.date().isoformat())
                continue
            delta = float(ownership.iloc[pos]) - float(ownership.iloc[pos - 1])
            fore = float(df.loc[idx, sig.COL_FORE])
            if (fore > 0 and delta < -_EHRT_ROUND_TOL) or \
               (fore < 0 and delta > _EHRT_ROUND_TOL):
                cross_notes.append(
                    f"{idx.date().isoformat()} (장내 순매수 {fore:+.0f}백만원 vs Δ{delta:+.2f}%p)"
                )
        if cross_missing:
            failures.append(
                f"소진율-순매수 교차 정합: 매매동향에 없는 거래일 "
                f"{len(cross_missing)}건 (첫 건: {cross_missing[0]})"
            )
        elif cross_notes:
            checks.append(
                f"소진율-순매수 교차 정합: {len(cross_notes)}일 방향 상이 — "
                f"장외·시간외 등 장내 밖 요인 가능, 참고 주석 (첫 건: {cross_notes[0]})"
            )
        else:
            checks.append("소진율-순매수 교차 정합: 표시 창 전일에서 방향 모순 없음")

    return GateResult(
        gate=2,
        passed=(len(failures) == 0),
        checks=checks,
        failures=failures,
    )
