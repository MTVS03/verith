# 5. Config 명세

`docs/config.md` (구현: `config.py`)

에이전트의 모든 설정값을 한 곳에서 관리한다. 규칙·계산·복원력에 쓰이는 상수를 코드에 하드코딩하지 않고 여기서 불러온다. 값을 바꾸면 이 파일만 고치면 되고, 검증 테스트(regime_test 등)도 이 값을 참조한다.

> **전체 원칙 — 구조는 코드, 수치는 config.** 아래 수치는 MVP v1 기준값으로 확정한다. 규칙의 **구조**(어떤 지표를 조합하는가)는 확정이지만, **수치**(임계값·기간·가중치)는 백테스트·오류 분석 결과에 따라 config 변경만으로 조정한다. 로직 코드는 바뀌지 않는다.

## 1. 지표 계산 (indicators)

```python
# 이동평균은 역할(단기/중기/장기) 의미 상수로 정의하고, MA_WINDOWS는 여기서 파생한다.
MA_SHORT_WINDOW = 5             # 단기 이동평균
MA_MID_WINDOW = 20             # 중기 이동평균
MA_LONG_WINDOW = 60            # 장기 이동평균
MA_WINDOWS = [MA_SHORT_WINDOW, MA_MID_WINDOW, MA_LONG_WINDOW]  # 파생 (단기 < 중기 < 장기)

RSI_PERIOD = 14                 # RSI 계산 기간 (와일더 표준)
BOLLINGER_PERIOD = 20           # 볼린저밴드 기간
BOLLINGER_STD = 2.0             # 볼린저밴드 표준편차 배수
VOLUME_AVG_WINDOW = 20          # 거래량 평균 기간
```

*연결: `indicators/`, `regime_rules.md` 지표 계산*
*RSI 14, 볼린저 20/2는 기술적 분석에서 널리 쓰이는 표준값. MVP 초기값으로 사용하고 백테스트로 조정.*

> **`MA_SHORT_WINDOW`·`MA_MID_WINDOW`·`MA_LONG_WINDOW`는 각각 단기·중기·장기 이동평균 역할을 정의한다.** `MA_WINDOWS`는 이 세 역할 상수에서 파생된다(`[MA_SHORT_WINDOW, MA_MID_WINDOW, MA_LONG_WINDOW]`). **기본값은 5 / 20 / 60**이다.
>
> 값은 바꿀 수 있으나 **세 값은 반드시 단기 < 중기 < 장기 역할을 유지**해야 한다(예: `10 / 30 / 90`). 소비 코드(`indicators`·`regime/rules.py`·`synthesis/signal_score.py`·`charts/chart_builder.py`·`nodes/indicator_calculate.py`)는 `mas[5]` 같은 **하드코딩 키 대신 역할 상수(`mas[MA_SHORT_WINDOW]` 등)로 접근**하므로, window 값을 바꿔도 `KeyError` 없이 동작한다. 단, window를 바꾸면 골든크로스·정배열 등 **분석 의미는 달라질 수 있다**(값 변경은 분석 튜닝, 상수화는 구조 정리 — 별개다).

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
TREND_SLOPE_LOOKBACK = 4       # 주/월봉 추세 기울기 판정 기간 (몇 봉 전과 비교)
TREND_SIDEWAYS_THRESHOLD_PCT = 0.01  # 상위 추세 sideways 판정 밴드 (변화율 ±1% 이내)
```

*연결: `regime/multiframe.py`, `services/kis_client.py`, `regime_rules.md` 멀티프레임*
*주봉·월봉은 KIS `inquire-daily-itemchartprice`를 `FID_PERIOD_DIV_CODE=W/M`으로 직접 호출해 받는다. 일봉에서 리샘플로 파생하지 않는다 — 세 타임프레임 모두 KIS 원본 시세.*
*주/월봉 추세는 절대 가격차가 아니라 **변화율**로 본다: `slope_pct = (최신 종가 − TREND_SLOPE_LOOKBACK봉 전 종가) / 그 종가`. `slope_pct > +TREND_SIDEWAYS_THRESHOLD_PCT`면 up, `< −TREND_SIDEWAYS_THRESHOLD_PCT`면 down, 그 사이면 sideways. 이 밴드가 없으면(SLOPE_MIN=0 기준) 실데이터에서 sideways가 거의 나오지 않아 도입한다. 일봉 regime의 MA 기울기 판정은 `SLOPE_MIN=0.0`(§2)을 그대로 쓰며 이 값과 무관하다.*

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

### 4.1 지표별 signal 산출 규칙 (positive / neutral / negative)

각 지표는 원천 계산값(§1 indicators)을 아래 규칙으로 `Signal`(positive/neutral/negative)로 확정한다. **코드가 확정하며 LLM은 개입하지 않는다.** 매수/매도 표현을 쓰지 않는다.

| indicator | positive | negative | neutral |
| --- | --- | --- | --- |
| `moving_average` | `close > 20MA` AND `5MA > 20MA` | `close < 20MA` AND `5MA < 20MA` | 그 외 |
| `rsi` | `50 < RSI < RSI_OVERBOUGHT` | `RSI_OVERSOLD < RSI < 50` | `RSI ≥ RSI_OVERBOUGHT` 또는 `RSI ≤ RSI_OVERSOLD` 또는 `RSI == 50` |
| `volume` | 최신봉 상승 AND `volume_ratio ≥ 1` | 최신봉 하락 AND `volume_ratio ≥ 1` | `volume_ratio < 1` 또는 계산 불가 |
| `support_resistance` | 지지 근처(±`NEAR_SUPPORT_THRESHOLD_PCT`) | 저항 근처(±`NEAR_RESISTANCE_THRESHOLD_PCT`) | 그 외 |
| `pattern` | `is_bullish` | `is_bearish` | 도지 또는 판단 불가 |

- **RSI 극단은 방향 신호로 쓰지 않는다** — `RSI ≥ RSI_OVERBOUGHT`는 risk `overheated_momentum`/regime `overheated`, `RSI ≤ RSI_OVERSOLD`는 regime `oversold_rebound_watch`에서 다룬다.
- **volume은 독립 방향성이 아니라** 가격 방향을 거래량이 확인하는 방식이다(상승/하락봉 판정 × 거래량비).
- **지표 제외(excluded) vs neutral:** 핵심 입력이 아예 계산 불가일 때만 그 지표를 **제외**하고 남은 weight로 재정규화한다. 제외 조건 — `moving_average`: 20MA(또는 5MA) 없음 / `rsi`: RSI 없음 / `support_resistance`: support·resistance 둘 다 없음. `volume`·`pattern`은 제외하지 않고 계산 불가 시 neutral로 둔다(위 표).

### 4.2 signal_score · consensus 계산

지표별 signal을 `positive=+1 / neutral=0 / negative=−1`로 부호화하고 가중합한다.

```
signal_score = Σ(weight_i × signal_i) / Σ(active_weight_i)     # 범위 −1.0 ~ 1.0
```

- 계산 가능한(active) 지표만 합산하고, 제외된 지표가 있으면 **남은 active weight로 재정규화**한다.
- **모든 지표가 제외되면** `signal_score = 0.0`, `consensus = neutral`.
- consensus는 경계값 **포함**으로 라벨링한다(§2 enums·glossary와 동일):
  - `score ≥ SIGNAL_STRONG` → `strong_positive`
  - `score ≥ SIGNAL_WEAK` → `weak_positive`
  - `score ≤ −SIGNAL_STRONG` → `strong_negative`
  - `score ≤ −SIGNAL_WEAK` → `weak_negative`
  - 그 외 → `neutral`

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

### 5.1 confidence 4요소 계산식

각 요소를 0.0~1.0으로 계산해 `CONFIDENCE_WEIGHTS`로 가중합한다. 모든 요소는 "높을수록 confidence↑" 방향이다. **코드가 확정하며 LLM은 confidence를 만들지 않는다.**

- **agreement** = `|Σ(weight_i × signal_i)| / Σ(weight_i × |signal_i|)` — 모두 같은 방향이면 1.0, 상쇄될수록 낮아짐. **모든 지표가 neutral이면 0.0**(분모 0 → 0으로 정의).
- **volume_confirm** = `clamp(volume_ratio, 0.0, 1.0)` — `volume_ratio ≥ 1` → 1.0, 계산 불가 → 0.0.
- **trend_clarity** — 국면·상위 추세 정합성:
  - `final_regime`이 `sideways`·`unavailable` → 0.0
  - `alignment_flag == aligned` → 1.0
  - `alignment_flag == counter_trend` → 0.3
  - `alignment_flag == neutral` AND `final_regime`이 방향성 국면(`bullish_reversal_watch`·`uptrend_intact`·`downtrend`) → 0.6
  - 그 외(중립 성격 국면 `overheated`·`oversold_rebound_watch` + neutral) → 0.0
- **conflict_absence** = `clamp(1 − 2 × min(pos_weight, neg_weight), 0.0, 1.0)` — positive·negative가 동시에 강하면 낮아지고, 한쪽만 있거나 전부 neutral이면 1.0. (`pos_weight`·`neg_weight` = 각 방향 지표들의 원본 weight 합.)

`confidence_level`은 표시용 파생값이며 **DB에 저장하지 않는다**(저장값은 confidence 숫자): `≥ CONFIDENCE_HIGH` → high / `≥ CONFIDENCE_MEDIUM` → medium / 그 외 → low.

## 6. 리스크 (risk)

```python
# 유동성 판정 (둘 중 하나라도 미만이면 low_liquidity)
MIN_AVG_VOLUME = 100_000        # 최근 20일 평균 거래량 하한 (주)
MIN_AVG_TRADING_VALUE = 1_000_000_000  # 최근 20일 평균 거래대금 하한 (원, 10억)
```

*연결: `synthesis/risk.py`, `enums.md` risk_flags (low_liquidity)*
*MVP에서는 거래량 기준과 거래대금 기준을 함께 둔다. **둘 중 하나라도 기준 미만이면 `low_liquidity`를 부여한다**(보수적 기준 — 저가주는 거래량이 많아도 거래대금이 낮을 수 있음). 실제 임계값은 시장 구간·종목군에 따라 백테스트로 조정한다.*

### 6.1 risk flag 산출 조건

`risk.items[]`는 `{flag, note, ref_price}`(contracts §2)를 코드가 확정한다. `note`는 **코드 템플릿**(LLM 아님, glossary risk_notes)이고 짧은 사실 서술 톤이며 매수/매도 표현을 쓰지 않는다.

| flag | 조건 | ref_price |
| --- | --- | --- |
| `volume_not_confirmed` | 방향성 있는(positive/negative) 지표 신호가 있는데 `volume_ratio < 1` 또는 계산 불가 | `None` |
| `near_resistance` | 최신 close가 resistance 기준 ±`NEAR_RESISTANCE_THRESHOLD_PCT` 이내 | resistance |
| `near_support` | 최신 close가 support 기준 ±`NEAR_SUPPORT_THRESHOLD_PCT` 이내 | support |
| `mixed_signals` | positive 지표와 negative 지표가 **동시에** 존재 | `None` |
| `overheated_momentum` | `RSI ≥ RSI_OVERBOUGHT` 또는 `final_regime == overheated` | `None` |
| `counter_higher_trend` | `alignment_flag == counter_trend` | `None` |
| `low_liquidity` | 평균 거래량 < `MIN_AVG_VOLUME` 또는 평균 거래대금 < `MIN_AVG_TRADING_VALUE` | `None` |

- `near_support`는 위험이 아니라 관찰 지점이므로 note를 중립적으로 쓴다("매수 기회" 표현 금지, enums §7). `near_resistance`도 과장 경고 없이 중립 서술.
- `ref_price`는 `near_support`·`near_resistance`에만 각각 support·resistance 값을 넣고, 나머지는 `None`.

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

### 8.1 구간 분할 조회 (pagination)

KIS 단일 호출은 최대 100건이라(kis_mapping §11.4), 1y 일봉·5y 주봉은 여러 번 나눠 조회해 합친다.

```python
# 타임프레임별 KIS에서 확보할 데이터 기간 (fetch 기간 — 프론트 표시 slice가 아님).
KIS_FETCH_LOOKBACK_DAYS = {
    "D": 460,    # 1y(365) + 60MA 계산 여유 약 90일
    "W": 2250,   # 5y(1825) + 60주 MA 여유 약 420일
    "M": 1900,   # monthly_trend/regime 및 보조용 5년 수준
}
# 단일 호출 100건 제한을 피하기 위한 청크 폭 (달력일).
KIS_FETCH_CHUNK_DAYS = {
    "D": 100,    # ≈68거래일 < 100건
    "W": 600,    # ≈85주 < 100건
    "M": 1900,   # ≈60개월 < 100건 (분할 없이 1청크)
}
KIS_MAX_CHUNKS = 10             # 무한 루프 방지 상한 (D≈5·W≈4청크면 충분)
```

*연결: `services/kis_client.py`(`fetch_ohlcv`·`fetch_ohlcv_range`), `charts/chart_builder.py`(표시 slice `CHART_PERIOD_DAYS`), `kis_mapping.md` §8.*
*`KIS_MAX_CHUNKS`는 상한이자 완전성 가드다 — `fetch_ohlcv_range`가 이 상한을 다 쓰고도 요청 `start_date`까지 못 가면 잘린 결과를 반환하지 않고 예외(`KisRangeIncompleteError`)를 던진다(kis_mapping §8.1). 지나치게 넓은 명시 범위 요청에서 데이터가 조용히 잘리는 것을 막기 위함이다.*
***`KIS_FETCH_LOOKBACK_DAYS`(원천 데이터 확보 기간)와 `CHART_PERIOD_DAYS`(§10, 프론트 표시 slice)는 다른 축이다.*** fetch가 표시 창보다 넓어야 차트 왼쪽 끝 candle의 MA overlay까지 계산된다. D→W/M 리샘플은 하지 않는다 — D/W/M은 각각 KIS `FID_PERIOD_DIV_CODE`로 직접 조회한다.

## 9. 검증·재생성 (verification)

```python
REGEN_MAX_COUNT = 1             # 검증 ③ 실패 시 재생성 최대 횟수
# 재생성 후에도 실패 → 템플릿 폴백 (LLM 문장 버림)
```

*연결: `supervisor/technical_supervisor.py` 재생성 루프, `observability/trajectory_eval.py`, UseCase T6*
*금융 리포트에서 LLM 라벨 왜곡 시 무한 재시도하지 않는다. 1회 재생성 후 실패하면 템플릿으로 안전하게 폴백한다.*

### 9.1 1D intraday(Beta) 활성화 플래그

```python
# 기본 False. .env/환경변수 INTRADAY_FETCH_ENABLED 로 override 가능(_env_bool 파싱).
INTRADAY_FETCH_ENABLED = _env_bool("INTRADAY_FETCH_ENABLED", default=False)
```

```env
# .env 예시 — 이 값일 때만 supervisor가 기본 KIS 분봉 fetcher를 켠다(기본은 미설정=꺼짐).
INTRADAY_FETCH_ENABLED=true
```

- **의미**: "프론트 1d 탭 클릭 시 따로 가져올지"가 아니라, **technical report 생성 시 1D intraday까지 D/W/M과 함께 포함할지**를 제어하는 feature flag다.
- **`True`일 때만** supervisor가 `intraday_fetcher` 미주입 시 **기본 KIS 분봉 fetcher(`fetch_minute_ohlcv`)** 를 써서 **리포트 생성 1회에 3m/1y/5y와 함께 `1d`·`intraday_context`를 조립**한다(best-effort). D/W/M이 supervisor 계층에서 항상 fetch되는 것과 같은 방식이되, **flag로 gate**한다.
- **`False`(기본)** 이면 intraday 미포함 — **기존 D/W/M(3m/1y/5y)만**(현재 동작과 동일). **D/W/M은 필수, 1D는 best-effort로 실패/빈 응답 시 리포트 전체를 실패시키지 않는다.**
- **env override**: `.env` 또는 환경변수 `INTRADAY_FETCH_ENABLED`로 환경별(dev/staging=on, prod=off 등) 제어한다. **새 KIS env key가 아니다**(기존 KIS 인증 값은 그대로). 파싱 규칙 — true: `1`/`true`/`yes`/`on`, false: 미설정/`0`/`false`/`no`/`off`/빈문자열, **인식 불가값은 경고 후 False**(운영 안전, 조용한 True 금지).
- 우선순위: `intraday_candles` 직접 주입 > 명시 `intraday_fetcher` > (flag ON) `fetch_minute_ohlcv` > off.
- **실험/Beta 성격.** ON 시 요청마다 분봉 조회가 추가되어 **호출량·rate limit 부담이 커진다**(1회 30건 페이징, `EGW00201` 재시도 — `kis_mapping.md §12`). 운영 default-on은 **smoke 결과·운영 정책을 보고 결정**한다.
- intraday fetch 실패·빈 응답은 D/W/M output에 전파되지 않는다.

*연결: `supervisor/technical_supervisor.py` intraday 조립, `services/kis_client.py::fetch_minute_ohlcv`, `contracts.md` "1D intraday"*

## 10. 차트 (charts)

```python
CHART_PERIODS = ["3m", "1y", "5y"]   # 기간 토글 (1d는 Beta, chart_annotation_spec §3.1)
# 3m: 일봉 / 1y: 일봉·주봉 / 5y: 주봉·월봉

# 기간별 candle slice 창 (기본 candle source의 마지막 candle date 기준 최근 N일).
# 데이터 부족 시 확보된 봉까지만 사용하고 예외를 내지 않는다. D→W/M 리샘플은 하지 않는다.
CHART_PERIOD_DAYS = {
    "3m": 90,
    "1y": 365,
    "5y": 1825,
}

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

# annotation 중복 제거 창 — 달력일이 아니라 candle(봉) index 거리 기준(주말·휴장 왜곡 방지).
# chart_annotation_spec §8.4의 "거래일/4주"를 봉 개수로 표현. 5y는 주봉이라 "4주"=4봉.
ANNOTATION_DEDUP_BARS = {
    "3m": 5,    # 3m(일봉): 5봉
    "1y": 10,   # 1y(일봉): 10봉
    "5y": 4,    # 5y(주봉): 4봉(≈4주)
}
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
