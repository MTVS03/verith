"""종목코드 → 종목명 allowlist (backend 소유).

AI output 에는 stock_name 이 없고 backend 는 AI 코드를 import 하지 않으므로, backend 가 자체
allowlist 를 관리한다(AI 의 BATTERY_TICKERS 를 import 하지 않는다). 최소 목록으로 시작하고
필요 시 확장한다. 궁극적으로는 stocks 테이블 seed 로 일원화될 수 있다.

stock_name 해소 우선순위(서비스에서 사용):
  1) 요청 body 의 stock_name
  2) 이 allowlist(ticker 조회)
  3) fallback: ticker 문자열 그대로
"""

from __future__ import annotations

# ticker(6자리 문자열) → 종목명. 숫자 키 금지(앞자리 0 보존).
STOCK_NAMES: dict[str, str] = {
    "373220": "LG에너지솔루션",
}


def resolve_stock_name(ticker: str, requested: str | None = None) -> str:
    """stock_name 해소. 요청값 > allowlist > ticker fallback.

    stocks.stock_name 은 NOT NULL 이므로 항상 비어있지 않은 값을 반환한다.
    """
    if requested and requested.strip():
        return requested.strip()
    return STOCK_NAMES.get(ticker, ticker)
