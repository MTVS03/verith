"""KIS 어댑터 — "종목별 투자자매매동향(일별)" → signals.py DataFrame.

경계 번역기(boundary translator). 이 파일만이 KIS의 필드명·단위·정렬·인증을 안다.
덕분에 signals.py·verify_rules.py는 KIS를 전혀 몰라도, 자기 스키마
("개인/외국인/기관/거래대금" 컬럼 + 오름차순 날짜 index)만 신뢰하면 된다.

규약(CLAUDE.md 데이터 소스):
  - 조회(GET) 전용. 주문(매수/매도/정정/취소) 함수는 이 파일에 없다 — 실전 계좌.
  - .env의 KIS_API_KEY/KIS_API_SECRET/KIS_BASE_URL로 토큰 발급 후 호출.
  - 비밀·토큰은 로그/예외 메시지에 넣지 않는다.
  - 실패 시 다른 방법을 연쇄 시도하지 않고 명확한 예외로 멈춘다.
    (단 하나의 예외: 유량 제어 EGW00201 은 0.6초 후 1회 재시도 — _get_json 참고.)

실물로 확인된 변환 4가지(scratch_kis.py로 검증):
  (1) 필드 매핑: *_ntby_tr_pbmn → 개인/외국인/기관, acml_tr_pbmn → 거래대금
  (2) 정렬: KIS는 최신이 먼저(내림차순) → signals는 오름차순 전제 → 오름차순으로
  (3) 단위: 순매수는 백만원, acml_tr_pbmn은 원 → acml ÷ 1,000,000 로 백만원 통일
  (4) 컬럼명·순서를 signals 스키마와 정확히 일치시켜 반환
"""

from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path

import httpx
import pandas as pd
from dotenv import find_dotenv, load_dotenv

from .. import config
from .signals import COL_FORE, COL_INDI, COL_INST, COL_VALUE, INST_DETAIL

# ── KIS 엔드포인트 상수 (이 경계에서만 안다) ──────────────────
_OAUTH_PATH = "/oauth2/tokenP"
_QUOTATIONS_PATH = "/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily"
_TR_ID = "FHPTJ04160001"  # 종목별 투자자매매동향(일별). 실전전용.
_TIMEOUT = 15.0

# KIS 유량 제어: 짧은 창에 조회가 겹치면 HTTP 500 + EGW00201 로 선차단된다
# (scratch_kis_ratelimit.py 로 실물 확인 — 간헐적, 11ms 게이트웨이 즉답).
_RATE_LIMIT_MSG_CD = "EGW00201"       # "초당 거래건수를 초과하였습니다."
_RATE_LIMIT_RETRY_WAIT_SEC = 0.6      # 유량 창 하나를 넘기는 대기

# (1) KIS 원본 필드 → signals 컬럼. 매핑의 단일 출처(매직 스트링 금지).
_FIELD_MAP: dict[str, str] = {
    "prsn_ntby_tr_pbmn": COL_INDI,   # 개인   순매수 거래대금 (백만원)
    "frgn_ntby_tr_pbmn": COL_FORE,   # 외국인 순매수 거래대금 (백만원)
    "orgn_ntby_tr_pbmn": COL_INST,   # 기관계 순매수 거래대금 (백만원)
    "acml_tr_pbmn": COL_VALUE,       # 누적(총) 거래대금 (원! ← ÷1e6 필요)
}
# 기관계 세부 7주체 (전부 백만원 — 세부 합 ≈ 기관계 항등식 실물 확인됨).
# 한글명은 KIS 공식 필드 사전(공식 GitHub) 그대로. signals.INST_DETAIL 과 일치.
_DETAIL_FIELD_MAP: dict[str, str] = {
    "scrt_ntby_tr_pbmn": "증권",
    "ivtr_ntby_tr_pbmn": "투자신탁",
    "pe_fund_ntby_tr_pbmn": "사모펀드",
    "bank_ntby_tr_pbmn": "은행",
    "insu_ntby_tr_pbmn": "보험",
    "mrbn_ntby_tr_pbmn": "종금",
    "fund_ntby_tr_pbmn": "기금",
}
assert set(_DETAIL_FIELD_MAP.values()) == set(INST_DETAIL)  # 이름 단일 출처 보장
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


def _issue_token(client: httpx.Client, app_key: str, app_secret: str) -> tuple[str, float]:
    """접근토큰 발급(POST) → (토큰, 유효초). 실패 시 상태코드만 알리고 멈춘다(토큰/키 비노출)."""
    resp = client.post(
        _OAUTH_PATH,
        json={"grant_type": "client_credentials",
              "appkey": app_key, "appsecret": app_secret},
    )
    if resp.status_code != 200:
        raise KisError(f"KIS 토큰 발급 실패 (HTTP {resp.status_code}).")
    body = resp.json()
    token = body.get("access_token")
    if not token:
        raise KisError("KIS 토큰 발급 응답에 access_token이 없습니다.")
    return token, float(body.get("expires_in") or 86400)


# ── 토큰 캐시 ─────────────────────────────────────────────
# KIS 토큰은 24h 유효한데 발급 '빈도'에 제한이 있다(과발급 → 403).
# 렌더·테스트가 각각 새 프로세스라 메모리 캐시로는 부족 → 파일 캐시.
# 경로는 리포 밖(~/.cache)이라 커밋될 수 없다(비밀 커밋 금지 규약을 구조로 보장).
_TOKEN_CACHE_PATH = Path.home() / ".cache" / "verith" / "kis_token.json"
_TOKEN_MARGIN_SEC = 60          # 만료 직전 토큰은 안 쓴다(리포트 생성은 초 단위라 충분)


def _read_cache(path: Path, now: float) -> str | None:
    """캐시된 토큰이 유효하면 반환, 없거나 만료·손상이면 None. 값은 출력하지 않는다."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    token = data.get("token")
    expires_at = data.get("expires_at")
    if not token or not isinstance(expires_at, (int, float)):
        return None
    if now >= expires_at - _TOKEN_MARGIN_SEC:
        return None
    return token


def _write_cache(path: Path, token: str, expires_at: float) -> None:
    """토큰을 파일로 저장(권한 600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"token": token, "expires_at": expires_at}), encoding="utf-8"
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass                    # 권한 미지원 파일시스템이어도 동작은 유지


def _get_token(client: httpx.Client, app_key: str, app_secret: str) -> str:
    """캐시 우선 토큰 획득 — 유효 캐시가 있으면 발급 0회(빈도 제한 회피).

    알려진 한계(M2 최소): 같은 키로 다른 곳에서 새 토큰을 발급하면 KIS 가
    이전 토큰을 무효화한다. 그 경우 조회가 KisError 로 멈춘다(정직한 실패).
    반응형 재발급은 넣지 않는다.
    """
    now = time.time()
    cached = _read_cache(_TOKEN_CACHE_PATH, now)
    if cached:
        return cached
    token, expires_in = _issue_token(client, app_key, app_secret)
    _write_cache(_TOKEN_CACHE_PATH, token, now + expires_in)
    return token


def _auth_headers(app_key: str, app_secret: str, token: str, tr_id: str) -> dict:
    """KIS 조회 공통 헤더. TR마다 tr_id만 다르다."""
    return {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
    }


def _get_json(client: httpx.Client, path: str, headers: dict, params: dict, what: str) -> dict:
    """조회 GET 의 HTTP 층 공통 경로 — 실패 처리를 한 곳에 모은다.

    유일한 재시도: KIS 유량 제어 신호(HTTP 500 + EGW00201)에 한해 0.6초 대기 후
    딱 1회. 문서화된 흐름 제어에 대한 규정된 대응이지, 원인 불명 실패의 연쇄
    시도가 아니다 — 그 외 모든 실패는 즉시 KisError(규약 유지). 에러 메시지에
    msg_cd·msg1 을 담아 원인이 바로 보이게 한다(상태코드만으론 진단 불가 교훈).
    """
    for attempt in (1, 2):
        resp = client.get(path, headers=headers, params=params)
        if resp.status_code == 200:
            return resp.json()
        try:
            body = resp.json()
            msg_cd, msg1 = body.get("msg_cd"), body.get("msg1")
        except ValueError:
            msg_cd, msg1 = None, None
        if attempt == 1 and resp.status_code == 500 and msg_cd == _RATE_LIMIT_MSG_CD:
            time.sleep(_RATE_LIMIT_RETRY_WAIT_SEC)
            continue
        raise KisError(
            f"KIS {what} 조회 실패 (HTTP {resp.status_code}, msg_cd={msg_cd}, msg1={msg1})."
        )
    raise AssertionError("unreachable")


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
        token = _get_token(client, app_key, app_secret)
        body = _get_json(
            client, _QUOTATIONS_PATH,
            headers=_auth_headers(app_key, app_secret, token, _TR_ID),
            params={  # KIS 공식 예제 기준 파라미터 세트(scratch_kis.py로 확인)
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": ticker,
                "FID_INPUT_DATE_1": date_str,
                "FID_ORG_ADJ_PRC": "",
                "FID_ETC_CLS_CODE": "",
            },
            what="투자자매매동향",
        )

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
    # (1) 필드 매핑: KIS 필드명을 signals 컬럼명으로 갈아끼운다(세부 7주체 포함).
    full_map = {**_FIELD_MAP, **_DETAIL_FIELD_MAP}
    records = [{col: row[kis] for kis, col in full_map.items()} for row in rows]
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

    # (4) 컬럼 순서를 signals 스키마와 정확히 일치시켜 반환 (+ 기관 세부 7주체).
    return df[[COL_INDI, COL_FORE, COL_INST, COL_VALUE, *INST_DETAIL]]

