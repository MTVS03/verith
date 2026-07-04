"""KIS 국내주식기간별시세 client.

책임(technical_coding_guidelines §4.1): KIS 호출·재시도·원본 응답 수신과, 원본 `output2`를
내부 표준 OHLCV(`schemas/ohlcv.py`)로 변환하는 것까지. regime 판정·LLM·DB·Redis는 하지 않는다.

정본:
  - 요청 스펙·필드 매핑: `docs/kis_mapping.md` (§4·§5·§7, 실측 §11)
  - 설정값(period·재시도·timeout·allowlist): `config.py` (하드코딩 금지, §2.1)

이번 단계 범위: D/W/M **단일 호출** + 변환 + 검증. 100건 초과 구간 분할·병합, Redis 폴백은
후속 단계(§11.4는 분할 필요를 기록만 함).
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

import httpx

from ..config import (
    KIS_BACKOFF_SECONDS,
    KIS_MAX_RETRIES,
    KIS_PERIOD_DAILY,
    KIS_PERIOD_MONTHLY,
    KIS_PERIOD_WEEKLY,
    KIS_TIMEOUT_SECONDS,
    KISSettings,
    is_allowed_ticker,
    load_kis_settings,
)
from ..schemas.ohlcv import OHLCV

logger = logging.getLogger(__name__)

# ── KIS API 스펙 (kis_mapping §4·§5·§11.1) ────────────────────────────────────
TOKEN_PATH = "/oauth2/tokenP"
CHART_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
TR_ID = "FHKST03010100"
MARKET_DIV_CODE = "J"  # FID_COND_MRKT_DIV_CODE — KRX
ORG_ADJ_PRC = "0"      # FID_ORG_ADJ_PRC — 수정주가
CUST_TYPE = "P"        # 개인
RATE_LIMIT_MSG_CODE = "EGW00201"  # "초당 거래건수 초과" — 재시도 대상 (kis_mapping §11.7)

ALLOWED_PERIODS = (KIS_PERIOD_DAILY, KIS_PERIOD_WEEKLY, KIS_PERIOD_MONTHLY)

# ── KIS output2 원본 필드명 → 내부 OHLCV (kis_mapping §7·§11.3 실측 정본) ──────
# 실측으로 고정한 필드명만 사용한다. 여러 축약형을 추측해 넓게 받지 않는다.
KIS_FIELD_DATE = "stck_bsop_date"
KIS_FIELD_OPEN = "stck_oprc"
KIS_FIELD_HIGH = "stck_hgpr"
KIS_FIELD_LOW = "stck_lwpr"
KIS_FIELD_CLOSE = "stck_clpr"
KIS_FIELD_VOLUME = "acml_vol"
KIS_FIELD_TRADING_VALUE = "acml_tr_pbmn"
REQUIRED_KIS_FIELDS = (
    KIS_FIELD_DATE, KIS_FIELD_OPEN, KIS_FIELD_HIGH, KIS_FIELD_LOW,
    KIS_FIELD_CLOSE, KIS_FIELD_VOLUME, KIS_FIELD_TRADING_VALUE,
)

# 단일 호출 조회 창(달력일). §11.4 실측 기준: D 100건≈5개월, W/M은 100건 미만.
_LOOKBACK_DAYS_DAILY = 480
_LOOKBACK_DAYS_WEEKLY_MONTHLY = 365 * 5


# ─────────────────────────────────────────────────────────────────────────────
# 예외 (client 내부 전용. FastAPI/OUT_OF_SCOPE_TICKER 응답 포맷은 이 단계 범위 아님)
# ─────────────────────────────────────────────────────────────────────────────
class KisError(Exception):
    """KIS client 공통 베이스 예외."""


class OutOfScopeTickerError(KisError):
    """MVP allowlist(2차전지 10종목) 밖 종목."""


class InvalidPeriodError(KisError):
    """지원하지 않는 period (D/W/M 외)."""


class KisFieldError(KisError):
    """KIS 응답 필수 필드 누락·숫자 변환 실패."""


class KisApiError(KisError):
    """KIS API 오류(rt_cd≠0·HTTP 오류·재시도 초과)."""


# ─────────────────────────────────────────────────────────────────────────────
# 입력 검증
# ─────────────────────────────────────────────────────────────────────────────
def validate_ticker(ticker: str) -> None:
    """allowlist 밖 종목이면 KIS 호출 없이 즉시 실패(config.is_allowed_ticker 사용)."""
    if not is_allowed_ticker(ticker):
        raise OutOfScopeTickerError(f"MVP 조사 범위 밖 종목입니다: {ticker!r}")


def validate_period(period: str) -> None:
    """허용 period는 config의 KIS_PERIOD_DAILY/WEEKLY/MONTHLY(D/W/M) 뿐."""
    if period not in ALLOWED_PERIODS:
        raise InvalidPeriodError(
            f"지원하지 않는 period: {period!r}. 허용: {ALLOWED_PERIODS}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 값 변환 헬퍼 — KIS는 OHLCV 값을 전부 문자열로 반환(kis_mapping §11.3)
# ─────────────────────────────────────────────────────────────────────────────
def _to_iso_date(raw: object, field: str = KIS_FIELD_DATE) -> str:
    """KIS 원본 'YYYYMMDD' → 내부 표준 ISO 'YYYY-MM-DD'."""
    text = str(raw).strip()
    if len(text) != 8 or not text.isdigit():
        raise KisFieldError(f"날짜 형식 오류 ({field}={raw!r}), 'YYYYMMDD' 기대")
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def _to_price(raw: object, field: str) -> int | float:
    """가격 문자열 → 숫자. 정수면 int, 소수면 float."""
    text = str(raw).strip()
    if not text:
        raise KisFieldError(f"가격 값이 비어 있음 ({field})")
    try:
        return int(text) if text.lstrip("-").isdigit() else float(text)
    except ValueError as exc:
        raise KisFieldError(f"가격 숫자 변환 실패 ({field}={raw!r})") from exc


def _to_int(raw: object, field: str) -> int:
    """거래량/거래대금 문자열 → int."""
    text = str(raw).strip()
    if not text:
        raise KisFieldError(f"정수 값이 비어 있음 ({field})")
    try:
        return int(text)
    except ValueError as exc:
        raise KisFieldError(f"정수 변환 실패 ({field}={raw!r})") from exc


# ─────────────────────────────────────────────────────────────────────────────
# 응답 변환 (output2 → 내부 OHLCV)
# ─────────────────────────────────────────────────────────────────────────────
def parse_kis_ohlcv_item(item: dict) -> OHLCV:
    """output2 원소 1건을 내부 표준 OHLCV로 변환. 필수 필드 누락 시 KisFieldError."""
    missing = [f for f in REQUIRED_KIS_FIELDS if f not in item]
    if missing:
        raise KisFieldError(f"KIS output2 필수 필드 누락: {missing}")
    return OHLCV(
        date=_to_iso_date(item[KIS_FIELD_DATE]),
        open=_to_price(item[KIS_FIELD_OPEN], KIS_FIELD_OPEN),
        high=_to_price(item[KIS_FIELD_HIGH], KIS_FIELD_HIGH),
        low=_to_price(item[KIS_FIELD_LOW], KIS_FIELD_LOW),
        close=_to_price(item[KIS_FIELD_CLOSE], KIS_FIELD_CLOSE),
        volume=_to_int(item[KIS_FIELD_VOLUME], KIS_FIELD_VOLUME),
        trading_value=_to_int(item[KIS_FIELD_TRADING_VALUE], KIS_FIELD_TRADING_VALUE),
    )


def parse_kis_ohlcv_output(output2: list[dict]) -> list[OHLCV]:
    """output2 배열 → 내부 OHLCV 리스트. **날짜 오름차순(과거→최신)으로 정규화**.

    KIS는 최신→과거(descending)로 반환하므로(kis_mapping §11.5), 이후 지표·차트가 쓰기 좋게
    과거→최신으로 정렬한다. output2가 비면 빈 리스트를 반환한다(상장폐지·거래정지·무데이터는
    상위 supervisor가 data_limited/regime_unavailable로 판단 — 이 단계는 상태 판정하지 않음).
    """
    if not output2:
        return []
    bars = [parse_kis_ohlcv_item(item) for item in output2]
    bars.sort(key=lambda bar: bar.date)  # ISO 문자열은 사전순=시간순
    return bars


# ─────────────────────────────────────────────────────────────────────────────
# access token 발급 (모듈 레벨 메모리 캐시. 파일/Redis 캐시는 이 단계 범위 아님)
# ─────────────────────────────────────────────────────────────────────────────
_token_state: dict[str, object] = {"access_token": None, "expires_at": 0.0}
_TOKEN_EXPIRY_MARGIN_SECONDS = 300  # 만료 5분 전 갱신


def get_access_token(*, client: httpx.Client | None = None) -> str:
    """KIS access token을 발급하거나 만료 전이면 메모리 캐시에서 재사용한다.

    인증정보는 load_kis_settings()로 .env에서만 읽는다(코드 하드코딩 없음). secret은 로그에 남기지 않는다.
    """
    now = time.time()
    cached = _token_state["access_token"]
    if isinstance(cached, str) and now < float(_token_state["expires_at"]):
        return cached

    settings = load_kis_settings()
    owns_client = client is None
    client = client or httpx.Client(timeout=KIS_TIMEOUT_SECONDS)
    try:
        resp = client.post(
            f"{settings.base_url}{TOKEN_PATH}",
            json={
                "grant_type": "client_credentials",
                "appkey": settings.api_key,
                "appsecret": settings.api_secret,
            },
        )
    finally:
        if owns_client:
            client.close()

    if resp.status_code != 200:
        raise KisApiError(f"토큰 발급 실패 HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise KisApiError("토큰 응답에 access_token 없음")

    expires_in = int(data.get("expires_in", 86400))
    _token_state["access_token"] = token
    _token_state["expires_at"] = now + expires_in - _TOKEN_EXPIRY_MARGIN_SECONDS
    logger.info("kis_token_issued", extra={"expires_in": expires_in})
    return token


# ─────────────────────────────────────────────────────────────────────────────
# 기간별시세 호출
# ─────────────────────────────────────────────────────────────────────────────
def _default_date_range(period: str, today: date | None = None) -> tuple[str, str]:
    """단일 호출용 조회 구간(YYYYMMDD). 최근 봉 위주로 받는다(구간 분할은 후속 단계)."""
    today = today or datetime.now().date()
    lookback = _LOOKBACK_DAYS_DAILY if period == KIS_PERIOD_DAILY else _LOOKBACK_DAYS_WEEKLY_MONTHLY
    start = today - timedelta(days=lookback)
    return start.strftime("%Y%m%d"), today.strftime("%Y%m%d")


def _sleep_backoff(attempt: int) -> None:
    """재시도 사이 지수 백오프(config KIS_BACKOFF_SECONDS). 무한 재시도 없음."""
    idx = min(attempt, len(KIS_BACKOFF_SECONDS) - 1)
    time.sleep(KIS_BACKOFF_SECONDS[idx])


def _call_chart(
    settings: KISSettings,
    token: str,
    ticker: str,
    period: str,
    date_from: str,
    date_to: str,
    client: httpx.Client,
) -> dict:
    """기간별시세 1회 호출. 네트워크/타임아웃/429/EGW00201은 재시도, 그 외 오류는 즉시 실패."""
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": settings.api_key,
        "appsecret": settings.api_secret,
        "tr_id": TR_ID,
        "custtype": CUST_TYPE,
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": MARKET_DIV_CODE,
        "FID_INPUT_ISCD": ticker,
        "FID_INPUT_DATE_1": date_from,
        "FID_INPUT_DATE_2": date_to,
        "FID_PERIOD_DIV_CODE": period,
        "FID_ORG_ADJ_PRC": ORG_ADJ_PRC,
    }
    url = f"{settings.base_url}{CHART_PATH}"

    last_err = "unknown"
    for attempt in range(KIS_MAX_RETRIES):
        try:
            resp = client.get(url, headers=headers, params=params)
        except httpx.RequestError as exc:  # 타임아웃 포함(TimeoutException ⊂ RequestError)
            last_err = f"network error: {exc}"
        else:
            if resp.status_code == 429 or RATE_LIMIT_MSG_CODE in resp.text:
                last_err = f"rate limit(HTTP {resp.status_code})"  # 재시도 대상
            elif resp.status_code != 200:
                raise KisApiError(f"KIS HTTP {resp.status_code}: {resp.text[:200]}")
            else:
                data = resp.json()
                if data.get("rt_cd") == "0":
                    return data
                if data.get("msg_cd") == RATE_LIMIT_MSG_CODE:
                    last_err = f"rate limit(rt_cd): {data.get('msg1')}"  # 재시도 대상
                else:
                    raise KisApiError(
                        f"KIS 오류 rt_cd={data.get('rt_cd')} "
                        f"msg_cd={data.get('msg_cd')} msg1={data.get('msg1')}"
                    )
        if attempt < KIS_MAX_RETRIES - 1:
            logger.warning("kis_request_retry", extra={"ticker": ticker, "period": period, "reason": last_err})
            _sleep_backoff(attempt)
    raise KisApiError(f"KIS 최대 재시도({KIS_MAX_RETRIES}) 초과: {last_err}")


def fetch_ohlcv(ticker: str, period: str, *, client: httpx.Client | None = None) -> list[OHLCV]:
    """한 종목·한 타임프레임(D/W/M)의 내부 표준 OHLCV(과거→최신)를 반환한다(단일 호출)."""
    validate_ticker(ticker)
    validate_period(period)

    settings = load_kis_settings()
    token = get_access_token(client=client)
    date_from, date_to = _default_date_range(period)

    owns_client = client is None
    client = client or httpx.Client(timeout=KIS_TIMEOUT_SECONDS)
    try:
        data = _call_chart(settings, token, ticker, period, date_from, date_to, client)
    finally:
        if owns_client:
            client.close()

    return parse_kis_ohlcv_output(data.get("output2") or [])


def fetch_multi_timeframe_ohlcv(ticker: str) -> dict[str, list[OHLCV]]:
    """한 종목의 D/W/M 세 타임프레임을 각각 KIS에서 직접 받아 dict로 반환한다.

    일봉에서 주/월봉을 리샘플하지 않는다 — 세 타임프레임 모두 KIS 원본(kis_mapping §3).
    """
    validate_ticker(ticker)
    return {period: fetch_ohlcv(ticker, period) for period in ALLOWED_PERIODS}
