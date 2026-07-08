"""backend 종목 정본 상수 (임시 seed/fallback).

> **런타임 canonical source 는 `stocks` 테이블이다.** 아래 `SUPPORTED_STOCKS` 는 stocks 를 채우는
> **seed 소스이자** stocks 가 비어있는 구간의 fallback 이다. 종목 마스터 정본은 DB `stocks`
> (→ `scripts/seed_stocks.py` 가 이 목록을 읽어 seed)이며, 런타임 종목명 조회는 가능한 한 stocks 를
> 우선한다(서비스 resolve 1순위). 지원 종목이 모두 seed 된 뒤에는 이 상수의 런타임 역할이 사라진다.

**backend 내부 단일 정의:** 종목 목록은 `SUPPORTED_STOCKS` 하나만 둔다. `STOCK_NAMES`(ticker→이름)와
seed 는 모두 이 목록에서 파생/소비한다(중복 정의 금지). AI 의 BATTERY_TICKERS 는 import 하지 않는다.

stock_name 은 종목 마스터이며 클라이언트 입력으로 쉽게 덮이면 안 된다. 해소 우선순위(서비스):
  1) 기존 stocks 이름 유지(마스터 권위) → 2) allowlist(SUPPORTED_STOCKS) → 3) 요청값(미지 종목) → 4) ticker
"""

from __future__ import annotations

# backend 단일 종목 정본(= ai BATTERY_TICKERS 와 1:1). market 은 KOSPI/KOSDAQ.
# stock_code 는 반드시 문자열(앞자리 0 보존).
SUPPORTED_STOCKS: list[dict[str, str]] = [
    {"stock_code": "051910", "stock_name": "LG화학", "market": "KOSPI"},
    {"stock_code": "373220", "stock_name": "LG에너지솔루션", "market": "KOSPI"},
    {"stock_code": "006400", "stock_name": "삼성SDI", "market": "KOSPI"},
    {"stock_code": "096770", "stock_name": "SK이노베이션", "market": "KOSPI"},
    {"stock_code": "086520", "stock_name": "에코프로", "market": "KOSDAQ"},
    {"stock_code": "247540", "stock_name": "에코프로비엠", "market": "KOSDAQ"},
    {"stock_code": "003670", "stock_name": "포스코퓨처엠", "market": "KOSPI"},
    {"stock_code": "066970", "stock_name": "엘앤에프", "market": "KOSPI"},  # 2024 유가증권시장 이전상장
    {"stock_code": "348370", "stock_name": "엔켐", "market": "KOSDAQ"},
    {"stock_code": "361610", "stock_name": "SK아이이테크놀로지", "market": "KOSPI"},
]

# 위 정본에서 파생(ticker → 종목명). 별도 이름 목록을 두지 않는다.
STOCK_NAMES: dict[str, str] = {s["stock_code"]: s["stock_name"] for s in SUPPORTED_STOCKS}


def allowlist_name(ticker: str) -> str | None:
    """allowlist(SUPPORTED_STOCKS)에 있으면 종목명, 없으면 None."""
    return STOCK_NAMES.get(ticker)


# ─────────────────────────────────────────────────────────────────────────────
# 대표 확장 종목 (battery 밖 대형주) — 전체 종목 확장 검증용 canonical seed
# ─────────────────────────────────────────────────────────────────────────────
# ⚠️ `SUPPORTED_STOCKS`(= AI BATTERY 1:1, `allowlist_name` fallback 정본)와 **별개 목록**이다.
# stocks 를 battery 밖 대표 종목으로 넓혀 resolver/supervisor/technical 확장 smoke 를 검증하려는 것.
# `scripts/seed_representative_stocks.py` 가 이 목록을 읽어 seed 한다. 전체 KIS 종목 마스터 승격은 별도
# 운영 단계(`sync_stocks`)로 미룬다 — 이 목록을 무한정 늘리지 않는다(1차 대표 3종).
REPRESENTATIVE_STOCKS: list[dict[str, str]] = [
    {"stock_code": "005930", "stock_name": "삼성전자", "market": "KOSPI"},
    {"stock_code": "005935", "stock_name": "삼성전자우", "market": "KOSPI"},   # 우선주
    {"stock_code": "035720", "stock_name": "카카오", "market": "KOSPI"},
]
