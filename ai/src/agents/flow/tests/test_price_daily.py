"""일자별 시세(price_daily) — 직렬화 + 게이트2 규칙8의 '거짓 차단' 검증.

원리: 규칙 8의 핵심은 8b 항등식이다. 종가·전일비·등락률은 같은 행 안에서
  산술로 맞물리는 같은 출처의 값이라(전일비=종가차, 등락률=전일비÷전일종가),
  깨지면 데이터 손상이 확실해 하드 실패가 정당하다 — 다른 출처끼리의 방향
  비교라 주석으로 강등된 7c와 대비되는 지점. 8a(직렬화)·8c(매매동향 달력
  교차)와 비대칭 사다리(규칙 6·7과 동일)도 겨냥한다.
"""

import copy
import sys
from pathlib import Path

import pandas as pd

# 네임스페이스 패키지(PEP 420) — src 를 경로에 넣어 agents.flow.* 를 import.
_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agents.flow import config  # noqa: E402
from agents.flow.core import signals  # noqa: E402
from agents.flow.core import verify_rules  # noqa: E402

# 25거래일 공용 달력 — 매매동향 df 와 시세 quotes 가 같은 달력을 쓴다(8c 전제).
# df 에는 순매매량(주) 2컬럼 포함 — 표의 수량 필드는 매매동향이 출처다.
_IDX = pd.date_range("2026-06-01", periods=25, freq="B", name="날짜")
_df = pd.DataFrame(
    {"개인": -50000.0, "외국인": 20000.0, "기관": 30000.0, "거래대금": 1000000.0,
     signals.COL_FORE_QTY: 700.0, signals.COL_INST_QTY: -300.0},
    index=_IDX,
)


def _make_quotes() -> pd.DataFrame:
    """항등식이 성립하는 정합 시세: 종가 100,000원에서 매일 +1,000원.

    전일비·등락률은 손으로 같은 산술을 적용해 만든다(첫 행 전일비는 원본에
    전일이 없어 검사 대상 밖 — 임의값 0). 거래량은 자유값.
    """
    rows = []
    prev = None
    for i in range(25):
        close = 100000.0 + 1000.0 * i
        change = 0.0 if prev is None else close - prev
        rate = 0.0 if prev is None else round(change / prev * 100.0, 2)
        rows.append([close, change, rate, 500000.0 + i])
        prev = close
    return pd.DataFrame(rows, index=_IDX, columns=list(signals.QUOTE_COLS))


_quotes = _make_quotes()


def test_extract_price_daily_serializes_window_and_falls_back_to_none():
    """직렬화: 최근 PRICE_TABLE_DAYS일만, 오름차순, 값 그대로. 없으면 None.

    수량 2필드는 매매동향 df 가 출처 — df 에 컬럼이 없으면 None(주장 안 함)."""
    claimed = signals.extract_price_daily(_quotes, _df)
    assert len(claimed) == config.PRICE_TABLE_DAYS
    assert claimed[-1]["date"] == _IDX[-1].date().isoformat()   # 최근이 마지막
    assert claimed[-1]["close"] == 124000.0                     # 값 무변형
    assert claimed[-1]["frgn_qty"] == 700.0                     # 매매동향 출처
    assert claimed[-1]["inst_qty"] == -300.0
    assert signals.extract_price_daily(None, _df) is None
    assert signals.extract_price_daily(pd.DataFrame(), _df) is None
    # df 에 수량 컬럼이 없으면 해당 필드만 None (시세 4필드는 그대로).
    no_qty = signals.extract_price_daily(_quotes, _df[["개인", "외국인", "기관", "거래대금"]])
    assert no_qty[-1]["frgn_qty"] is None and no_qty[-1]["close"] == 124000.0


def test_rule8_passes_on_consistent_data():
    """정합 데이터 → 규칙8 세 검사(직렬화·항등식·달력 교차) 모두 체크로 통과."""
    result = verify_rules.verify_signals(
        _df, signals.compute_signals(_df, quotes=_quotes), quotes=_quotes
    )
    assert result.passed is True
    assert any("시세 직렬화 정합" in c for c in result.checks)
    assert any("시세 항등식" in c for c in result.checks)
    assert any("시세-매매동향 교차 정합" in c for c in result.checks)


def test_rule8a_catches_tampered_serialization():
    """주장 배열의 종가를 훼손 → 규칙 8a(원본 대조)가 잡는다."""
    tampered = copy.deepcopy(signals.compute_signals(_df, quotes=_quotes))
    tampered["price_daily"][-1]["close"] = 999999.0
    result = verify_rules.verify_signals(_df, tampered, quotes=_quotes)
    assert result.passed is False
    assert any("시세 직렬화 정합" in f for f in result.failures)


def test_rule8a_catches_tampered_qty_and_sourceless_qty():
    """수량 필드의 두 거짓: 값 훼손(원본과 불일치)과 출처 없는 주장 — 둘 다 8a가 잡는다."""
    # 훼손: 기관 순매매량을 조작
    tampered = copy.deepcopy(signals.compute_signals(_df, quotes=_quotes))
    tampered["price_daily"][-1]["inst_qty"] = 12345.0
    result = verify_rules.verify_signals(_df, tampered, quotes=_quotes)
    assert result.passed is False
    assert any("순매매량" in f for f in result.failures)

    # 출처 없는 주장: df 에 수량 컬럼이 없는데 주장 배열엔 값이 있음
    df_no_qty = _df[["개인", "외국인", "기관", "거래대금"]]
    sourceless = copy.deepcopy(signals.compute_signals(df_no_qty, quotes=_quotes))
    sourceless["price_daily"][-1]["frgn_qty"] = 700.0
    result = verify_rules.verify_signals(df_no_qty, sourceless, quotes=_quotes)
    assert result.passed is False
    assert any("순매매량" in f for f in result.failures)


def test_rule8b_catches_broken_identity():
    """원본의 전일비가 종가차와 어긋남 → 같은 출처 내부 모순 → 규칙 8b 실패.

    직렬화(주장=원본)는 통과하는 손상이라 8a 로는 못 잡는다 — 8b 가 잡아야 한다.
    """
    broken = _quotes.copy()
    broken.iloc[-2, broken.columns.get_loc(signals.COL_CHANGE)] = 77777.0
    result = verify_rules.verify_signals(
        _df, signals.compute_signals(_df, quotes=broken), quotes=broken
    )
    assert result.passed is False
    assert any("시세 항등식" in f for f in result.failures)


def test_rule8c_catches_calendar_mismatch():
    """시세 달력이 매매동향과 다름(하루 어긋남) → 두 수집이 어긋남 → 규칙 8c 실패."""
    shifted_idx = _IDX[:-1].append(pd.DatetimeIndex([_IDX[-1] + pd.Timedelta(days=1)]))
    shifted = _quotes.copy()
    shifted.index = shifted_idx
    result = verify_rules.verify_signals(
        _df, signals.compute_signals(_df, quotes=shifted), quotes=shifted
    )
    assert result.passed is False
    assert any("시세-매매동향 교차 정합" in f for f in result.failures)


def test_rule8_asymmetric_ladder():
    """원본×주장 비대칭 사다리: 없음×없음=정합 / 한쪽만 있으면 실패."""
    # 없음 × 없음 → 정합(주장하지 않으면 표시도 없다)
    result = verify_rules.verify_signals(_df, signals.compute_signals(_df))
    assert result.passed is True
    assert any("시세: 원본 없음" in c for c in result.checks)

    # 원본 없는데 주장 → 실패 (출처 없는 숫자)
    tampered = copy.deepcopy(signals.compute_signals(_df))
    tampered["price_daily"] = [{"date": "2026-07-03", "close": 100000.0}]
    result = verify_rules.verify_signals(_df, tampered)
    assert result.passed is False
    assert any("원본이 없는데" in f for f in result.failures)

    # 원본 있는데 주장 없음 → 실패 (있는 팩트를 누락)
    tampered = copy.deepcopy(signals.compute_signals(_df, quotes=_quotes))
    tampered["price_daily"] = None
    result = verify_rules.verify_signals(_df, tampered, quotes=_quotes)
    assert result.passed is False
    assert any("price_daily 가 신호에 없음" in f for f in result.failures)
