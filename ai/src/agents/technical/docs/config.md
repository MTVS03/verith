# 5. Config 명세

`docs/config.md` (구현: `config.py`)

에이전트의 모든 설정값을 한 곳에서 관리한다. 규칙·계산·복원력에 쓰이는 상수를 코드에 하드코딩하지 않고 여기서 불러온다. 값을 바꾸면 이 파일만 고치면 되고, 검증 테스트(regime_test 등)도 이 값을 참조한다.

> **전체 원칙 — 구조는 코드, 수치는 config.** 아래 수치는 MVP v1 기준값으로 확정한다. 규칙의 **구조**(어떤 지표를 조합하는가)는 확정이지만, **수치**(임계값·기간·가중치)는 백테스트·오류 분석 결과에 따라 config 변경만으로 조정한다. 로직 코드는 바뀌지 않는다.

## 1. 지표 계산 (indicators)

```python
MA_WINDOWS = [5, 20, 60]        # 이동평균 기간 (단기/중기/장기)
RSI_PERIOD = 14                 # RSI 계산 기간 (와일더 표준)
BOLLINGER_PERIOD = 20           # 볼린저밴드 기간
BOLLINGER_STD = 2.0             # 볼린저밴드 표준편차 배수
VOLUME_AVG_WINDOW = 20          # 거래량 평균 기간
```

*연결: `indicators/`, `regime_rules.md` 지표 계산*
*RSI 14, 볼린저 20/2는 기술적 분석에서 널리 쓰이는 표준값. MVP 초기값으로 사용하고 백테스트로 조정.*

## 2. regime 판정 (regime rules)

```python
RSI_OVERBOUGHT = 70             # 과열 판정 RSI 상한
RSI_OVERSOLD = 35               # 과매도 반등 판정 RSI 하한
MIN_DAILY_BARS = 60             # 국면 판정 최소 봉 수 (미만이면 판단 불가)

# 보조 판정 정의
NEAR_BAND_THRESHOLD = 0.98      # 볼밴 상단 근처: 현재가 >= 상단 × 이 값
NEAR_SUPPORT_THRESHOLD_PCT = 0.02    # 지지 근처: 최근 저점과 차이 2% 이내
NEAR_RESISTANCE_THRESHOLD_PCT = 0.02 # 저항 근처: 최근 고점과 차이 2% 이내
REBOUND_WICK_RATIO = 1.5        # 반등 캔들: 아랫꼬리 > 몸통 × 이 값
SLOPE_LOOKBACK_DAYS = 5         # 기울기 판정 기간 (우상향/전환)
SLOPE_MIN = 0.0                 # 우상향 최소 기울기
SUPPORT_LOOKBACK_DAYS = 20      # 주요 지지/저항 탐색 기간
```

*연결: `regime/rules.py`, `regime_rules.md` 1·3단계, 검증 ②*
*`RSI_OVERSOLD = 35`: 라벨이 "과매도 확정"이 아니라 "과매도 반등 관찰"이므로, 30보다 넓은 35를 MVP 기본값으로 둔다(30 이하만 잡으면 신호가 너무 적게 나옴).*

## 3. 멀티프레임 (multiframe)

```python
KIS_PERIOD_DAILY = "D"         # KIS FID_PERIOD_DIV_CODE 일봉
KIS_PERIOD_WEEKLY = "W"        # KIS FID_PERIOD_DIV_CODE 주봉
KIS_PERIOD_MONTHLY = "M"       # KIS FID_PERIOD_DIV_CODE 월봉
MIN_WEEKLY_BARS = 12           # 주봉 추세 판정 최소 봉 수 (미만이면 unavailable)
MIN_MONTHLY_BARS = 6           # 월봉 추세 판정 최소 봉 수
TREND_SLOPE_LOOKBACK = 4       # 주/월봉 추세 기울기 판정 기간
```

*연결: `regime/multiframe.py`, `services/kis_client.py`, `regime_rules.md` 멀티프레임*
*주봉·월봉은 KIS `inquire-daily-itemchartprice`를 `FID_PERIOD_DIV_CODE=W/M`으로 직접 호출해 받는다. 일봉에서 리샘플로 파생하지 않는다 — 세 타임프레임 모두 KIS 원본 시세.*

## 4. 신호 종합 (synthesis)

```python
# 지표별 가중치 (합 = 1.0)
INDICATOR_WEIGHTS = {
    "moving_average":     0.30,   # 추세 판단의 핵심
    "rsi":                0.20,   # 과열/과매도 보조
    "volume":             0.20,   # 신호 신뢰도 보조
    "support_resistance": 0.20,   # 가격 구조 판단
    "pattern":            0.10,   # 오탐 가능성 커서 낮게 (honest scoping)
}

# signal_score 임계값 (consensus 판정)
SIGNAL_STRONG = 0.5             # |score| >= 0.5  → 우세 (긍정/부정)
SIGNAL_WEAK = 0.3              # 0.3 <= |score| < 0.5 → 약한 (긍정/부정)
                               # |score| < 0.3 → 중립
```

*연결: `synthesis/signal_score.py`, `enums.md` consensus*
*가중치는 지표 제외(데이터 부족) 시 남은 지표로 재정규화한다.*
*가중치는 MVP v1 기준값으로 확정. 이전 목업의 값(예: RSI 0.25)은 폐기하고 이 문서 기준으로 통일한다.*

## 5. 신뢰도 (confidence)

```python
# confidence 계산 요소별 가중치 (합 = 1.0)
# 모든 요소는 "높을수록 confidence가 올라가는" 방향으로 통일한다.
CONFIDENCE_WEIGHTS = {
    "agreement":        0.40,   # 지표 일치도
    "volume_confirm":   0.20,   # 거래량 확인
    "trend_clarity":    0.20,   # 추세 명확도
    "conflict_absence": 0.20,   # 신호 충돌 없음 (충돌 적을수록 높음)
}

# confidence_level 구간 (표시용, DB 저장 안 함)
CONFIDENCE_HIGH = 0.7           # >= 0.7 → 높음
CONFIDENCE_MEDIUM = 0.4         # 0.4 ~ 0.7 → 보통, < 0.4 → 낮음
```

*연결: `synthesis/confidence.py`, `enums.md` confidence_level*
*`conflict_absence`는 신호 충돌이 적을수록 높아지는 값이다(내부적으로 `1 - conflict_score`). 신호 충돌이 클수록 confidence는 낮아진다. 네 요소가 모두 "높을수록 좋음" 방향이라 가중합으로 바로 계산된다.*

## 6. 리스크 (risk)

```python
# 유동성 판정 (둘 중 하나라도 미만이면 low_liquidity)
MIN_AVG_VOLUME = 100_000        # 최근 20일 평균 거래량 하한 (주)
MIN_AVG_TRADING_VALUE = 1_000_000_000  # 최근 20일 평균 거래대금 하한 (원, 10억)
```

*연결: `synthesis/risk.py`, `enums.md` risk_flags (low_liquidity)*
*MVP에서는 거래량 기준과 거래대금 기준을 함께 둔다. **둘 중 하나라도 기준 미만이면 `low_liquidity`를 부여한다**(보수적 기준 — 저가주는 거래량이 많아도 거래대금이 낮을 수 있음). 실제 임계값은 시장 구간·종목군에 따라 백테스트로 조정한다.*

## 7. 데이터 캐시 (Redis TTL)

```python
CACHE_TTL_DAILY = None          # 과거 일봉: expire 미설정 (안 바뀜)
CACHE_TTL_WEEKLY = None         # 주봉: expire 미설정
CACHE_TTL_MONTHLY = None        # 월봉: expire 미설정
CACHE_TTL_TODAY = 60 * 15       # 오늘 일봉: 15분
CACHE_TTL_MINUTE = 60           # 분봉: 1분 (lazy, 1d Beta/Future Work용·MVP 필수 아님)

# 캐시 키 패턴
CACHE_KEY_DAILY = "ohlcv:daily:{ticker}"
CACHE_KEY_WEEKLY = "ohlcv:weekly:{ticker}"
CACHE_KEY_MONTHLY = "ohlcv:monthly:{ticker}"
CACHE_KEY_TODAY = "ohlcv:today:{ticker}"
CACHE_KEY_MINUTE = "ohlcv:minute:{ticker}"  # 1d 정식 지원 시 사용 (chart_annotation_spec §3.1)
```

*연결: `services/cache_service.py`. 일봉·주봉·월봉은 KIS D/W/M 원본을 각각 캐시한다(리샘플 파생 없음).*
*`CACHE_TTL_* = None`은 Redis expire를 설정하지 않는다는 의미다(만료 없이 보관, 오늘 일봉만 갱신).*

## 8. 복원력 (resilience)

```python
# KIS 재시도
KIS_MAX_RETRIES = 3             # 최대 재시도 횟수
KIS_BACKOFF_SECONDS = [1, 2, 4] # 지수 백오프 대기 (초)
KIS_TIMEOUT_SECONDS = 5         # 호출 타임아웃
# stale 캐시 허용 기간 — 타임프레임별 (일봉 1거래일, 주/월봉은 주기가 길어 더 관대)
STALE_CACHE_MAX_AGE_BY_PERIOD = {
    "D": 1,     # 1거래일
    "W": 7,     # 약 1주
    "M": 31,    # 약 1개월
}
```

*연결: `services/kis_client.py`(재시도·timeout)·`supervisor/technical_supervisor.py`(폴백 분기), UseCase T2*
*`STALE_CACHE_MAX_AGE_BY_PERIOD`의 D는 일봉(1거래일) 기준. 주/월봉(W·M) 신선도 기준은 KIS 실제 응답·갱신 주기 확인 후 확정한다(kis_mapping §11 TODO).*

## 9. 검증·재생성 (verification)

```python
REGEN_MAX_COUNT = 1             # 검증 ③ 실패 시 재생성 최대 횟수
# 재생성 후에도 실패 → 템플릿 폴백 (LLM 문장 버림)
```

*연결: `supervisor/technical_supervisor.py` 재생성 루프, `observability/trajectory_eval.py`, UseCase T6*
*금융 리포트에서 LLM 라벨 왜곡 시 무한 재시도하지 않는다. 1회 재생성 후 실패하면 템플릿으로 안전하게 폴백한다.*

## 10. 차트 (charts)

```python
CHART_PERIODS = ["3m", "1y", "5y"]   # 기간 토글 (1d는 Beta, chart_annotation_spec §3.1)
# 3m: 일봉 / 1y: 일봉·주봉 / 5y: 주봉·월봉

# 차트 annotation 계산 상수 (chart_annotation_spec.md)
VOLUME_SPIKE_MULTIPLIER = 2.0          # 거래량 급증: 20봉 평균 × 배수
TRADING_VALUE_SPIKE_MULTIPLIER = 2.0   # 거래대금 급증 배수
BOX_LOOKBACK_DAYS = 40                 # 박스권 탐색 기간
BOX_RANGE_THRESHOLD_PCT = 0.12         # 박스권 상·하단 범위 허용 폭
BOX_MIN_TOUCH_COUNT = 2                # 박스권 왕복 최소 횟수
CUP_LOOKBACK_DAYS = 120                # 컵앤핸들 탐색 기간
CUP_MIN_DEPTH_PCT = 0.10               # 컵 최소 깊이
CUP_MAX_DEPTH_PCT = 0.40               # 컵 최대 깊이
HANDLE_MAX_PULLBACK_PCT = 0.15         # 핸들 최대 되돌림
```

*연결: `charts/chart_builder.py`, `enums.md` period, `chart_annotation_spec.md`*
*차트 급증 배수(`VOLUME_SPIKE_MULTIPLIER`)는 차트 표시용이며, 유동성 판정(`MIN_AVG_VOLUME`/`MIN_AVG_TRADING_VALUE`, §6)과는 별개다. 박스·컵앤핸들 값은 패턴 후보 탐지용 MVP 기본값으로, 오류 분석으로 조정한다.*

---

## 11. MVP 종목 범위 (allowlist)

MVP 조사 범위는 **2차전지 10종목**으로 제한한다. KIS API는 섹터 단위 조회가 아니라 종목코드 단위 조회이므로, 섹터 제한은 KIS가 아니라 **서비스 레벨의 allowlist**로 수행한다.

```python
BATTERY_TICKERS = {
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
```

allowlist 밖 종목 요청은 조회하지 않고 범위 밖으로 처리한다.

```python
if ticker not in BATTERY_TICKERS:
    raise OutOfScopeTickerError("MVP 조사 범위 밖 종목입니다.")
```

*연결: `services/kis_client.py`, `kis_mapping.md` §2, `api_spec.md`(OUT_OF_SCOPE_TICKER)*

종목 마스터를 DB로 공유하는 것은 MVP 범위가 아니다 — allowlist는 자주 바뀌지 않는 **설정값**이므로 config에 둔다. 팀 공통 종목 마스터가 필요해지면 그것은 이 에이전트의 `schema.md`가 아니라 팀 공통 스키마 영역에서 다룬다.

---

## 값 조정 규약

1. **구조는 코드, 수치는 config.** 로직(어떤 지표를 조합하는가)은 코드에, 임계값·기간·가중치는 여기에. 튜닝이 config 수정만으로 끝나게 한다.
2. **가중치 합은 1.0.** `INDICATOR_WEIGHTS`, `CONFIDENCE_WEIGHTS`는 합이 1.0이어야 한다(코드에서 검증).
3. **confidence 요소는 모두 같은 방향.** 네 요소 전부 "높을수록 confidence 상승"으로 통일(`conflict_absence` 사용). 감점 요소를 그대로 더하지 않는다.
4. **값 변경 시 테스트 동반.** 상수를 바꾸면 관련 검증 테스트(regime_test 등)의 기대값도 함께 검토한다.
5. **전부 MVP v1 기준값.** 위 수치는 기술적 분석 표준·합리적 기본값이며, 백테스트·오류 분석으로 config 변경만으로 조정한다. 이전 목업 값과 충돌 시 이 문서를 기준으로 통일한다.
