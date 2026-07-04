"""기술적 분석 에이전트 — KIS 연동 최소 설정.

값의 정본은 `docs/config.md`이며, 이 파일은 그 문서의 KIS 연동 관련 값을 코드로
1:1 옮긴 것이다. 여기서 값을 새로 설계하지 않는다(튜닝은 config.md 문서 기준).

이 파일이 담는 범위 (config.md 대응 섹션):
  - BATTERY_TICKERS allowlist  ......  config.md §11
  - KIS period 상수 (D/W/M)     ......  config.md §3
  - KIS 재시도/타임아웃 상수     ......  config.md §8
  - .env 기반 KIS 인증정보 로딩  ......  kis_mapping.md §11.1
  - 지표 계산 상수              ......  config.md §1 + §2(SUPPORT_LOOKBACK_DAYS)

이 파일이 담지 않는 것 (다음 단계):
  - kis_client 구간분할, Redis 캐시·TTL, regime 임계값(RSI_OVERBOUGHT 등)·synthesis·risk·chart 상수,
    OUT_OF_SCOPE_TICKER 예외/응답 포맷.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────────────────────
# 1. MVP 종목 allowlist (config.md §11 BATTERY_TICKERS 정본과 1:1)
# ─────────────────────────────────────────────────────────────────────────────
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


def is_allowed_ticker(ticker: str) -> bool:
    """MVP allowlist(2차전지 10종목)에 속하는 종목코드인지 판별한다.

    범위 밖 종목의 예외/응답 처리(OUT_OF_SCOPE_TICKER)는 이번 단계 범위가 아니며,
    이후 kis_client/서비스 계층에서 이 함수를 근거로 처리한다.
    """
    return ticker in BATTERY_TICKERS


# ─────────────────────────────────────────────────────────────────────────────
# 2. KIS period 상수 (config.md §3 — FID_PERIOD_DIV_CODE)
#    D/W/M을 KIS에 직접 호출한다. 일봉→주/월봉 리샘플링은 하지 않는다(리샘플 상수 없음).
# ─────────────────────────────────────────────────────────────────────────────
KIS_PERIOD_DAILY = "D"
KIS_PERIOD_WEEKLY = "W"
KIS_PERIOD_MONTHLY = "M"


# ─────────────────────────────────────────────────────────────────────────────
# 3. KIS 복원력 상수 (config.md §8)
#    KIS_TIMEOUT_SECONDS 는 KIS 1회 호출 timeout이다. Backend→AI 전체 60초와는 다른 계층.
#    EGW00201(초당 거래건수 초과) 대응은 이후 kis_client.py 본 구현에서 처리한다.
# ─────────────────────────────────────────────────────────────────────────────
KIS_MAX_RETRIES = 3
KIS_BACKOFF_SECONDS = [1, 2, 4]
KIS_TIMEOUT_SECONDS = 5


# ─────────────────────────────────────────────────────────────────────────────
# 4. KIS 인증정보 로딩 (.env / 환경변수)
#    이 프로젝트의 공식 .env 키: KIS_API_KEY / KIS_API_SECRET / KIS_BASE_URL
#    - 인증정보는 코드에 하드코딩하지 않는다. 반드시 .env(또는 환경변수)에서만 읽는다.
#    - 시세 조회에는 계좌번호가 필요 없으므로 KIS_ACCOUNT_NO는 로딩하지 않는다(kis_mapping §11.1).
# ─────────────────────────────────────────────────────────────────────────────
REQUIRED_ENV_KEYS = ("KIS_API_KEY", "KIS_API_SECRET", "KIS_BASE_URL")
# 이 프로젝트에서 공식 지원하지 않는(혼동 방지용) 키. 존재 시 경고만 낸다.
UNSUPPORTED_ENV_KEYS = ("KIS_APP_KEY", "KIS_APP_SECRET")


@dataclass(frozen=True)
class KISSettings:
    """KIS 시세 조회에 필요한 최소 인증정보. (계좌번호는 포함하지 않는다.)"""
    api_key: str
    api_secret: str
    base_url: str


def _find_env_file() -> Path | None:
    """상위 디렉터리로 올라가며 ai/.env 를 찾는다. 실행 CWD와 무관하게 동작."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if candidate.exists():
            return candidate
    return None


def load_kis_settings() -> KISSettings:
    """.env(또는 환경변수)에서 KIS 인증정보를 읽어 KISSettings로 반환한다.

    - 필수 키(KIS_API_KEY/KIS_API_SECRET/KIS_BASE_URL) 중 하나라도 없으면
      어떤 키가 빠졌는지 명시하며 즉시 실패한다(fail-fast).
    - 구/타 프로젝트 키(KIS_APP_KEY/KIS_APP_SECRET)가 남아 있으면 혼동 방지 경고를 낸다.
    """
    env_path = _find_env_file()
    if env_path is not None:
        # 이미 설정된 실제 환경변수는 .env보다 우선(override=False).
        load_dotenv(env_path, override=False)

    # 공식 미지원 키가 남아 있으면 경고 (fail은 아님).
    leftover = [k for k in UNSUPPORTED_ENV_KEYS if os.getenv(k)]
    if leftover:
        warnings.warn(
            f"[KIS config] 미지원 키가 .env/환경변수에 있습니다: {leftover}. "
            f"이 프로젝트는 {REQUIRED_ENV_KEYS} 만 사용합니다 — 해당 키는 무시됩니다.",
            stacklevel=2,
        )

    values = {k: (os.getenv(k) or "").strip() for k in REQUIRED_ENV_KEYS}
    missing = [k for k, v in values.items() if not v]
    if missing:
        where = f"{env_path}" if env_path else "환경변수(.env 파일 미발견)"
        raise RuntimeError(
            f"[KIS config] 필수 인증정보 누락: {missing}. "
            f"{where} 에 {', '.join(missing)} 를 설정하세요."
        )

    return KISSettings(
        api_key=values["KIS_API_KEY"],
        api_secret=values["KIS_API_SECRET"],
        base_url=values["KIS_BASE_URL"].rstrip("/"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 5. 지표 계산 상수 (config.md §1). indicators/ 모듈이 사용한다.
#    regime 판정 임계값(RSI_OVERBOUGHT/OVERSOLD·NEAR_*·SLOPE_* 등)은 여기 없다 — 7단계 regime에서 추가.
# ─────────────────────────────────────────────────────────────────────────────
MA_WINDOWS = [5, 20, 60]        # 이동평균 기간 (단기/중기/장기)
RSI_PERIOD = 14                 # RSI 계산 기간 (와일더 표준)
BOLLINGER_PERIOD = 20           # 볼린저밴드 기간 (중심선 SMA 기간)
BOLLINGER_STD = 2.0             # 볼린저밴드 표준편차 배수
VOLUME_AVG_WINDOW = 20          # 거래량/거래대금 평균 기간

# support/resistance 탐색 기간 (config.md §2). regime 임계값은 제외하고 이 값만 가져온다.
SUPPORT_LOOKBACK_DAYS = 20      # 주요 지지/저항 탐색 기간


# ─────────────────────────────────────────────────────────────────────────────
# 6. 일봉 regime 판정 상수 (config.md §2). regime/rules.py가 사용한다.
# ─────────────────────────────────────────────────────────────────────────────
RSI_OVERBOUGHT = 70                   # 과열 판정 RSI 상한 (>= 포함)
RSI_OVERSOLD = 35                     # 과매도 반등 판정 RSI 하한 (<= 포함)
MIN_DAILY_BARS = 60                   # 국면 판정 최소 일봉 수 (미만이면 unavailable)

NEAR_BAND_THRESHOLD = 0.98            # 볼밴 상단 근처: 현재가 >= 상단 × 이 값
NEAR_SUPPORT_THRESHOLD_PCT = 0.02     # 지지 근처: 최근 저점과 차이 2% 이내
NEAR_RESISTANCE_THRESHOLD_PCT = 0.02  # 저항 근처: 최근 고점과 차이 2% 이내 (사용은 risk 단계)
REBOUND_WICK_RATIO = 1.5             # 반등 캔들: 아랫꼬리 > 몸통 × 이 값
SLOPE_LOOKBACK_DAYS = 5              # MA 기울기 판정 기간 (우상향/전환)
SLOPE_MIN = 0.0                     # 우상향 최소 기울기 (절대 가격차 기준)


# ─────────────────────────────────────────────────────────────────────────────
# 7. 멀티프레임 regime 보정 상수 (config.md §3). regime/multiframe.py가 사용한다.
#    KIS_PERIOD_* 는 위 §2(2번 섹션)에 이미 정의됨.
# ─────────────────────────────────────────────────────────────────────────────
MIN_WEEKLY_BARS = 12                 # 주봉 추세 판정 최소 봉 수 (미만이면 unavailable)
MIN_MONTHLY_BARS = 6                 # 월봉 추세 판정 최소 봉 수
TREND_SLOPE_LOOKBACK = 4             # 주/월봉 추세 기울기 판정 기간 (몇 봉 전과 비교)
TREND_SIDEWAYS_THRESHOLD_PCT = 0.01  # 상위 추세 sideways 판정 밴드 (변화율 ±1% 이내)
