"""기술적 분석 에이전트 — KIS 연동 최소 설정.

값의 정본은 `docs/config.md`이며, 이 파일은 그 문서의 KIS 연동 관련 값을 코드로
1:1 옮긴 것이다. 여기서 값을 새로 설계하지 않는다(튜닝은 config.md 문서 기준).

이 파일이 담는 범위 (config.md 대응 섹션):
  - BATTERY_TICKERS allowlist  ......  config.md §11
  - KIS period 상수 (D/W/M)     ......  config.md §3
  - KIS 재시도/타임아웃 상수     ......  config.md §8
  - .env 기반 KIS 인증정보 로딩  ......  kis_mapping.md §11.1

이 파일이 담지 않는 것 (다음 단계):
  - kis_client 실호출/구간분할, Redis 캐시·TTL, 지표·regime·synthesis·risk·chart 상수,
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
