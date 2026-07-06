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
import math
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx
from pydantic import ValidationError

from ..config import (
    INTRADAY_MARKET_OPEN_HHMMSS,
    INTRADAY_MINUTE_MAX_CALLS,
    KIS_BACKOFF_SECONDS,
    KIS_FETCH_CHUNK_DAYS,
    KIS_FETCH_LOOKBACK_DAYS,
    KIS_MAX_CHUNKS,
    KIS_MAX_RETRIES,
    KIS_PERIOD_DAILY,
    KIS_PERIOD_MONTHLY,
    KIS_PERIOD_WEEKLY,
    KIS_TIMEOUT_SECONDS,
    KISSettings,
    is_allowed_ticker,
    load_kis_settings,
)
from ..schemas.intraday import IntradayCandle
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

# ── 주식당일분봉조회 API (kis_mapping §12) — D/W/M과 별도 TR ────────────────────
MINUTE_CHART_PATH = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
MINUTE_TR_ID = "FHKST03010200"  # 실전/모의 동일 (kis_mapping §12.2)
# 요청 FID 값 — kis_mapping §12.3 / 공식 샘플 기준. FID_COND_MRKT_DIV_CODE는 MARKET_DIV_CODE("J") 재사용.
# 아래 두 값의 정확한 코드는 §12.9 smoke 확인 대상(구조·필드명은 확정).
MINUTE_PW_DATA_INCU_YN = "Y"  # FID_PW_DATA_INCU_YN
MINUTE_ETC_CLS_CODE = ""      # FID_ETC_CLS_CODE
# 역방향 페이징 상한·장 시작 컷오프는 config.py §14(config.md §12) 정본을 사용한다:
#   INTRADAY_MINUTE_MAX_CALLS · INTRADAY_MARKET_OPEN_HHMMSS.

# output2 원본 필드 → IntradayCandle (kis_mapping §12.4). close는 분봉 현재가(stck_prpr)로,
# 일봉의 stck_clpr과 다르다. trading_value는 매핑하지 않는다(acml_tr_pbmn은 누적).
KIS_MIN_FIELD_DATE = "stck_bsop_date"
KIS_MIN_FIELD_HOUR = "stck_cntg_hour"
KIS_MIN_FIELD_OPEN = "stck_oprc"
KIS_MIN_FIELD_HIGH = "stck_hgpr"
KIS_MIN_FIELD_LOW = "stck_lwpr"
KIS_MIN_FIELD_CLOSE = "stck_prpr"
KIS_MIN_FIELD_VOLUME = "cntg_vol"
REQUIRED_MIN_FIELDS = (
    KIS_MIN_FIELD_DATE, KIS_MIN_FIELD_HOUR, KIS_MIN_FIELD_OPEN,
    KIS_MIN_FIELD_HIGH, KIS_MIN_FIELD_LOW, KIS_MIN_FIELD_CLOSE, KIS_MIN_FIELD_VOLUME,
)
# output1 메타데이터 필드 (kis_mapping §12.5)
KIS_MIN_OUT1_PREV_CLOSE = "stck_prdy_clpr"
KIS_MIN_OUT1_LAST_PRICE = "stck_prpr"
KIS_MIN_OUT1_CUM_VOLUME = "acml_vol"
KIS_MIN_OUT1_CUM_TRADING_VALUE = "acml_tr_pbmn"

_HHMMSS_RE = re.compile(r"^\d{6}$")



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


class KisRangeIncompleteError(KisError):
    """구간 분할 조회가 KIS_MAX_CHUNKS 안에 요청 start_date까지 확보하지 못함(partial 반환 금지)."""


# 허용 날짜 입력 형식 (kis_mapping §8.1). 이 둘 외에는 거부.
_YMD_RE = re.compile(r"^\d{8}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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
    """KIS 원본 'YYYYMMDD' → 내부 표준 ISO 'YYYY-MM-DD'.

    8자리 여부만 보지 않고 실제 달력 날짜인지 검증한다(20260231·20261301 등 거부).
    """
    text = str(raw).strip()
    # 정확히 8자리 숫자 + 실제 달력 날짜여야 한다 (strptime은 "2026731" 같은 7자리도
    # 관대하게 파싱하므로 길이를 먼저 강제한다).
    if len(text) != 8 or not text.isdigit():
        raise KisFieldError(f"날짜 형식 오류 ({field}={raw!r}), 'YYYYMMDD' 8자리 기대")
    try:
        parsed = datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise KisFieldError(f"존재하지 않는 날짜 ({field}={raw!r})") from exc
    return parsed.strftime("%Y-%m-%d")


def _to_price(raw: object, field: str) -> int | float:
    """가격 문자열 → 숫자. 정수면 int, 소수면 float. inf/-inf/nan은 fail-fast(비정상 응답)."""
    text = str(raw).strip()
    if not text:
        raise KisFieldError(f"가격 값이 비어 있음 ({field})")
    try:
        value = int(text) if text.lstrip("-").isdigit() else float(text)
    except ValueError as exc:
        raise KisFieldError(f"가격 숫자 변환 실패 ({field}={raw!r})") from exc
    if isinstance(value, float) and not math.isfinite(value):  # Infinity/-Infinity/NaN
        raise KisFieldError(f"비정상 숫자(inf/nan) ({field}={raw!r})")
    return value


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
def _normalize_to_date(value: str) -> date:
    """'YYYYMMDD' 또는 'YYYY-MM-DD' **두 형식만** 허용 → date.

    형식을 정규식으로 먼저 검증한 뒤(그 외 '2026--07-04'·'2026/07/04' 등 거부),
    _to_iso_date로 실제 달력 유효성까지 확인한다.
    """
    text = str(value).strip()
    if _YMD_RE.match(text):
        ymd = text
    elif _ISO_DATE_RE.match(text):
        ymd = text.replace("-", "")
    else:
        raise KisFieldError(f"날짜 형식 오류 ({value!r}), 'YYYYMMDD' 또는 'YYYY-MM-DD'만 허용")
    return date.fromisoformat(_to_iso_date(ymd))


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def normalize_end_date(value: datetime | date | str | None) -> date | None:
    """`as_of`/`end_date` 입력을 KIS 조회 종료일(date)로 정규화한다 (kis_mapping §8.2).

    None→None(오늘 기준), datetime→date(), date→그대로, 'YYYYMMDD'/'YYYY-MM-DD'→date.
    문자열 파싱은 `_normalize_to_date` 재사용. 잘못된 형식·미지원 타입·**미래 날짜**는 ValueError.
    미래 판정은 tz-aware datetime이면 그 tz 기준 오늘과 비교해, 타임존 차이로 정상 '오늘' 요청을
    미래로 오판하지 않는다.
    """
    if value is None:
        return None
    if isinstance(value, datetime):  # datetime은 date의 하위 클래스라 먼저 검사
        result = value.date()
        today = datetime.now(value.tzinfo).date()
    elif isinstance(value, date):
        result = value
        today = date.today()
    elif isinstance(value, str):
        try:
            result = _normalize_to_date(value)  # 'YYYYMMDD'/'YYYY-MM-DD' + 달력 검증 재사용
        except KisFieldError as exc:
            raise ValueError(str(exc)) from exc
        today = date.today()
    else:
        raise ValueError(f"지원하지 않는 end_date 타입: {type(value).__name__}")
    if result > today:
        raise ValueError(f"미래 as_of/end_date는 허용되지 않습니다: {result.isoformat()} > {today.isoformat()}")
    return result


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


def _extract_output2(data: dict) -> list:
    """output2 키 부재(비정상 응답)·비-list는 fail-fast, 빈 배열([])은 정상으로 반환.

    (technical_coding_guidelines §8.3·§9.1) 실제 빈 데이터와 잘못된 응답을 구분한다.
    """
    if "output2" not in data:
        raise KisFieldError("KIS 응답에 output2 키가 없습니다 (비정상 응답)")
    output2 = data["output2"]
    if not isinstance(output2, list):
        raise KisFieldError(f"output2가 list가 아닙니다: {type(output2).__name__}")
    return output2


def _fetch_ohlcv_range(
    ticker: str, period: str, start: date, end: date, client: httpx.Client,
) -> list[OHLCV]:
    """[start, end]를 청크로 나눠 KIS를 여러 번 호출·병합한다(kis_mapping §8.1).

    end에서 과거 방향으로 KIS_FETCH_CHUNK_DAYS[period]씩 이동하며, 정지 조건(목표 도달·빈 청크·
    최고(最古) date 정체·KIS_MAX_CHUNKS) 중 하나면 멈춘다. 결과는 date dedup → 범위 필터 →
    과거→최신 정렬. 청크 실패·EGW00201은 _call_chart의 기존 retry/backoff를 그대로 쓴다.
    """
    settings = load_kis_settings()
    token = get_access_token(client=client)
    chunk_days = KIS_FETCH_CHUNK_DAYS[period]

    by_date: dict[str, OHLCV] = {}
    cursor_end = end
    oldest_seen: str | None = None
    for _ in range(KIS_MAX_CHUNKS):
        chunk_start = max(start, cursor_end - timedelta(days=chunk_days))
        data = _call_chart(settings, token, ticker, period, _ymd(chunk_start), _ymd(cursor_end), client)
        bars = parse_kis_ohlcv_output(_extract_output2(data))  # 빈 배열이면 []

        if not bars:  # 자연 종료 ②: 빈 청크(더 과거 데이터 없음)
            break
        for bar in bars:
            by_date[bar.date] = bar

        chunk_oldest = min(bar.date for bar in bars)
        if chunk_start <= start:  # 자연 종료 ①: 목표 start까지 확보
            break
        if oldest_seen is not None and chunk_oldest >= oldest_seen:  # 자연 종료 ③: 더 과거로 안 감(정체)
            break
        oldest_seen = chunk_oldest
        cursor_end = chunk_start  # 다음 청크는 여기서 끝(경계 1일 겹침 → date dedup으로 흡수)
    else:
        # KIS_MAX_CHUNKS를 모두 쓰고도 요청 start까지 못 감 → 잘린 partial을 조용히 반환하지 않는다.
        raise KisRangeIncompleteError(
            f"요청 범위를 KIS_MAX_CHUNKS({KIS_MAX_CHUNKS}) 안에 확보하지 못했습니다: "
            f"ticker={ticker} period={period} "
            f"requested_start={start.isoformat()} requested_end={end.isoformat()} "
            f"oldest_fetched={oldest_seen}"
        )

    start_iso, end_iso = start.isoformat(), end.isoformat()
    merged = [bar for bar in by_date.values() if start_iso <= bar.date <= end_iso]
    merged.sort(key=lambda bar: bar.date)  # 과거→최신
    return merged


def fetch_ohlcv_range(
    ticker: str, period: str, start_date: str, end_date: str,
    *, client: httpx.Client | None = None,
) -> list[OHLCV]:
    """명시 구간 [start_date, end_date]의 내부 표준 OHLCV(과거→최신)를 반환한다.

    start_date·end_date는 'YYYYMMDD' 또는 'YYYY-MM-DD'만 허용. 구간 분할·병합은 내부에서 처리.

    fail-fast(KIS 호출 전): 잘못된 날짜 형식, `start_date > end_date`(역전 범위)는 토큰 발급·
    네트워크 호출 전에 거부한다. 요청 범위를 `KIS_MAX_CHUNKS` 안에 확보하지 못하면
    partial을 반환하지 않고 `KisRangeIncompleteError`를 던진다.
    """
    validate_ticker(ticker)
    validate_period(period)
    start, end = _normalize_to_date(start_date), _normalize_to_date(end_date)
    if start > end:  # 역전 범위 → 토큰/네트워크 전에 거부
        raise ValueError(f"start_date가 end_date보다 뒤입니다: start={start_date!r} end={end_date!r}")

    owns_client = client is None
    client = client or httpx.Client(timeout=KIS_TIMEOUT_SECONDS)
    try:
        return _fetch_ohlcv_range(ticker, period, start, end, client)
    finally:
        if owns_client:
            client.close()


def fetch_ohlcv(
    ticker: str, period: str,
    *, end_date: datetime | date | str | None = None, client: httpx.Client | None = None,
) -> list[OHLCV]:
    """한 종목·한 타임프레임(D/W/M)의 내부 표준 OHLCV(과거→최신)를 반환한다.

    KIS 단일 호출 100건 제한을 넘기기 위해 period별 KIS_FETCH_LOOKBACK_DAYS 만큼
    구간 분할 조회한다(kis_mapping §8.1). `end_date`(조회 종료일 = FID_INPUT_DATE_2)를 주면 그
    날짜 기준, 없으면 오늘 기준으로 조회한다(kis_mapping §8.2). 미래 end_date는 ValueError.
    """
    validate_ticker(ticker)
    validate_period(period)
    end = normalize_end_date(end_date) or datetime.now().date()
    start = end - timedelta(days=KIS_FETCH_LOOKBACK_DAYS[period])
    return fetch_ohlcv_range(ticker, period, _ymd(start), _ymd(end), client=client)


def fetch_multi_timeframe_ohlcv(
    ticker: str, *, end_date: datetime | date | str | None = None,
) -> dict[str, list[OHLCV]]:
    """한 종목의 D/W/M 세 타임프레임을 각각 KIS에서 직접 받아 dict로 반환한다.

    일봉에서 주/월봉을 리샘플하지 않는다 — 세 타임프레임 모두 KIS 원본(kis_mapping §3).
    `end_date`는 한 번 정규화해 **D/W/M 모두 같은 종료일**로 조회한다(kis_mapping §8.2).
    """
    validate_ticker(ticker)
    end = normalize_end_date(end_date)  # 한 번 정규화 → 세 타임프레임 동일 기준일
    return {period: fetch_ohlcv(ticker, period, end_date=end) for period in ALLOWED_PERIODS}


# ─────────────────────────────────────────────────────────────────────────────
# 주식당일분봉조회 (kis_mapping §12) — output2 → IntradayCandle, output1 → 메타데이터
# ─────────────────────────────────────────────────────────────────────────────
def _validate_hhmmss(value: object, *, field: str) -> str:
    """'HHMMSS' 6자리 + 실제 시각(00:00:00–23:59:59) 검증. 통과 시 정규화 문자열 반환, 아니면 KisFieldError.

    6자리 형식만으로는 '256000'(25시)·'126099'(60분/99초) 같은 비시각을 걸러내지 못하므로
    strptime으로 실제 시각인지 확인한다(입력·응답 파싱 공통). 네트워크 호출 전에 fail-fast하는 데 쓴다.
    """
    text = str(value).strip()
    if not _HHMMSS_RE.match(text):
        raise KisFieldError(f"{field} 형식 오류 ({value!r}), 'HHMMSS' 6자리 기대")
    try:
        datetime.strptime(text, "%H%M%S")  # 실제 시각 검증(240000·256000·126099 등 거부)
    except ValueError as exc:
        raise KisFieldError(f"존재하지 않는 시각 ({field}={value!r})") from exc
    return text


def _to_intraday_timestamp(bsop_date: object, cntg_hour: object) -> str:
    """KIS 'YYYYMMDD' + 'HHMMSS' → IntradayCandle.timestamp 'YYYY-MM-DDTHH:MM:SS'."""
    iso_date = _to_iso_date(bsop_date, KIS_MIN_FIELD_DATE)  # 8자리·달력 검증 재사용
    hh = _validate_hhmmss(cntg_hour, field=KIS_MIN_FIELD_HOUR)  # 6자리 + 실제 시각 검증
    return f"{iso_date}T{hh[0:2]}:{hh[2:4]}:{hh[4:6]}"


def parse_kis_intraday_item(item: dict) -> IntradayCandle:
    """output2 원소 1건 → IntradayCandle. trading_value는 매핑하지 않는다(acml_tr_pbmn은 누적).

    필수 필드 누락·숫자 변환 실패·스키마 위반(high<low 등)은 KisFieldError로 fail-fast한다(row skip 안 함).
    """
    missing = [f for f in REQUIRED_MIN_FIELDS if f not in item]
    if missing:
        raise KisFieldError(f"KIS 분봉 output2 필수 필드 누락: {missing}")
    try:
        return IntradayCandle(
            timestamp=_to_intraday_timestamp(item[KIS_MIN_FIELD_DATE], item[KIS_MIN_FIELD_HOUR]),
            open=_to_price(item[KIS_MIN_FIELD_OPEN], KIS_MIN_FIELD_OPEN),
            high=_to_price(item[KIS_MIN_FIELD_HIGH], KIS_MIN_FIELD_HIGH),
            low=_to_price(item[KIS_MIN_FIELD_LOW], KIS_MIN_FIELD_LOW),
            close=_to_price(item[KIS_MIN_FIELD_CLOSE], KIS_MIN_FIELD_CLOSE),
            volume=_to_int(item[KIS_MIN_FIELD_VOLUME], KIS_MIN_FIELD_VOLUME),
            trading_value=None,  # acml_tr_pbmn은 누적 거래대금이라 개별 분봉 값이 아님(kis_mapping §12.4)
            interval="1min",
        )
    except ValidationError as exc:  # high<low 등 스키마 위반 → fail-fast
        raise KisFieldError(f"분봉 스키마 검증 실패: {exc}") from exc


def parse_kis_intraday_output(output2: list[dict]) -> list[IntradayCandle]:
    """output2 배열 → IntradayCandle 리스트(정렬·dedupe는 상위 fetch에서 병합 시 처리). 빈 배열은 []."""
    if not output2:
        return []
    return [parse_kis_intraday_item(item) for item in output2]


def _opt_price(out1: dict, field: str) -> float | None:
    raw = out1.get(field)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(_to_price(raw, field))
    except KisFieldError:
        return None


def _opt_int(out1: dict, field: str) -> int | None:
    raw = out1.get(field)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return _to_int(raw, field)
    except KisFieldError:
        return None


def _extract_output1(data: dict) -> dict:
    """output1(종목 요약)을 dict로 반환. 단일 객체/리스트 첫 원소 모두 허용, 부재 시 {}."""
    out1 = data.get("output1")
    if isinstance(out1, dict):
        return out1
    if isinstance(out1, list) and out1 and isinstance(out1[0], dict):
        return out1[0]
    return {}


@dataclass(frozen=True)
class IntradayFetchResult:
    """주식당일분봉조회 결과 — 정규화 candles + output1 메타데이터.

    supervisor는 previous_close(전일 종가) 등 메타데이터로 intraday_context를 채운다.
    (이 단계에서 status 판정·보정은 하지 않는다.)
    """
    candles: list[IntradayCandle]
    previous_close: float | None
    latest_price: float | None
    cumulative_volume: int | None
    cumulative_trading_value: int | None


def _resolve_input_hour(as_of: date | datetime | None, input_hour: str | None) -> str:
    """FID_INPUT_HOUR_1(HHMMSS). input_hour 우선, 없으면 as_of 시각, 그것도 없으면 현재 시각."""
    if input_hour is not None:
        # 6자리 형식뿐 아니라 실제 시각까지 검증해 네트워크 호출 전에 fail-fast(256000 등 거부).
        return _validate_hhmmss(input_hour, field="input_hour")
    if isinstance(as_of, datetime):
        return as_of.strftime("%H%M%S")
    return datetime.now().strftime("%H%M%S")


def _hhmmss_minus_minute(hhmmss: str) -> str:
    """HHMMSS에서 1분 뺀 HHMMSS(같은 날 기준). 역방향 페이징 커서 계산용."""
    return (datetime.strptime(hhmmss, "%H%M%S") - timedelta(minutes=1)).strftime("%H%M%S")


def _call_minute_chart(
    settings: KISSettings, token: str, ticker: str, input_hour: str, client: httpx.Client,
) -> dict:
    """주식당일분봉조회 1회 호출. 네트워크/429/EGW00201은 재시도(기존 D/W/M 패턴 재사용, _call_chart 무변경)."""
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": settings.api_key,
        "appsecret": settings.api_secret,
        "tr_id": MINUTE_TR_ID,
        "custtype": CUST_TYPE,
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": MARKET_DIV_CODE,
        "FID_INPUT_ISCD": ticker,
        "FID_INPUT_HOUR_1": input_hour,
        "FID_PW_DATA_INCU_YN": MINUTE_PW_DATA_INCU_YN,
        "FID_ETC_CLS_CODE": MINUTE_ETC_CLS_CODE,
    }
    url = f"{settings.base_url}{MINUTE_CHART_PATH}"

    last_err = "unknown"
    for attempt in range(KIS_MAX_RETRIES):
        try:
            resp = client.get(url, headers=headers, params=params)
        except httpx.RequestError as exc:
            last_err = f"network error: {exc}"
        else:
            if resp.status_code == 429 or RATE_LIMIT_MSG_CODE in resp.text:
                last_err = f"rate limit(HTTP {resp.status_code})"
            elif resp.status_code != 200:
                raise KisApiError(f"KIS HTTP {resp.status_code}: {resp.text[:200]}")
            else:
                data = resp.json()
                if data.get("rt_cd") == "0":
                    return data
                if data.get("msg_cd") == RATE_LIMIT_MSG_CODE:
                    last_err = f"rate limit(rt_cd): {data.get('msg1')}"
                else:
                    raise KisApiError(
                        f"KIS 오류 rt_cd={data.get('rt_cd')} "
                        f"msg_cd={data.get('msg_cd')} msg1={data.get('msg1')}"
                    )
        if attempt < KIS_MAX_RETRIES - 1:
            logger.warning("kis_minute_request_retry", extra={"ticker": ticker, "hour": input_hour, "reason": last_err})
            _sleep_backoff(attempt)
    raise KisApiError(f"KIS 분봉 최대 재시도({KIS_MAX_RETRIES}) 초과: {last_err}")


def fetch_minute_ohlcv(
    ticker: str,
    *,
    as_of: date | datetime | None = None,
    input_hour: str | None = None,
    limit: int | None = None,
    client: httpx.Client | None = None,
) -> IntradayFetchResult:
    """주식당일분봉조회(TR FHKST03010200)로 **당일** 1분봉을 조회한다(kis_mapping §12).

    당일만 제공·1회 최대 30건이라, `FID_INPUT_HOUR_1`을 **역방향으로 이동하며 반복 조회**하고
    timestamp 기준 dedupe·오름차순 정렬한다(tr_cont/FK100/NK100 방식 아님). `input_hour`가 없으면
    `as_of` 시각(또는 현재 시각) 기준으로 시작한다. 미래 시각은 공식 샘플상 현재 기준으로 조회되며,
    코드에서 과하게 보정하지 않는다. `limit`이 있으면 최신 `limit`개만 반환한다.
    빈 output2는 빈 candles로 반환하고, **status(휴장·장전 등) 판정은 하지 않는다**(supervisor 몫).

    **단일 거래일 보장:** 역방향 페이징이 09:00 이전 구간에서 직전 영업일 봉을 반환할 수 있으므로,
    반환 candles는 **첫 non-empty batch의 거래일 하루로 제한**한다(다른 날짜가 나오면 same-day subset만
    확보하고 중단). `as_of`로는 거르지 않는다 — `as_of.date()` 일치 여부는 supervisor 최종 가드가 본다.
    """
    validate_ticker(ticker)
    if limit is not None and limit <= 0:
        return IntradayFetchResult([], None, None, None, None)
    cursor = _resolve_input_hour(as_of, input_hour)

    owns_client = client is None
    client = client or httpx.Client(timeout=KIS_TIMEOUT_SECONDS)
    try:
        settings = load_kis_settings()
        token = get_access_token(client=client)
        by_ts: dict[str, IntradayCandle] = {}
        metadata: dict | None = None
        oldest_hour: str | None = None
        target_date: str | None = None  # 첫 non-empty batch의 거래일(YYYY-MM-DD). 결과를 이 하루로 제한.
        for _ in range(INTRADAY_MINUTE_MAX_CALLS):
            data = _call_minute_chart(settings, token, ticker, cursor, client)
            if metadata is None:
                metadata = _extract_output1(data)  # 첫 응답의 종목 요약을 메타데이터로
            candles = parse_kis_intraday_output(_extract_output2(data))
            if not candles:  # 자연 종료: 더 과거(또는 데이터) 없음
                break
            # 날짜 경계 가드: KIS 역방향 페이징이 09:00 이전에서 직전 영업일 봉을 내줄 수 있다
            # (그 봉의 HHMMSS는 여전히 090000보다 커서 아래 장시작 컷오프가 안 걸린다). 결과를 첫
            # non-empty batch의 거래일 하루로 제한해 여러 날짜가 섞이지 않게 한다(kis_mapping §12.6).
            if target_date is None:
                target_date = max(c.timestamp for c in candles)[:10]  # 커서에 가장 가까운 세션
            same_day = [c for c in candles if c.timestamp[:10] == target_date]
            crossed_date = len(same_day) != len(candles)  # 직전 영업일 등 다른 날짜 candle 포함
            for candle in same_day:
                by_ts[candle.timestamp] = candle
            if crossed_date:  # 날짜 경계 넘어감 → same-day subset만 확보하고 페이징 중단(추가 호출 없음)
                break

            batch_oldest_hour = min(c.timestamp[11:].replace(":", "") for c in same_day)  # HHMMSS
            if batch_oldest_hour <= INTRADAY_MARKET_OPEN_HHMMSS:  # 장 시작 이전까지 확보
                break
            if oldest_hour is not None and batch_oldest_hour >= oldest_hour:  # 정체
                break
            oldest_hour = batch_oldest_hour
            next_cursor = _hhmmss_minus_minute(batch_oldest_hour)
            if next_cursor >= cursor:  # 경계 wrap 등으로 진전 없음 → 중단
                break
            cursor = next_cursor
            if limit is not None and len(by_ts) >= limit:
                break
    finally:
        if owns_client:
            client.close()

    candles_sorted = sorted(by_ts.values(), key=lambda c: c.timestamp)  # 과거→최신
    if limit is not None:
        candles_sorted = candles_sorted[-limit:]  # 최신 limit개
    out1 = metadata or {}
    return IntradayFetchResult(
        candles=candles_sorted,
        previous_close=_opt_price(out1, KIS_MIN_OUT1_PREV_CLOSE),
        latest_price=_opt_price(out1, KIS_MIN_OUT1_LAST_PRICE),
        cumulative_volume=_opt_int(out1, KIS_MIN_OUT1_CUM_VOLUME),
        cumulative_trading_value=_opt_int(out1, KIS_MIN_OUT1_CUM_TRADING_VALUE),
    )
