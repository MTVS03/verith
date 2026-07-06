"""KIS 어댑터 — "종목별 투자자매매동향(일별)" → signals.py DataFrame.

경계 번역기(boundary translator). 이 파일만이 KIS의 필드명·단위·정렬·인증을 안다.
덕분에 signals.py·verify_rules.py는 KIS를 전혀 몰라도, 자기 스키마
("개인/외국인/기관/거래대금" 컬럼 + 오름차순 날짜 index)만 신뢰하면 된다.

규약(CLAUDE.md 데이터 소스):
  - 조회(GET) 전용. 주문(매수/매도/정정/취소) 함수는 이 파일에 없다 — 실전 계좌.
  - .env의 KIS_API_KEY/KIS_API_SECRET/KIS_BASE_URL로 토큰 발급 후 호출.
  - 비밀·토큰은 로그/예외 메시지에 넣지 않는다.
  - 실패 시 다른 방법을 연쇄 시도하지 않고 명확한 예외로 멈춘다.

실물로 확인된 변환 4가지(scratch_kis.py로 검증):
  (1) 필드 매핑: *_ntby_tr_pbmn → 개인/외국인/기관, acml_tr_pbmn → 거래대금
  (2) 정렬: KIS는 최신이 먼저(내림차순) → signals는 오름차순 전제 → 오름차순으로
  (3) 단위: 순매수는 백만원, acml_tr_pbmn은 원 → acml ÷ 1,000,000 로 백만원 통일
  (4) 컬럼명·순서를 signals 스키마와 정확히 일치시켜 반환
"""

from __future__ import annotations

import os
from datetime import date

import httpx
import pandas as pd
from dotenv import find_dotenv, load_dotenv

from .. import config
from .signals import COL_FORE, COL_INDI, COL_INST, COL_VALUE

# ── KIS 엔드포인트 상수 (이 경계에서만 안다) ──────────────────
_OAUTH_PATH = "/oauth2/tokenP"
_QUOTATIONS_PATH = "/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily"
_TR_ID = "FHPTJ04160001"  # 종목별 투자자매매동향(일별). 실전전용.
_TIMEOUT = 15.0

# (1) KIS 원본 필드 → signals 컬럼. 매핑의 단일 출처(매직 스트링 금지).
_FIELD_MAP: dict[str, str] = {
    "prsn_ntby_tr_pbmn": COL_INDI,   # 개인   순매수 거래대금 (백만원)
    "frgn_ntby_tr_pbmn": COL_FORE,   # 외국인 순매수 거래대금 (백만원)
    "orgn_ntby_tr_pbmn": COL_INST,   # 기관계 순매수 거래대금 (백만원)
    "acml_tr_pbmn": COL_VALUE,       # 누적(총) 거래대금 (원! ← ÷1e6 필요)
}
_DATE_FIELD = "stck_bsop_date"       # "20260703"


class KisError(RuntimeError):
    """KIS 호출 실패. 메시지에 비밀·토큰을 담지 않는다."""


def _load_credentials() -> tuple[str, str, str]:
    """.env에서 KIS 자격정보를 읽는다. 값은 반환만 하고 절대 출력하지 않는다."""
    load_dotenv(find_dotenv(usecwd=False))  # 모듈 위치 기준 상위로 .env 탐색(CWD 무관)
    app_key = os.getenv("KIS_API_KEY")
    app_secret = os.getenv("KIS_API_SECRET")
    base_url = os.getenv("KIS_BASE_URL")
    missing = [name for name, value in (
        ("KIS_API_KEY", app_key),
        ("KIS_API_SECRET", app_secret),
        ("KIS_BASE_URL", base_url),
    ) if not value]
    if missing:
        # 어떤 키가 비었는지만 알리고 값은 노출하지 않는다.
        raise KisError(f".env에 다음 KIS 설정이 없습니다: {missing}")
    return app_key, app_secret, base_url.rstrip("/")


def _issue_token(client: httpx.Client, app_key: str, app_secret: str) -> str:
    """접근토큰 발급(POST). 실패 시 상태코드만 알리고 멈춘다(토큰/키 비노출)."""
    resp = client.post(
        _OAUTH_PATH,
        json={"grant_type": "client_credentials",
              "appkey": app_key, "appsecret": app_secret},
    )
    if resp.status_code != 200:
        raise KisError(f"KIS 토큰 발급 실패 (HTTP {resp.status_code}).")
    token = resp.json().get("access_token")
    if not token:
        raise KisError("KIS 토큰 발급 응답에 access_token이 없습니다.")
    return token


def fetch_supply_demand(
    base_date: date | str,
    ticker: str = config.TARGET_TICKER,
) -> pd.DataFrame:
    """기준일(base_date)까지의 일별 투자자매매동향을 signals 스키마로 반환한다.

    Args:
        base_date: 조회 기준일. date 또는 "YYYYMMDD" 문자열. (오늘=장중 미확정이라
                   TIME LIMIT 에러가 나므로, 호출부가 확정된 거래일을 넘겨야 한다.)
        ticker:    6자리 종목코드. 기본값은 M1 대상(삼성전자 005930).

    Returns:
        index=날짜(오름차순), columns=[개인, 외국인, 기관, 거래대금]의 DataFrame.
        모든 값 단위는 백만원.
    """
    app_key, app_secret, base_url = _load_credentials()
    date_str = base_date.strftime("%Y%m%d") if isinstance(base_date, date) else str(base_date)

    with httpx.Client(base_url=base_url, timeout=_TIMEOUT) as client:
        token = _issue_token(client, app_key, app_secret)
        resp = client.get(
            _QUOTATIONS_PATH,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {token}",
                "appkey": app_key,
                "appsecret": app_secret,
                "tr_id": _TR_ID,
                "custtype": "P",
            },
            params={  # KIS 공식 예제 기준 파라미터 세트(scratch_kis.py로 확인)
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": ticker,
                "FID_INPUT_DATE_1": date_str,
                "FID_ORG_ADJ_PRC": "",
                "FID_ETC_CLS_CODE": "",
            },
        )

    if resp.status_code != 200:
        raise KisError(f"KIS 조회 실패 (HTTP {resp.status_code}).")
    body = resp.json()
    if body.get("rt_cd") != "0":
        # KIS 업무 에러: 코드/메시지 그대로 보여주고 멈춘다(임의 재시도 금지).
        raise KisError(
            f"KIS 조회 에러 rt_cd={body.get('rt_cd')} "
            f"msg_cd={body.get('msg_cd')} msg1={body.get('msg1')}"
        )
    rows = body.get("output2") or []
    if not rows:
        raise KisError(f"KIS output2가 비어있습니다 (ticker={ticker}, date={date_str}).")

    return _to_signals_frame(rows)


def _to_signals_frame(rows: list[dict]) -> pd.DataFrame:
    """KIS output2(내림차순 원본) → signals 스키마 DataFrame(오름차순, 백만원)."""
    # (1) 필드 매핑: KIS 필드명을 signals 컬럼명으로 갈아끼운다.
    records = [{col: row[kis] for kis, col in _FIELD_MAP.items()} for row in rows]
    dates = [row[_DATE_FIELD] for row in rows]

    df = pd.DataFrame.from_records(records)
    # KIS 값은 문자열 → 숫자. 예상 밖 값이면 조용히 넘기지 않고 에러(실패는 정보).
    df = df.apply(pd.to_numeric, errors="raise")

    # 날짜 문자열 → datetime index(이름 "날짜"), signals/fixtures와 동일한 형태.
    df.index = pd.to_datetime(dates, format="%Y%m%d")
    df.index.name = "날짜"

    # (3) 단위 통일: acml_tr_pbmn(원) ÷ 1,000,000 → 백만원(순매수와 같은 단위).
    #     이 한 줄이 없으면 강도(순매수/거래대금)가 100만 배 어긋난다.
    df[COL_VALUE] = df[COL_VALUE] / 1_000_000

    # (2) 정렬: 날짜 오름차순(과거→최신). KIS 내림차순을 뒤집어 signals의
    #     tail(5)·reversed 순회 전제와 정확히 맞춘다.
    df = df.sort_index()

    # (4) 컬럼 순서를 signals 스키마와 정확히 일치시켜 반환.
    return df[[COL_INDI, COL_FORE, COL_INST, COL_VALUE]]
