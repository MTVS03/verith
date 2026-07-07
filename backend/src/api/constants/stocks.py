"""종목코드 → 종목명 allowlist (backend 소유).

AI output 에는 stock_name 이 없고 backend 는 AI 코드를 import 하지 않으므로, backend 가 자체
allowlist 를 관리한다(AI 의 BATTERY_TICKERS 를 import 하지 않는다). 필요 시 확장하며, 궁극적으로는
stocks 테이블 seed 로 일원화될 수 있다.

stock_name 은 **종목 마스터**이며 클라이언트 입력으로 쉽게 덮이면 안 된다. 해소 우선순위(서비스):
  1) 기존 stocks 에 이름이 있으면 그 값을 유지(마스터 권위)
  2) 이 allowlist(ticker 조회)
  3) 요청 stock_name 은 **미지 종목일 때만** 보조로 사용
  4) 그래도 없으면 ticker fallback
"""

from __future__ import annotations

# ticker(6자리 문자열) → 종목명. 숫자 키 금지(앞자리 0 보존).
STOCK_NAMES: dict[str, str] = {
    "051910": "LG화학",
    "373220": "LG에너지솔루션",
    "006400": "삼성SDI",
    "096770": "SK이노베이션",
    "086520": "에코프로",
    "247540": "에코프로비엠",
    "003670": "포스코퓨처엠",
    "066970": "엘앤에프",
    "348370": "엔켐",
    "361610": "SK아이이테크놀로지",
}


def allowlist_name(ticker: str) -> str | None:
    """allowlist 에 있으면 종목명, 없으면 None."""
    return STOCK_NAMES.get(ticker)
