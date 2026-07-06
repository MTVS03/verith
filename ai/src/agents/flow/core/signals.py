"""수급 신호 계산 — 순수 함수 계층.

원리: "숫자는 코드가 결정론적으로 정한다." (CLAUDE.md 핵심 원칙)
  이 파일에는 pykrx·LLM·네트워크 같은 외부 의존이 없다. 입력은 pandas DataFrame,
  출력은 계산된 신호 dict뿐. 외부 의존이 없어야 테스트가 빠르고, 결과가 항상
  같은 입력 → 같은 출력(결정론)이 된다. 검증 게이트가 믿을 수 있는 "팩트"는
  바로 이 계층에서 나온다.

기대하는 입력 DataFrame 스키마
  - index: 날짜. **오름차순**(과거 → 최신). 즉 가장 최근 날짜가 마지막 행.
  - 컬럼:
      개인   : 개인 일별 순매수 (원)      — 양수=순매수, 음수=순매도
      외국인 : 외국인 일별 순매수 (원)
      기관   : 기관 일별 순매수 (원)
      거래대금: 그 날 종목의 **총** 거래대금 (원)  — 3주체 공용(종목 규모 지표)
  '거래대금'을 주체별이 아니라 종목 총액으로 두는 이유: 순매수 강도는
  "종목 규모 대비 얼마나 샀나"를 보려는 것이므로 분모가 종목 전체 거래대금이어야
  주체 간·종목 간 비교가 가능해진다.
"""

from __future__ import annotations

import pandas as pd

from .. import config

# ── DataFrame 컬럼 이름 (스키마 상수) ────────────────────────
# 매직 스트링을 코드에 흩뿌리지 않기 위해 한 곳에 모은다.
COL_INDI: str = "개인"
COL_FORE: str = "외국인"
COL_INST: str = "기관"
COL_VALUE: str = "거래대금"

# 순매수 주체 3인. 반복 계산에서 이 리스트를 돌린다.
SUBJECTS: tuple[str, ...] = (COL_INDI, COL_FORE, COL_INST)


def consecutive_net_buy_days(net: pd.Series) -> int:
    """가장 최근 날짜부터 과거로 거꾸로 세어, 순매수(net > 0)가 끊기지 않고
    이어진 일수를 반환한다. 순매수가 아닌 날(net <= 0)을 만나면 즉시 멈춘다.

    원리: "지금 진행 중인 흐름"을 보려는 것이므로 최신부터 거꾸로 센다.
      과거의 연속 매수는 이미 끝난 이야기고, 오늘로 이어지는 연속만이
      "매집이 진행 중"이라는 신호다. 그래서 reversed 순회 + 첫 비매수에서 break.
    """
    days = 0
    # index 오름차순 → 뒤에서부터(reversed)가 최신 → 과거 방향.
    for value in reversed(net.tolist()):
        if value > 0:
            days += 1
        else:
            break
    return days


def calc_consecutive(df: pd.DataFrame) -> dict[str, dict[str, object]]:
    """3주체 각각의 연속 순매수 일수와 신호 플래그.

    signal = (연속 일수 >= config.CONSECUTIVE_THRESHOLD).
    3일 미만은 노이즈로 간주(하루 반짝 매수와 의도적 매집을 가르는 문턱).
    """
    result: dict[str, dict[str, object]] = {}
    for subject in SUBJECTS:
        days = consecutive_net_buy_days(df[subject])
        result[subject] = {
            "days": days,
            "signal": days >= config.CONSECUTIVE_THRESHOLD,
        }
    return result


def calc_strength(df: pd.DataFrame) -> dict[str, dict[str, object]]:
    """3주체 각각의 순매수 강도와 강한 매수 플래그.

    강도 = 최근 RECENT_DAYS일 순매수 합 / 최근 RECENT_DAYS일 평균 거래대금.
    strong = (강도 >= config.STRENGTH_THRESHOLD).

    원리: 절대 금액은 큰 종목일수록 무조건 커 보인다. 종목 총 거래대금으로
      나눠 비율로 봐야 규모가 다른 종목·주체를 같은 잣대로 비교할 수 있다.
    """
    recent = df.tail(config.RECENT_DAYS)
    avg_value = recent[COL_VALUE].mean()

    result: dict[str, dict[str, object]] = {}
    for subject in SUBJECTS:
        net_sum = recent[subject].sum()
        # 분모 0/NaN 방어: 거래대금이 0이면 비율이 정의되지 않으므로 0.0으로 후퇴.
        if not avg_value or pd.isna(avg_value):
            ratio = 0.0
        else:
            ratio = float(net_sum) / float(avg_value)
        result[subject] = {
            "ratio": ratio,
            "strong": ratio >= config.STRENGTH_THRESHOLD,
        }
    return result


def calc_alignment(df: pd.DataFrame) -> str:
    """외국인·기관 두 큰손의 최근 RECENT_DAYS일 구도.

    반환: "동반매수" | "동반매도" | "엇갈림"
      - 둘 다 5일 순매수 합 > 0  → 동반매수
      - 둘 다 5일 순매수 합 < 0  → 동반매도
      - 그 외(부호 불일치·0 포함) → 엇갈림

    원리: 두 큰손이 같은 방향이면 신호가 강해지고, 엇갈리면 해석이 조심스러워진다.
      이 구도가 뒤 해석 단계의 톤을 좌우하므로 여기서 결정론적으로 확정해 둔다.
      5일 '합'의 부호를 쓰는 이유: 강도 계산과 같은 창(RECENT_DAYS)·같은 집계(합)를
      써야 신호들 사이에 기준이 어긋나지 않는다.
    """
    recent = df.tail(config.RECENT_DAYS)
    fore_sum = recent[COL_FORE].sum()
    inst_sum = recent[COL_INST].sum()

    if fore_sum > 0 and inst_sum > 0:
        return "동반매수"
    if fore_sum < 0 and inst_sum < 0:
        return "동반매도"
    return "엇갈림"


def extract_daily(df: pd.DataFrame) -> list[dict]:
    """최근 TREND_DAYS일의 일별 순매수 팩트 목록 (오름차순, 최근이 마지막).

    원리: 계산이 아니라 "있는 값의 직렬화".
      df 의 행을 dict 목록으로 옮겨 담을 뿐, 어떤 값도 만들거나 바꾸지 않는다
      (단위도 df 그대로 백만원). 일별 차트가 쓸 팩트를 signals dict(검증된
      팩트 컨테이너)에 실어 보내기 위한 것 — 이 배열도 게이트2 규칙 4 가
      원본 df 와 대조한다. 거래대금은 차트가 안 쓰므로 싣지 않는다(컨테이너
      최소주의: 표시할 팩트만).
    """
    recent = df.tail(config.TREND_DAYS)
    return [
        {
            "date": idx.date().isoformat(),
            **{subject: float(row[subject]) for subject in SUBJECTS},
        }
        for idx, row in recent.iterrows()
    ]


def compute_signals(df: pd.DataFrame) -> dict[str, object]:
    """세 계산을 묶어 하나의 신호 dict로 반환한다.

    이 dict가 다음 계층(검증 게이트 → 해석)으로 넘어가는 "검증된 팩트"의 원천이다.
    """
    return {
        "consecutive": calc_consecutive(df),
        "strength": calc_strength(df),
        "alignment": calc_alignment(df),
        "daily": extract_daily(df),          # M2: 일별 순매수 팩트(차트용)
    }
