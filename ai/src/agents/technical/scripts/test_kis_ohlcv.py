"""KIS 국내주식 기간별시세(OHLCV) 수집 샘플 테스트.

목적:
  - KIS Open API가 MVP 대상 2차전지 10종목의 일/주/월봉을 정상 조회하는지 검증한다.
  - 실제 응답 구조(output1/output2)·건수·날짜 정렬 방향·100건 제한·거래대금 필드 유무를
    확인해 kis_mapping.md §11 TODO를 채우기 위한 근거를 만든다.

하지 않는 것 (지시서 제한):
  - DB 저장, Redis 캐시, LangGraph 연결, 기술적 지표 계산은 하지 않는다.
  - 오직 "KIS 실데이터 수집 가능 여부 확인"만 한다.

실행:
  cd ai
  uv run python src/agents/technical/scripts/test_kis_ohlcv.py

산출물:
  - 콘솔: 단일종목 원문 구조 / 10종목 요약 / 실패 원인
  - (스크립트와 같은 폴더)/kis_sample_output/{ticker}_{D|W|M}.csv  (내부 OHLCV 구조)
"""

from __future__ import annotations

import csv
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from dotenv import dotenv_values

# ─────────────────────────────────────────────────────────────────────────────
# 경로 / 상수
# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent          # ai/src/agents/technical/scripts


def _find_ai_dir(start: Path) -> Path:
    """상위로 올라가며 .env 가 있는 디렉터리(ai/)를 찾는다. 스크립트 위치가 바뀌어도 동작."""
    for p in [start, *start.parents]:
        if (p / ".env").exists():
            return p
    return start.parents[2] if len(start.parents) >= 3 else start  # 폴백


AI_DIR = _find_ai_dir(SCRIPT_DIR)                      # ai (.env 보유 디렉터리)
ENV_PATH = AI_DIR / ".env"                             # ai/.env
OUTPUT_DIR = SCRIPT_DIR / "kis_sample_output"
TOKEN_CACHE = SCRIPT_DIR / ".kis_token.json"           # 토큰 재사용 캐시 (gitignore 대상)

# MVP allowlist — config.md §11 BATTERY_TICKERS 정본과 동일 (kis_mapping §2).
# 이 목록 밖 종목은 테스트하지 않는다.
BATTERY_TICKERS: dict[str, str] = {
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
SINGLE_TICKER = "373220"  # 1단계 단일 종목 검증 대상 (LG에너지솔루션)

# KIS 기간별시세 API (kis_mapping §4)
CHART_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
TR_ID = "FHKST03010100"
PERIODS = ["D", "W", "M"]  # 일봉 / 주봉 / 월봉

# 내부 OHLCV 매핑 (kis_mapping §7). KIS 원본 필드 → 내부 필드.
# 실제 응답 필드명이 다를 수 있으므로, 아래는 "기대 필드명"이고
# 매핑 시 존재 여부를 검사해 실제값 기준으로 확정한다.
FIELD_MAP = {
    "stck_bsop_date": "date",
    "stck_oprc": "open",
    "stck_hgpr": "high",
    "stck_lwpr": "low",
    "stck_clpr": "close",
    "acml_vol": "volume",
    "acml_tr_pbmn": "trading_value",
}
INTERNAL_COLS = ["date", "open", "high", "low", "close", "volume", "trading_value"]

# ── 유량 제한(rate limit) 정책 ────────────────────────────────────────────────
# KIS 실전계좌 REST 유량 제한은 일반적으로 "초당 약 20건" 수준으로 알려져 있다.
# 여기서는 샘플 테스트이므로 안전 마진을 크게 두어 초당 ~3건(호출 간 0.35s)으로 제한한다.
# (개인 계정 + 조회성 API라 굳이 상한을 밀어붙일 이유가 없고, 429/유량초과를 사실상 피하는 게 목적.)
CALL_INTERVAL_SEC = 0.35
# 유량 초과/일시 오류 시 지수 백오프 재시도. (kis_mapping §10: 3회, 백오프 1·2·4초)
MAX_RETRY = 3
BACKOFF_BASE_SEC = 1.0
HTTP_TIMEOUT_SEC = 5.0  # KIS 1회 호출 timeout (config.md §8 = KIS_TIMEOUT_SECONDS)


# ─────────────────────────────────────────────────────────────────────────────
# 인증 정보 로드
# ─────────────────────────────────────────────────────────────────────────────
def _pick(env: dict, *names: str) -> tuple[str | None, str | None]:
    """후보 이름들 중 처음으로 값이 있는 것을 (값, 사용한키) 로 반환. 값은 strip."""
    for n in names:
        v = env.get(n)
        if v and v.strip():
            return v.strip(), n
    return None, None


def load_credentials() -> dict:
    if not ENV_PATH.exists():
        sys.exit(f"[FATAL] .env 를 찾을 수 없습니다: {ENV_PATH}")
    env = dotenv_values(ENV_PATH)

    # 지시서는 KIS 공식 필드명(KIS_APP_KEY/KIS_APP_SECRET)을 요구하지만,
    # 현재 .env 에는 KIS_API_KEY/KIS_API_SECRET 로 들어있다. 양쪽을 모두 허용하되
    # 공식명을 우선한다. 어떤 키를 썼는지 로그로 남겨 kis_client.py 정합성 확인에 쓴다.
    app_key, key_name = _pick(env, "KIS_APP_KEY", "KIS_API_KEY")
    app_secret, sec_name = _pick(env, "KIS_APP_SECRET", "KIS_API_SECRET")
    base_url, _ = _pick(env, "KIS_BASE_URL")

    missing = [n for n, v in [("appkey", app_key), ("appsecret", app_secret), ("KIS_BASE_URL", base_url)] if not v]
    if missing:
        sys.exit(f"[FATAL] .env 에 다음이 없습니다: {', '.join(missing)}")

    print(f"[env] appkey    ← {key_name}")
    print(f"[env] appsecret ← {sec_name}")
    print(f"[env] base_url  = {base_url}")
    if key_name != "KIS_APP_KEY" or sec_name != "KIS_APP_SECRET":
        print("[warn] .env 키 이름이 KIS 공식명(KIS_APP_KEY/KIS_APP_SECRET)과 다릅니다. "
              "본 구현 services/kis_client.py 와 이름을 맞출지 확인 필요.")
    return {"app_key": app_key, "app_secret": app_secret, "base_url": base_url.rstrip("/")}


# ─────────────────────────────────────────────────────────────────────────────
# 접근토큰 발급 / 재사용
# ─────────────────────────────────────────────────────────────────────────────
def get_access_token(creds: dict, client: httpx.Client) -> str:
    """access_token 을 발급하거나, 만료 전이면 캐시에서 재사용한다.

    KIS 토큰은 유효시간(보통 24h)이 있고, 발급 자체에도 유량 제한(분당 1회)이 있으므로
    파일 캐시(.kis_token.json)에 만료시각과 함께 저장해 재실행 시 재사용한다.
    """
    if TOKEN_CACHE.exists():
        try:
            cached = json.loads(TOKEN_CACHE.read_text())
            if cached.get("base_url") == creds["base_url"] and cached.get("expires_at", 0) > time.time() + 60:
                left = int(cached["expires_at"] - time.time())
                print(f"[token] 캐시 재사용 (만료까지 ~{left}s)")
                return cached["access_token"]
        except Exception:
            pass  # 캐시 손상 시 무시하고 새로 발급

    print("[token] 신규 발급 요청 → /oauth2/tokenP")
    resp = client.post(
        f"{creds['base_url']}/oauth2/tokenP",
        json={
            "grant_type": "client_credentials",
            "appkey": creds["app_key"],
            "appsecret": creds["app_secret"],
        },
    )
    if resp.status_code != 200:
        sys.exit(f"[FATAL] 토큰 발급 실패 {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    token = data.get("access_token")
    if not token:
        sys.exit(f"[FATAL] 토큰 응답에 access_token 없음: {data}")

    expires_in = int(data.get("expires_in", 86400))
    TOKEN_CACHE.write_text(json.dumps({
        "access_token": token,
        "base_url": creds["base_url"],
        "expires_at": time.time() + expires_in - 300,  # 5분 여유
    }))
    print(f"[token] 발급 성공 (expires_in={expires_in}s, 캐시 저장)")
    return token


# ─────────────────────────────────────────────────────────────────────────────
# 기간별시세 호출
# ─────────────────────────────────────────────────────────────────────────────
def call_chart(creds: dict, token: str, client: httpx.Client,
               ticker: str, period: str, date_from: str, date_to: str) -> dict:
    """기간별시세 1회 호출. 유량초과/일시오류는 백오프 재시도. 성공 시 응답 JSON 반환."""
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": creds["app_key"],
        "appsecret": creds["app_secret"],
        "tr_id": TR_ID,
        "custtype": "P",  # 개인
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": ticker,
        "FID_INPUT_DATE_1": date_from,
        "FID_INPUT_DATE_2": date_to,
        "FID_PERIOD_DIV_CODE": period,
        "FID_ORG_ADJ_PRC": "0",
    }

    last_err = ""
    for attempt in range(1, MAX_RETRY + 1):
        time.sleep(CALL_INTERVAL_SEC)  # 유량 제한 간격
        try:
            resp = client.get(f"{creds['base_url']}{CHART_PATH}", headers=headers, params=params)
        except httpx.RequestError as e:
            last_err = f"network: {e}"
        else:
            # 429 또는 유량초과 메시지 → 백오프 재시도
            body_snippet = resp.text[:200]
            if resp.status_code == 429 or "초당 거래건수" in resp.text or "EGW00201" in resp.text:
                last_err = f"rate-limit {resp.status_code}: {body_snippet}"
            elif resp.status_code != 200:
                last_err = f"http {resp.status_code}: {body_snippet}"
            else:
                data = resp.json()
                if data.get("rt_cd") != "0":
                    # 정상 아님 (rt_cd!=0). 유량 관련이면 재시도, 그 외엔 즉시 실패 반환.
                    msg = f"rt_cd={data.get('rt_cd')} msg_cd={data.get('msg_cd')} msg1={data.get('msg1')}"
                    if data.get("msg_cd") in ("EGW00201", "EGW00133"):
                        last_err = f"rate/limit: {msg}"
                    else:
                        raise KisApiError(msg)
                else:
                    return data
        backoff = BACKOFF_BASE_SEC * (2 ** (attempt - 1))
        print(f"      재시도 {attempt}/{MAX_RETRY} ({last_err}) → {backoff:.0f}s 대기")
        time.sleep(backoff)
    raise KisApiError(f"최대 재시도 초과: {last_err}")


class KisApiError(Exception):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# 내부 OHLCV 변환
# ─────────────────────────────────────────────────────────────────────────────
def to_internal(rows: list[dict]) -> list[dict]:
    """output2 원본 배열 → 내부 OHLCV 배열. 실제 존재하는 필드만 매핑."""
    out = []
    for r in rows:
        rec = {}
        for kis_field, internal in FIELD_MAP.items():
            rec[internal] = r.get(kis_field)
        out.append(rec)
    return out


def detect_fields(rows: list[dict]) -> dict:
    """output2 첫 원소 기준으로 매핑 대상 필드의 실제 존재 여부를 반환."""
    if not rows:
        return {internal: False for internal in FIELD_MAP.values()}
    first = rows[0]
    return {FIELD_MAP[k]: (k in first) for k in FIELD_MAP}


def sort_direction(rows: list[dict]) -> str:
    """output2 날짜 정렬 방향 판정: 최신우선(desc) / 과거우선(asc) / 불명."""
    dates = [r.get("stck_bsop_date") for r in rows if r.get("stck_bsop_date")]
    if len(dates) < 2:
        return "판정불가(1건 이하)"
    if dates[0] > dates[-1]:
        return "최신→과거 (descending, 최신 우선)"
    if dates[0] < dates[-1]:
        return "과거→최신 (ascending, 과거 우선)"
    return "동일/불명"


def date_span(rows: list[dict]) -> tuple[str, str]:
    dates = sorted(r.get("stck_bsop_date") for r in rows if r.get("stck_bsop_date"))
    return (dates[0], dates[-1]) if dates else ("-", "-")


def save_csv(ticker: str, period: str, internal_rows: list[dict]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{ticker}_{period}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=INTERNAL_COLS)
        w.writeheader()
        w.writerows(internal_rows)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# 날짜 구간 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
def ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def default_range(period: str, today: date) -> tuple[str, str]:
    """타임프레임별 '넓은' 조회 구간. 100건 제한/구간분할 검증을 위해 일부러 크게 잡는다.
       D: 최근 ~1.3년(달력) / W·M: 최근 ~5년."""
    if period == "D":
        return ymd(today - timedelta(days=480)), ymd(today)
    return ymd(today - timedelta(days=365 * 5)), ymd(today)


# ─────────────────────────────────────────────────────────────────────────────
# 1단계 — 단일 종목 상세 검증
# ─────────────────────────────────────────────────────────────────────────────
def verify_single(creds, token, client, today: date) -> dict:
    print("\n" + "=" * 78)
    print(f"[1단계] 단일 종목 상세 검증 — {SINGLE_TICKER} {BATTERY_TICKERS[SINGLE_TICKER]}")
    print("=" * 78)
    summary = {}
    for period in PERIODS:
        d1, d2 = default_range(period, today)
        print(f"\n─── period={period}  구간 {d1}~{d2} ───")
        try:
            data = call_chart(creds, token, client, SINGLE_TICKER, period, d1, d2)
        except KisApiError as e:
            print(f"  [실패] {e}")
            summary[period] = {"ok": False, "error": str(e)}
            continue

        out1 = data.get("output1") or {}
        out2 = data.get("output2") or []

        # output1 원문 (필드명 확인용)
        print("  · output1 원문(필드명 확인용):")
        print("      " + json.dumps(out1, ensure_ascii=False))
        # output2 원문 — 앞 2건 / 뒤 1건만 (정렬 방향·필드명 확인용)
        print(f"  · output2 개수: {len(out2)}")
        if out2:
            print("  · output2[0] 원문:")
            print("      " + json.dumps(out2[0], ensure_ascii=False))
            if len(out2) > 1:
                print("  · output2[-1] 원문:")
                print("      " + json.dumps(out2[-1], ensure_ascii=False))

        direction = sort_direction(out2)
        span = date_span(out2)
        fields = detect_fields(out2)
        has_tr_pbmn = fields.get("trading_value", False)
        capped = len(out2) >= 100

        print(f"  · 날짜 정렬 방향   : {direction}")
        print(f"  · 날짜 범위(실제)  : {span[0]} ~ {span[1]}")
        print(f"  · 100건 제한 도달  : {'예 (>=100건, 구간분할 필요)' if capped else '아니오'}")
        print(f"  · acml_tr_pbmn(거래대금) 존재: {'예' if has_tr_pbmn else '아니오 ✗'}")
        missing_fields = [f for f, present in fields.items() if not present]
        if missing_fields:
            print(f"  · [주의] 기대 필드 중 응답에 없음: {missing_fields}")

        internal = to_internal(out2)
        path = save_csv(SINGLE_TICKER, period, internal)
        print(f"  · CSV 저장: {path.relative_to(AI_DIR)} ({len(internal)}행)")

        summary[period] = {
            "ok": True, "count": len(out2), "direction": direction, "span": span,
            "capped": capped, "has_tr_pbmn": has_tr_pbmn, "fields": fields,
            "out1_keys": list(out1.keys()), "out2_keys": list(out2[0].keys()) if out2 else [],
        }

    # 구간 파라미터 동작 확인: 좁은 과거 구간을 따로 요청해 실제로 그 구간만 오는지 검증
    print("\n─── 구간 파라미터(FID_INPUT_DATE_1/2) 동작 확인 (period=D) ───")
    nd1, nd2 = ymd(today - timedelta(days=60)), ymd(today - timedelta(days=30))
    try:
        ndata = call_chart(creds, token, client, SINGLE_TICKER, "D", nd1, nd2)
        n2 = ndata.get("output2") or []
        nspan = date_span(n2)
        in_range = all(nd1 <= r.get("stck_bsop_date", "") <= nd2 for r in n2 if r.get("stck_bsop_date"))
        print(f"  요청 {nd1}~{nd2} → {len(n2)}건, 실제 {nspan[0]}~{nspan[1]}, 구간내={in_range}")
        summary["range_param_works"] = in_range and len(n2) > 0
    except KisApiError as e:
        print(f"  [실패] {e}")
        summary["range_param_works"] = False
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# 2단계 — 10종목 전체 확장
# ─────────────────────────────────────────────────────────────────────────────
def verify_all(creds, token, client, today: date) -> tuple[list, list]:
    print("\n" + "=" * 78)
    print("[2단계] 10종목 전체 D/W/M 확장 (총 30호출)")
    print("=" * 78)
    results, failures = [], []
    for ticker, name in BATTERY_TICKERS.items():
        for period in PERIODS:
            d1, d2 = default_range(period, today)
            try:
                data = call_chart(creds, token, client, ticker, period, d1, d2)
                out2 = data.get("output2") or []
                if not out2:
                    raise KisApiError("output2 비어있음")
                internal = to_internal(out2)
                save_csv(ticker, period, internal)
                span = date_span(out2)
                row = {
                    "ticker": ticker, "name": name, "period": period,
                    "count": len(out2), "span": span,
                    "direction": sort_direction(out2),
                    "has_tr_pbmn": detect_fields(out2).get("trading_value", False),
                }
                results.append(row)
                print(f"  ✓ {ticker} {name:<12} {period}  {len(out2):>3}건  "
                      f"{span[0]}~{span[1]}  거래대금={'O' if row['has_tr_pbmn'] else 'X'}")
            except KisApiError as e:
                failures.append({"ticker": ticker, "name": name, "period": period, "error": str(e)})
                print(f"  ✗ {ticker} {name:<12} {period}  실패: {e}")
    return results, failures


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    today = datetime.now().date()
    print(f"실행일: {today}  |  대상: 2차전지 {len(BATTERY_TICKERS)}종목  |  API: {TR_ID}")
    creds = load_credentials()

    with httpx.Client(timeout=HTTP_TIMEOUT_SEC) as client:
        token = get_access_token(creds, client)
        single = verify_single(creds, token, client, today)
        results, failures = verify_all(creds, token, client, today)

    # ── 최종 요약 ──
    print("\n" + "=" * 78)
    print("[요약]")
    print("=" * 78)
    print("단일종목(373220) 결과: " + ", ".join(
        f"{p}={'OK' if single.get(p, {}).get('ok') else 'FAIL'}" for p in PERIODS))
    print(f"구간 파라미터 동작: {single.get('range_param_works')}")
    ok_cnt = len(results)
    print(f"10종목 확장: 성공 {ok_cnt}/30, 실패 {len(failures)}")
    if failures:
        print("실패 목록:")
        for f in failures:
            print(f"  - {f['ticker']} {f['name']} {f['period']}: {f['error']}")

    # 타임프레임별 건수/정렬/거래대금 요약 (문서화용)
    print("\n[타임프레임별 관찰(단일종목 기준)]")
    for p in PERIODS:
        s = single.get(p, {})
        if s.get("ok"):
            print(f"  {p}: {s['count']}건, 정렬={s['direction']}, "
                  f"100건제한={'예' if s['capped'] else '아니오'}, "
                  f"거래대금={'존재' if s['has_tr_pbmn'] else '없음'}")

    print(f"\nCSV 산출물: {OUTPUT_DIR.relative_to(AI_DIR)}/  (종목_기간.csv)")
    # 종료코드: 단일종목 3개 다 성공 & 실패 0 이면 0
    single_ok = all(single.get(p, {}).get("ok") for p in PERIODS)
    return 0 if (single_ok and not failures) else 1


if __name__ == "__main__":
    raise SystemExit(main())
