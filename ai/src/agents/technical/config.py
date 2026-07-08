"""기술적 분석 에이전트 — KIS 연동 최소 설정.

값의 정본은 `docs/config.md`이며, 이 파일은 그 문서의 KIS 연동 관련 값을 코드로
1:1 옮긴 것이다. 여기서 값을 새로 설계하지 않는다(튜닝은 config.md 문서 기준).

이 파일이 담는 범위 (config.md 대응 섹션):
  - BATTERY_TICKERS dev/smoke 표시명 fallback + 지원 정책 함수  ......  config.md §11
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
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────────────────────
# 1. dev/smoke/test 표시명 fallback (production gate·정본 아님)
# ─────────────────────────────────────────────────────────────────────────────
# ⚠️ 이 상수는 더 이상 **production allowlist gate 나 종목명 canonical source 가 아니다.**
# production 에서 종목 정본(코드·이름·시장)은 backend canonical stock context 가 담당하고,
# supervisor 가 `stock_name` 을 technical 입력으로 주입한다(contracts §TechnicalAgentInput). 이 map 은
# dev/smoke/test 에서 종목명이 주입되지 않았을 때의 **표시명 fallback** 으로만 남는다(2차전지 대표 10종).
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


def is_supported_ticker(ticker: str) -> bool:
    """종목 지원 정책의 **단일 경계**. 기본 정책: **형식상 유효한 ticker 는 모두 지원**한다.

    6자리 형식 검증은 입력 계약(`TechnicalAgentInput` validator)이 담당한다. 종목 지원 여부는
    **allowlist membership 이 아니라 실제 데이터/결과 상태(data_status)** 로 표현한다 — BATTERY_TICKERS
    소속 여부에 더 이상 의존하지 않는다. 향후 시장/유형 정책이 필요하면 gate 를 흩뿌리지 말고 이 함수에서만
    확장한다.
    """
    return bool(ticker)  # 비어있지 않은(계약상 6자리) ticker 는 지원


def dev_stock_name(ticker: str) -> str | None:
    """dev/smoke/test 표시명 fallback (production 정본 아님).

    production 종목명 정본은 backend canonical stock context 이며 supervisor 가 `stock_name` 으로
    주입한다. 이 함수는 stock_name 이 주입되지 않은 dev 경로에서만 표시명을 보조로 제공한다.
    """
    return BATTERY_TICKERS.get(ticker)


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
    """KIS 시세 조회에 필요한 최소 인증정보. (계좌번호는 포함하지 않는다.)

    api_key·api_secret은 repr에서 제외한다 — repr(settings)·로그에 비밀값이 노출되지 않도록
    (technical_coding_guidelines §2.2·§13.2).
    """
    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)
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
# 이동평균은 역할(단기/중기/장기) 의미 상수로 정의하고 MA_WINDOWS는 파생시킨다.
# 소비 코드는 mas[5] 같은 하드코딩 키가 아니라 이 상수로 접근한다(refactor/technical-ma-window-config).
MA_SHORT_WINDOW = 5             # 단기 이동평균
MA_MID_WINDOW = 20             # 중기 이동평균
MA_LONG_WINDOW = 60            # 장기 이동평균
MA_WINDOWS = [MA_SHORT_WINDOW, MA_MID_WINDOW, MA_LONG_WINDOW]  # 파생 (단기 < 중기 < 장기)
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


# ─────────────────────────────────────────────────────────────────────────────
# 7.1 KIS 구간 분할 조회 상수 (config.md §8.1). services/kis_client.py가 사용한다.
#     CHART_PERIOD_DAYS(§11, 프론트 표시 slice)와 다른 축: 이건 원천 데이터 fetch 기간.
# ─────────────────────────────────────────────────────────────────────────────
KIS_FETCH_LOOKBACK_DAYS = {           # 타임프레임별 확보할 데이터 기간(달력일)
    "D": 460,                         # 1y(365) + 60MA 여유 약 90일
    "W": 2250,                        # 5y(1825) + 60주 MA 여유 약 420일
    "M": 1900,                        # monthly_trend/regime 및 보조용 5년 수준
}
KIS_FETCH_CHUNK_DAYS = {              # 단일 호출 100건 제한 회피용 청크 폭(달력일)
    "D": 100,                         # ≈68거래일 < 100건
    "W": 600,                         # ≈85주 < 100건
    "M": 1900,                        # ≈60개월 < 100건 (1청크)
}
KIS_MAX_CHUNKS = 10                   # 무한 루프 방지 상한


# ─────────────────────────────────────────────────────────────────────────────
# 7.2 데이터 캐시 (Redis) 상수 (config.md §7·§8). services/cache_service.py가 사용한다.
#     D/W/M OHLCV 원본을 timeframe별로 캐시한다(리샘플 파생 없음). 1D 분봉 캐시는 범위 밖.
#     key는 as_of를 포함하지 않는다(문서 계약) — as_of 정합은 entry에 저장한 as_of 비교로 보장한다.
# ─────────────────────────────────────────────────────────────────────────────
CACHE_KEY_BY_PERIOD = {               # Redis key 패턴(ticker만 포맷). D/W/M → daily/weekly/monthly
    "D": "ohlcv:daily:{ticker}",
    "W": "ohlcv:weekly:{ticker}",
    "M": "ohlcv:monthly:{ticker}",
}
# primary(fresh) 서빙 판정: fetched_at 나이 ≤ 이 값이면 KIS 없이 캐시를 그대로 쓴다.
# 시계열이 오늘/당주/당월 봉을 포함해 가변이므로 "오늘 일봉 15분"(config.md §7 CACHE_TTL_TODAY)을 쓴다.
CACHE_FRESH_TTL_SECONDS = 60 * 15     # 15분
# stale 폴백 허용 기간(일). Redis expire도 이 값으로 두어 그 안엔 stale로 재사용 가능하게 한다.
STALE_CACHE_MAX_AGE_BY_PERIOD = {     # config.md §8
    "D": 1,     # 1거래일
    "W": 7,     # 약 1주
    "M": 31,    # 약 1개월
}
CACHE_SECONDS_PER_DAY = 86400         # stale 일수 → Redis expire 초 환산


# ─────────────────────────────────────────────────────────────────────────────
# 7.3 Trace 로깅 상수 (trace_schema.md §13). observability/trace_logger.py가 사용한다.
#     관측 전용 — 운영 결선(JSONL path·config sink 자동 생성)은 AI endpoint 브랜치에서 한다.
# ─────────────────────────────────────────────────────────────────────────────
TRACE_MAX_ERROR_MESSAGE_LENGTH = 300  # trace error message 최대 길이(secret/원문 박제 방지·축약)


# ─────────────────────────────────────────────────────────────────────────────
# 8. 신호 종합 상수 (config.md §4). synthesis/signal_score.py가 사용한다.
# ─────────────────────────────────────────────────────────────────────────────
INDICATOR_WEIGHTS = {                # 지표별 가중치 (합 = 1.0)
    "moving_average": 0.30,
    "rsi": 0.20,
    "volume": 0.20,
    "support_resistance": 0.20,
    "pattern": 0.10,
}
SIGNAL_STRONG = 0.5                  # |score| >= 0.5 → 우세 (긍정/부정)
SIGNAL_WEAK = 0.3                   # 0.3 <= |score| < 0.5 → 약한 (긍정/부정)


# ─────────────────────────────────────────────────────────────────────────────
# 9. 신뢰도 상수 (config.md §5). synthesis/confidence.py가 사용한다.
# ─────────────────────────────────────────────────────────────────────────────
CONFIDENCE_WEIGHTS = {               # confidence 요소별 가중치 (합 = 1.0, 전부 "높을수록 좋음")
    "agreement": 0.40,
    "volume_confirm": 0.20,
    "trend_clarity": 0.20,
    "conflict_absence": 0.20,
}
CONFIDENCE_HIGH = 0.7               # >= 0.7 → high
CONFIDENCE_MEDIUM = 0.4            # >= 0.4 → medium, 그 외 low (표시용 파생값, DB 저장 안 함)


# ─────────────────────────────────────────────────────────────────────────────
# 10. 리스크 상수 (config.md §6). synthesis/risk.py가 사용한다.
#     둘 중 하나라도 미만이면 low_liquidity (보수적 기준).
# ─────────────────────────────────────────────────────────────────────────────
MIN_AVG_VOLUME = 100_000            # 최근 20일 평균 거래량 하한 (주)
MIN_AVG_TRADING_VALUE = 1_000_000_000  # 최근 20일 평균 거래대금 하한 (원, 10억)


# ─────────────────────────────────────────────────────────────────────────────
# 11. 차트 상수 (config.md §10). charts/chart_builder.py가 사용한다.
#     cup/handle 상수는 MVP 미구현이지만 정본 포팅 차원에서 함께 둔다.
# ─────────────────────────────────────────────────────────────────────────────
CHART_PERIODS = ["3m", "1y", "5y"]     # 기간 토글 (1d는 Beta)
CHART_PERIOD_DAYS = {                   # 기간별 candle slice 창 (마지막 candle date 기준 최근 N일)
    "3m": 90,
    "1y": 365,
    "5y": 1825,
}
VOLUME_SPIKE_MULTIPLIER = 2.0          # 거래량 급증: 20봉 평균 × 배수
TRADING_VALUE_SPIKE_MULTIPLIER = 2.0   # 거래대금 급증 배수
BOX_LOOKBACK_DAYS = 40                 # 박스권 탐색 기간
BOX_RANGE_THRESHOLD_PCT = 0.12         # 박스권 상·하단 범위 허용 폭
BOX_MIN_TOUCH_COUNT = 2                # 박스권 상·하단 각각 근접 최소 봉 수
BOX_MIN_ALTERNATIONS = 2               # 상단↔하단 zone 전환 최소 횟수(왕복 — 단방향 추세 배제)
# 컵앤핸들 후보(chart_annotation_spec §13). 탐색 창은 timeframe별 **봉(BARS)** 기준으로 분리한다
# (같은 120이라도 일봉=120일·주봉=120주로 의미가 달라 DAYS 이름은 쓰지 않는다). 1y=일봉·5y=주봉만 대상,
# 3m 제외. charts/chart_builder.py::_cup_handle_annotations가 사용한다(annotation-only, signal 미반영).
CUP_HANDLE_DAILY_LOOKBACK_BARS = 120       # 1y 일봉 탐색 창(봉)
CUP_HANDLE_WEEKLY_LOOKBACK_BARS = 78       # 5y 주봉 탐색 창(봉)
CUP_HANDLE_RIM_TOLERANCE_PCT = 0.05        # 좌/우 rim 가격 차 허용(≤5%) — 회복 정도
CUP_HANDLE_MIN_DEPTH_PCT = 0.10            # 컵 최소 깊이(rim 대비)
CUP_HANDLE_MAX_DEPTH_PCT = 0.40            # 컵 최대 깊이(rim 대비)
CUP_HANDLE_MIN_HANDLE_PULLBACK_PCT = 0.02  # 핸들 **최소** 되돌림(실제 조정 존재 강제 — no-handle 배제)
CUP_HANDLE_MAX_HANDLE_PULLBACK_PCT = 0.15  # 핸들 최대 되돌림(우측 rim 대비)
CUP_HANDLE_MIN_HANDLE_BARS = 5             # 핸들 최소 길이(봉)
CUP_HANDLE_MAX_HANDLE_BARS = 30            # 핸들 최대 길이(봉)
CUP_HANDLE_MIN_BOTTOM_BARS = 3            # 둥근 저점 최소 봉 수(단봉 V자 spike 배제)
CUP_HANDLE_BOTTOM_TOLERANCE_PCT = 0.03   # bottom 근처 판정 폭(이 안에 MIN_BOTTOM_BARS 이상)

# annotation 중복 제거 창 — candle(봉) index 거리 기준 (chart_annotation_spec §8.4).
ANNOTATION_DEDUP_BARS = {
    "3m": 5,    # 일봉 5봉
    "1y": 10,   # 일봉 10봉
    "5y": 4,    # 주봉 4봉 (≈4주)
}


# ─────────────────────────────────────────────────────────────────────────────
# 12. 검증·재생성 (config.md §9). supervisor의 interpret 재생성 루프가 사용한다.
# ─────────────────────────────────────────────────────────────────────────────
REGEN_MAX_COUNT = 1                     # 검증 ③ 실패 시 재생성 최대 횟수 (초과 시 template fallback)


# ─────────────────────────────────────────────────────────────────────────────
# 13. 1D intraday(Beta) 활성화 플래그 (chart_annotation_spec §3.1, kis_mapping §12)
#     True면 supervisor가 intraday_fetcher 미주입 시 기본 KIS 분봉 fetcher(fetch_minute_ohlcv)를
#     사용한다(C안 default-on gate). Beta·호출량/rate limit 부담 때문에 **기본 False**.
#     .env/환경변수 `INTRADAY_FETCH_ENABLED`로 override 가능(새 KIS env key 아님).
# ─────────────────────────────────────────────────────────────────────────────
_ENV_BOOL_TRUE = frozenset({"1", "true", "yes", "on"})
_ENV_BOOL_FALSE = frozenset({"0", "false", "no", "off", ""})


def _env_bool(name: str, *, default: bool = False) -> bool:
    """환경변수(.env 포함) 값을 bool로 파싱한다.

    미설정 → default. true 계열(1/true/yes/on) → True, false 계열(0/false/no/off/빈문자열) → False.
    인식할 수 없는 값은 **조용히 True로 두지 않고** 경고 후 False로 처리한다(운영 안전·config warn 스타일).
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _ENV_BOOL_TRUE:
        return True
    if value in _ENV_BOOL_FALSE:
        return False
    warnings.warn(
        f"[config] {name}={raw!r} 는 인식할 수 없는 bool 값입니다 — 운영 안전을 위해 False로 처리합니다.",
        stacklevel=2,
    )
    return False


# .env(있으면)를 로드해 override를 반영한다(override=False — 실제 환경변수 우선). 기본은 반드시 False.
_intraday_env_file = _find_env_file()
if _intraday_env_file is not None:
    load_dotenv(_intraday_env_file, override=False)
INTRADAY_FETCH_ENABLED: bool = _env_bool("INTRADAY_FETCH_ENABLED", default=False)

# ─────────────────────────────────────────────────────────────────────────────
# 14. 1D intraday(Beta) 판단 상수 (config.md §12). intraday builder/synthesis/kis_client가 사용한다.
#     계산 모듈에 흩어져 있던 상수를 여기로 모은 정본이다. **값은 이동 전과 동일** —
#     이 값들은 아직 실측 튜닝 전(Beta)이며, 후속 튜닝 대상이다(변경 시 이 표만 고치면 됨).
#     주의: threshold 단위가 %(등락률)와 비율(레인지)로 섞여 있다 — 아래 주석 단위를 지킬 것.
# ─────────────────────────────────────────────────────────────────────────────
# charts/intraday_chart_builder.py · intraday_context_builder.py
INTRADAY_SHORT_MA_WINDOW: int = 5              # 장중 단기 이동평균 창(분봉 개수)
INTRADAY_VOLUME_SPIKE_MULTIPLIER: float = 2.0  # 직전 분봉 대비 volume_spike 판정 배수
# synthesis/intraday_alignment.py — 장중 regime hint/방향 판정 임계값
INTRADAY_VOLATILITY_RETURN_THRESHOLD: float = 3.0   # |당일 등락률| ≥ 3%(퍼센트) → volatile
INTRADAY_VOLATILITY_RANGE_THRESHOLD: float = 0.05   # 당일 레인지 폭 ≥ 전일종가 5%(비율) → volatile
INTRADAY_DIRECTION_RETURN_THRESHOLD: float = 0.5    # |등락률| ≥ 0.5%(퍼센트) → 방향 1표
INTRADAY_HIGH_RANGE_POSITION_THRESHOLD: float = 0.66  # 레인지 위치 ≥ 0.66(비율) → 상방 1표
INTRADAY_LOW_RANGE_POSITION_THRESHOLD: float = 0.34   # 레인지 위치 ≤ 0.34(비율) → 하방 1표
INTRADAY_DIRECTION_MIN_AGREEMENT: int = 2           # 최소 2개 지표 합의해야 방향 확정
# synthesis/intraday_adjustment.py · schemas/intraday.py — 보정 한도/개수
INTRADAY_CONFIDENCE_ADJUSTMENT_CAP: float = 0.05  # confidence/signal_score 보정 절대값 상한(±)
INTRADAY_RISK_NOTE_MAX_COUNT: int = 3             # intraday risk_notes 최대 개수
# services/kis_client.py — 분봉 역방향 페이징 상한
INTRADAY_MINUTE_MAX_CALLS: int = 20               # 30건×20 ≈ 600봉(1일 ~391) — 무한 루프 방지 상한
INTRADAY_MARKET_OPEN_HHMMSS: str = "090000"       # 이 시각 이전으로는 더 역방향 조회하지 않는다


# ─────────────────────────────────────────────────────────────────────────────
# 15. OpenAI LLM client 설정 (services/openai_llm_client.py가 사용한다).
#     .env(배포/실험별) = API key(secret) + MODEL(환경마다 갈리는 선택값). 코드에 값을 박제하지
#     않고 반드시 .env/환경변수에서 읽는다(technical_coding_guidelines §2.2·§13.2). MODEL은
#     import 시점이 아니라 load_openai_settings()에서 .env 로드 후 읽어야 실제로 override가 먹는다.
#     아래 timeout/max_retries/temperature/max_tokens/store는 secret도 환경차도 아닌 "튜닝/안전 상수"
#     이므로 여기(코드)에 둔다 — KIS_TIMEOUT_SECONDS와 같은 급이다(.env에 넣지 않는다).
#     안전 정책: SDK 재시도는 끄고(max_retries=0) agent-level 재생성/fallback을 쓴다 — SDK retry는
#     중복이자 60초 API 계약(api_spec §)을 초과할 위험이 있다. store=False로 OpenAI 측 저장을 끈다
#     (stateless). 총 60초 deadline 완전 보장(호출 간 deadline 전파)은 후속 AI endpoint 범위.
#     runtime wiring(run_technical_agent 자동 생성)은 이 브랜치 범위 밖 — 후속 AI endpoint에서 주입.
# ─────────────────────────────────────────────────────────────────────────────
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"    # 키 "이름"만(값 아님) — 값은 .env
OPENAI_MODEL_ENV = "OPENAI_MODEL"        # 모델 "이름"만 — 값은 .env(단일 출처, 코드에 기본값 없음)
OPENAI_TIMEOUT_SECONDS: float = 20.0     # 1회 호출 timeout(초) — 60초 계약 안에서 보수적 하향
OPENAI_MAX_RETRIES: int = 0              # SDK 재시도 끔 — agent-level 재생성/template fallback 우선
OPENAI_TEMPERATURE: float | None = 0.0   # None이면 요청 파라미터에서 생략 — 튜닝 상수(코드)
OPENAI_MAX_OUTPUT_TOKENS: int = 1200     # 응답 최대 토큰(보수적 기본) — 튜닝 상수(코드)
OPENAI_STORE: bool = False               # OpenAI 측 application state 저장 끔(stateless). 분석 이력은 backend DB.


@dataclass(frozen=True)
class OpenAiSettings:
    """.env에서 읽는 OpenAI 설정. api_key는 repr에서 제외(로그/repr 노출 방지, §13.2)."""
    api_key: str = field(repr=False)
    model: str


def load_openai_settings() -> OpenAiSettings:
    """.env(또는 환경변수)에서 OpenAI api_key·model을 읽어 반환한다(fail-fast).

    KIS(§4)와 동일하게 코드에 하드코딩하지 않는다. **model도 .env가 단일 출처**이며 코드 기본값을
    두지 않는다(중복 방지). 누락 시 어디에 무엇을 넣어야 하는지 명시하며 즉시 실패한다 —
    이 config error는 client 생성 시점 오류이며 LlmCallError(호출 실패)와 구분된다.
    반환값(키 문자열)은 로그·trace·repr 어디에도 남기지 않는다(dataclass repr에서 제외)."""
    env_path = _find_env_file()
    if env_path is not None:
        load_dotenv(env_path, override=False)  # 실제 환경변수가 .env보다 우선
    api_key = (os.getenv(OPENAI_API_KEY_ENV) or "").strip()
    model = (os.getenv(OPENAI_MODEL_ENV) or "").strip()
    missing = [name for name, val in ((OPENAI_API_KEY_ENV, api_key), (OPENAI_MODEL_ENV, model)) if not val]
    if missing:
        where = f"{env_path}" if env_path else "환경변수(.env 파일 미발견)"
        raise RuntimeError(
            f"[OpenAI config] 필수 설정 누락: {missing}. {where} 에 {', '.join(missing)} 를 설정하세요."
        )
    return OpenAiSettings(api_key=api_key, model=model)


# ─────────────────────────────────────────────────────────────────────────────
# 16. Technical Agent 전체 실행 예산 (api_spec.md §10). AI endpoint가 Deadline으로 사용한다.
#     Backend→AI 계약 timeout은 60초 — 그보다 먼저 AI가 504를 돌려주도록 내부 예산은 55초로 둔다
#     (직렬화·error response 여유). cooperative deadline이라 실행 중 sync 작업을 즉시 죽이진 못하고
#     다음 stage check 지점에서 멈춘다(endpoint의 asyncio.wait_for가 응답 시간까지 바운딩).
# ─────────────────────────────────────────────────────────────────────────────
TECHNICAL_AGENT_TIMEOUT_SECONDS: float = 55.0  # 내부 budget(< 60초 계약). endpoint Deadline.after()에 사용
