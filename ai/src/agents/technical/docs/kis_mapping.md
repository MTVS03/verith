# 17. KIS API 매핑 (KIS Mapping)

`docs/kis_mapping.md`

가격/기술적 분석 에이전트가 KIS(한국투자증권) Open API에서 시세를 받아 내부 표준 OHLCV로 변환하는 방식을 정의한다. API 경로·요청 파라미터·응답 필드는 KIS 공식 저장소(`koreainvestment/open-trading-api`)로 검증했으며, 실제 응답 값은 토큰 발급 후 호출로 채운다(§11).

---

## 1. 문서 목적

1. MVP에서 사용하는 KIS API와 요청/응답 구조를 정의한다.
2. KIS 원본 필드를 내부 표준 OHLCV 필드로 매핑한다.
3. 종목 allowlist·호출 제한·구간 분할 등 실무 제약을 정리한다.
4. `services/kis_client.py` 구현의 기준 문서가 된다.

---

## 2. MVP 종목 범위

MVP 조사 범위는 **2차전지 10종목**으로 제한한다. KIS API는 섹터 단위 조회가 아니라 종목코드 단위 조회이므로, 10종목을 allowlist 순회하며 각 종목마다 D/W/M을 개별 호출한다(§3).

| 종목명 | 종목코드 |
| --- | --- |
| LG화학 | 051910 |
| LG에너지솔루션 | 373220 |
| 삼성SDI | 006400 |
| SK이노베이션 | 096770 |
| 에코프로 | 086520 |
| 에코프로비엠 | 247540 |
| 포스코퓨처엠 | 003670 |
| 엘앤에프 | 066970 |
| 엔켐 | 348370 |
| SK아이이테크놀로지 | 361610 |

allowlist 정본은 `config.md` §11 `BATTERY_TICKERS`다. allowlist 밖 종목은 조회하지 않고 범위 밖(`OUT_OF_SCOPE_TICKER`)으로 처리한다. 최종 종목코드는 KIS 종목정보파일(`stocks_info/`) 또는 KRX 기준으로 한 번 검증하는 것을 권장한다.

---

## 3. KIS 호출 방식

KIS 기간별시세 API는 **종목코드 1개 × 타임프레임 1개** 단위로 호출한다. "한 번에 10종목"이 아니라, 10종목을 D/W/M으로 각각 조회하면 최소 30회 호출한다.

```
for ticker in BATTERY_TICKERS:
    for period in [D, W, M]:              # 일봉·주봉·월봉 각각
        → KIS 기간별시세 API 호출 (FID_PERIOD_DIV_CODE=period)
        → output2를 내부 표준 OHLCV로 변환
        → Redis 캐시 저장 (daily / weekly / monthly)
```

**일봉·주봉·월봉을 모두 KIS 원본으로 각각 호출한다.** 같은 `inquire-daily-itemchartprice` API에 `FID_PERIOD_DIV_CODE`만 `D`/`W`/`M`으로 바꿔 부른다. 리샘플로 파생하지 않는다 — 타임프레임별로 KIS 실제 시세를 정본으로 쓴다. 종목당 3개 타임프레임 호출이므로 10종목이면 최소 30호출(구간 분할 시 더 늘 수 있음, §8).

---

## 4. 사용 API

**국내주식기간별시세(일/주/월/년)** — MVP 시세 수집의 핵심 API.

```
GET /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice
TR_ID: FHKST03010100
```

이동평균·RSI·거래량·지지저항·패턴 계산의 원천 데이터를 이 API로 받는다.

---

## 5. 요청 파라미터

| 파라미터 | 값 | 설명 |
| --- | --- | --- |
| `FID_COND_MRKT_DIV_CODE` | `J` | 시장 구분 (J:KRX, NX:NXT, UN:통합) |
| `FID_INPUT_ISCD` | 종목코드 | 예: `373220` |
| `FID_INPUT_DATE_1` | 시작일 | `YYYYMMDD` |
| `FID_INPUT_DATE_2` | 종료일 | `YYYYMMDD` (한 호출 최대 100건) |
| `FID_PERIOD_DIV_CODE` | `D`/`W`/`M`/`Y` | 일봉/주봉/월봉/연봉 |
| `FID_ORG_ADJ_PRC` | `0`/`1` | 0:수정주가 / 1:원주가 |

MVP는 `FID_COND_MRKT_DIV_CODE=J`, 수정주가 `FID_ORG_ADJ_PRC=0`을 기본으로 한다. `FID_PERIOD_DIV_CODE`는 요청 타임프레임에 따라 `D`(일봉)/`W`(주봉)/`M`(월봉)을 사용한다.

---

## 6. 응답 구조

응답은 `output1`(종목 요약)과 `output2`(기간별 OHLCV 배열)로 나뉜다. **기간별 OHLCV는 `output2`에서 가져온다.**

```json
{
  "rt_cd": "0",
  "msg_cd": "MCA00000",
  "msg1": "정상처리 되었습니다.",
  "output1": { "hts_kor_isnm": "...", "stck_prpr": "...", "acml_vol": "...", "...": "..." },
  "output2": [
    { "stck_bsop_date": "...", "stck_oprc": "...", "stck_hgpr": "...", "stck_lwpr": "...", "stck_clpr": "...", "acml_vol": "...", "acml_tr_pbmn": "...", "...": "..." }
  ]
}
```

`rt_cd`가 `0`이면 정상. `output2`의 각 원소가 하루(또는 한 주/월) 봉이다.

---

## 7. KIS 원본 필드 → 내부 OHLCV 매핑

이 표가 `kis_client.py` 변환의 기준이다. (필드명은 KIS 공식 저장소 `inquire_daily_itemchartprice` 응답으로 검증.)

| KIS 원본 필드 (output2) | 내부 필드 | 타입 | 설명 |
| --- | --- | --- | --- |
| `stck_bsop_date` | `date` | date | 영업일자 (YYYYMMDD) |
| `stck_oprc` | `open` | float | 시가 |
| `stck_hgpr` | `high` | float | 고가 |
| `stck_lwpr` | `low` | float | 저가 |
| `stck_clpr` | `close` | float | 종가 |
| `acml_vol` | `volume` | int | 누적 거래량 |
| `acml_tr_pbmn` | `trading_value` | int | 누적 거래대금 |

**내부 표준 OHLCV 형태:**

```json
{
  "ticker": "373220",
  "date": "2026-06-30",
  "open": 80000.0,
  "high": 81000.0,
  "low": 79000.0,
  "close": 80500.0,
  "volume": 12345678,
  "trading_value": 987654321000
}
```

`trading_value`(거래대금)를 함께 받는 것이 중요하다 — 국내 저가주 특성상 유동성 판정(`low_liquidity`)은 거래량뿐 아니라 거래대금도 본다(`config.md` §6, `enums.md`).

---

## 8. 호출 제한과 구간 분할

KIS 기간별시세는 **한 호출에 최대 100건**을 반환한다. 1년치 일봉(약 240거래일)은 한 번에 못 받으므로 날짜 구간을 나눠 여러 번 호출하고 합친다.

```
1년 일봉 필요
→ [시작일 ~ +100거래일], [+100 ~ +200], ... 로 구간 분할
→ 각 구간 호출 결과(output2)를 날짜 기준으로 병합·정렬
```

구현 시 주의: **응답의 날짜 정렬 방향**(최신→과거인지 과거→최신인지)을 실제 호출로 확인해 병합 로직을 맞춘다(§11 TODO).

**구간 분할은 D/W/M 각각에 적용한다.** 일봉은 1년 약 240개라 여러 번 호출이 필요하고, 주봉은 5년 기준 약 260개라 역시 분할이 필요할 수 있다. 월봉은 5년 약 60개로 100건 안에 들어올 수 있으나, 실제 반환 건수는 KIS 호출 후 확인한다(§11).

### 8.1 구간 분할 구현 정책 (확정)

`services/kis_client.py`의 `fetch_ohlcv_range(ticker, period, start, end)`가 아래 정책으로 구현한다. 파라미터·상수 정본은 `config.md §8.1`.

1. **청크 방향·폭:** `end_date`에서 **과거 방향**으로 `KIS_FETCH_CHUNK_DAYS[period]` 단위 청크. 각 청크는 `FID_INPUT_DATE_1/2`(YYYYMMDD)로 조회한다. 인접 청크는 경계일 1일 겹쳐도 되며, 중복은 date dedup으로 제거한다.
2. **기본 fetch 기간:** `fetch_ohlcv(ticker, period)`는 `end=오늘`, `start=오늘−KIS_FETCH_LOOKBACK_DAYS[period]`로 위 range 조회를 수행한다.
3. **자연 종료(정상 반환):** ① 목표 `start_date` 이전까지 확보 / ② 청크 응답이 빈 배열(더 과거 데이터 없음) / ③ 가장 오래된 date가 직전 청크보다 더 과거로 가지 않음(정체). 이 셋은 데이터가 소진된 정상 종료다.
4. **불완전 종료(예외):** `KIS_MAX_CHUNKS`를 모두 소진했는데도 요청 `start_date`까지 못 간 경우 — 잘린 partial 결과를 **조용히 반환하지 않고 예외(`KisRangeIncompleteError`)를 던진다.** 예외 메시지에 `ticker·period·requested_start·requested_end·oldest_fetched·KIS_MAX_CHUNKS`를 담는다. (기본 `fetch_ohlcv()`의 D=460·W=2250·M=1900은 10청크 이내라 정상적으로는 이 예외가 나지 않는다.)
5. **입력 fail-fast(KIS 호출 전):** ⓐ 날짜 입력은 `YYYYMMDD` 또는 `YYYY-MM-DD` **두 형식만** 허용(정규식 검증 후 실제 달력 검증), 그 외는 거부. ⓑ `start_date > end_date`(역전 범위)는 토큰 발급·네트워크 호출 전에 거부한다.
6. **병합:** 전 청크 결과를 **date 기준 dedup → `start ≤ date ≤ end` 필터 → 과거→최신 오름차순 정렬**(§11.5). KIS 원본이 최신→과거로 와도 최종 반환은 오름차순이다.
7. **재시도:** 청크별 호출 실패·`EGW00201`은 기존 `_call_chart`의 retry/backoff(§10·config §8)를 그대로 재사용한다. 새 재시도 로직을 만들지 않는다.
8. **리샘플 금지:** D/W/M은 각각 `FID_PERIOD_DIV_CODE`로 직접 조회한다. 일봉에서 주/월봉을 파생하지 않는다.

### 8.2 조회 종료일(`end_date`) 스레딩 — `as_of` 반영

리포트의 `as_of`(분석 기준 시점)를 **실제 KIS 조회 종료일**로 반영한다. 과거 `as_of` 요청에서 최신 데이터를 쓰고 출력엔 과거일을 찍는 불일치를 없앤다.

1. **경로:** `TechnicalAgentInput.as_of` → supervisor → `run_data_collect(ticker, as_of=…)` → `fetch_multi_timeframe_ohlcv(ticker, end_date=…)` → `fetch_ohlcv(ticker, period, end_date=…)` → `FID_INPUT_DATE_2`. `FID_INPUT_DATE_1`은 기존 lookback/pagination 정책대로 계산한다(§8.1).
2. **정규화:** `services/kis_client.normalize_end_date(datetime|date|str|None) -> date | None`가 담당한다. `None`→`None`(기존 오늘 기준), `datetime`→`.date()`, `date`→그대로, `YYYYMMDD`/`YYYY-MM-DD`→`date`(문자열 파싱은 `_normalize_to_date` 재사용). 잘못된 형식·미지원 타입·**미래 날짜**는 `ValueError`. `as_of→end_date` 번역은 `data_collect`가 수행하고, KIS 경계에서는 `end_date`라는 이름을 쓴다.
3. **미래 거부(tz 안전):** `end_date`가 오늘보다 **명백히 미래**면 `ValueError`. tz-aware `datetime`이면 그 tz 기준 오늘(`datetime.now(tzinfo).date()`)과 비교해, 타임존 차이로 정상적인 "오늘" 요청을 미래로 오판하지 않는다. `date`/naive/문자열은 일반 `date.today()` 기준.
4. **D/W/M 동일 기준:** `fetch_multi_timeframe_ohlcv`는 한 번 정규화한 `end_date`를 D·W·M **모두 같은 종료일**로 넘긴다.
5. **하위 호환:** `end_date`/`as_of`를 생략하면 기존 current-date 동작을 유지한다(`fetch_ohlcv_range`는 명시 구간 함수라 시그니처·pagination 무변경, 그대로 재사용).

---

## 9. Redis 캐시 저장 구조

변환된 내부 OHLCV는 Redis에 저장한다(`schema.md` §11과 동일).

| 키 패턴 | 내용 | TTL |
| --- | --- | --- |
| `ohlcv:daily:{ticker}` | 과거 일봉 배열 (KIS D) | 장기(오늘 봉만 갱신) |
| `ohlcv:weekly:{ticker}` | 주봉 배열 (KIS W) | 장기 |
| `ohlcv:monthly:{ticker}` | 월봉 배열 (KIS M) | 장기 |
| `ohlcv:today:{ticker}` | 오늘 일봉 1개 | 15분 |
| `ohlcv:minute:{ticker}` | 분봉 배열 | 1분 (1d Beta용·MVP 필수 아님) |

일봉·주봉·월봉은 모두 KIS `inquire-daily-itemchartprice`를 `FID_PERIOD_DIV_CODE`만 다르게(`D`/`W`/`M`) 호출한 원본이다. 리샘플로 만들지 않는다.

---

## 10. 실패·폴백 처리

KIS 호출 실패 시 재시도·폴백은 `config.md` §8·`sequence.md`·`trace_schema.md`를 따른다.

- 재시도 3회 (백오프 1·2·4초), **KIS 1회 호출 timeout 5초**(`KIS_TIMEOUT_SECONDS`)
- **일봉(D) 3회 실패 + stale daily 캐시(1거래일 내) 있음** → `data_status=stale_cache`("최신 시세 미반영")
- **일봉(D) 실패 + daily 캐시 없음** → `data_status=data_limited`, **환각 데이터 생성 없음**
- **주봉(W)·월봉(M) 실패 + 해당 타임프레임 stale 허용 범위 내 캐시 있음** → stale W/M 사용, 최신봉 미반영 표시 (D와 stale 기준이 다름 — `STALE_CACHE_MAX_AGE_BY_PERIOD`)
- **일봉(D)은 확보됐으나 W 또는 M 미확보(캐시도 없음)** → `data_status=data_limited`로 표기하고 **확보된 일봉 기준 계산은 계속 진행**한다. 미확보 타임프레임은 `weekly_trend`/`monthly_trend`=`unavailable`. `alignment_flag`는 `regime_rules.md`의 **월봉 우선 규칙**을 따른다(월봉 있으면 월봉 기준 / 월봉 unavailable이고 주봉 있으면 주봉 기준 / 둘 다 unavailable이면 `neutral`). `regime_context`에 상위 타임프레임 데이터 제한을 명시. (프론트는 "분석은 됐으나 상위 타임프레임 일부 제한"으로 표시)
- 봉 수 부족(60봉 미만) → `data_status=regime_unavailable`

> timeout 계층 구분: 여기 5초는 **KIS 1회 호출** timeout(`config.md` §8)이다. `api_spec.md`의 60초는 백엔드→AI **전체 분석 요청** timeout으로, 층이 다르다(AI 내부에서 KIS 재시도·폴백을 처리하는 시간을 포함).

allowlist 밖 종목은 KIS 호출 자체를 하지 않고 `OUT_OF_SCOPE_TICKER`로 즉시 반환한다(§2).

---

## 11. 실제 응답 샘플 (검증 완료)

> **검증 방법:** `ai/src/agents/technical/scripts/test_kis_ohlcv.py` — 실전 도메인(`https://openapi.koreainvestment.com:9443`)에 토큰 발급 후 2차전지 10종목 × D/W/M = 30호출.
> **검증일:** 2026-07-03. **결과:** 단일종목(373220) D/W/M 전부 OK, 10종목 확장 30/30 성공, 실패 0.
> 샘플 CSV: `ai/src/agents/technical/scripts/kis_sample_output/{ticker}_{D|W|M}.csv` (내부 OHLCV 구조).

### 11.1 인증·엔드포인트 실측
- 토큰: `POST {base}/oauth2/tokenP` `{grant_type=client_credentials, appkey, appsecret}` → `access_token`, `expires_in=86400`(24h). 스크립트는 파일 캐시로 재사용(만료 5분 전 갱신).
- 시세: `GET {base}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice`, 헤더 `tr_id=FHKST03010100`, `custtype=P`. **계좌번호 불필요**(확인됨).
- **`.env` 키 이름 확정:** 이 프로젝트의 공식 KIS 키는 **`KIS_API_KEY` / `KIS_API_SECRET` / `KIS_BASE_URL`** 3개다(기존 샘플 스크립트와 통일). `config.py`(`load_kis_settings()`)는 이 3개만 로딩하며, 누락 시 fail-fast한다. `KIS_APP_KEY`/`KIS_APP_SECRET`은 공식 키가 아니며(존재 시 경고), 시세 조회에 불필요한 `KIS_ACCOUNT_NO`는 로딩하지 않는다.

### 11.2 실제 `output1` 구조 (종목 요약 — **단일 객체**, 배열 아님)
`373220` D 응답 기준. 존재 필드:
```
prdy_vrss, prdy_vrss_sign, prdy_ctrt, stck_prdy_clpr, acml_vol, acml_tr_pbmn,
hts_kor_isnm, stck_prpr, stck_shrn_iscd, prdy_vol, stck_mxpr, stck_llam,
stck_oprc, stck_hgpr, stck_lwpr, stck_prdy_oprc, stck_prdy_hgpr, stck_prdy_lwpr,
askp, bidp, prdy_vrss_vol, vol_tnrt, stck_fcam, lstn_stcn, cpfn, hts_avls,
per, eps, pbr, itewhol_loan_rmnd_ratem
```
예: `hts_kor_isnm="LG에너지솔루션"`, `stck_prpr="362500"`(현재가), `acml_tr_pbmn="141122636250"`. output1은 "오늘 시점 요약"이라 OHLCV 시계열이 아니다 — 시계열은 output2에서만 취한다.

### 11.3 실제 `output2` 구조 (OHLCV 배열)
문서 §7 매핑 필드가 **실제 응답과 100% 일치**(필드명 변경 없음). 원소 예(373220 D, 최신):
```json
{"stck_bsop_date":"20260703","stck_clpr":"362500","stck_oprc":"359500","stck_hgpr":"363500",
 "stck_lwpr":"342500","acml_vol":"397490","acml_tr_pbmn":"141122636250","flng_cls_code":"00",
 "prtt_rate":"0.00","mod_yn":"N","prdy_vrss_sign":"2","prdy_vrss":"8500","revl_issu_reas":""}
```
- 매핑 대상 7개 필드(`stck_bsop_date/oprc/hgpr/lwpr/clpr, acml_vol, acml_tr_pbmn`)는 **D/W/M 전부 존재**. §7 매핑 그대로 확정.
- 값은 모두 **문자열**로 온다 → `kis_client.py`에서 float/int 캐스팅 필요.
- 매핑 외 부가 필드: `flng_cls_code`(락 구분), `prtt_rate`(분할비율), `mod_yn`(수정여부), `prdy_vrss_sign/prdy_vrss`(전일대비), `revl_issu_reas`(재평가 사유). MVP 매핑엔 불필요.

### 11.4 반환 건수 · 100건 제한 · 구간 분할
| 타임프레임 | 요청 구간 | 반환 건수 | 100건 제한 | 실제 날짜 범위(373220) |
| --- | --- | --- | --- | --- |
| **D** (일봉) | 최근 ~480일 | **100건 (상한)** | **도달** → 구간 분할 필요 | 20260204 ~ 20260703 |
| **W** (주봉) | 최근 5년 | **100건 (상한)** | **도달** → 구간 분할 필요 | 20240805 ~ 20260629 |
| **M** (월봉) | 최근 5년 | **55~60건** | 미도달 → 분할 불필요 | 20220128 ~ 20260703 |

- **D 100건 ≈ 달력 약 5개월(20260204~20260703, 거래일 100일).** 1년치 일봉(약 240거래일)은 **3구간** 분할 필요.
- **W 100건 ≈ 약 1.9년(20240805~20260629).** 5년 주봉(약 260개)은 **약 3구간** 분할 필요(§8 예상과 일치).
- **M은 5년 요청에 55~60건**으로 100건 안에 들어옴 → **월봉은 구간 분할 불필요.** (건수 차이는 상장일 — 예: 373220=55, 엔켐=57, 대부분 60.)
- **구간 파라미터(`FID_INPUT_DATE_1/2`) 정상 동작 확인:** `20260504~20260603` 요청 → 20건, 전부 구간 내. 본 구현의 구간 분할 병합에 사용 가능.

### 11.5 날짜 정렬 방향
- **D/W/M 전부 `최신 → 과거`(descending).** `output2[0]`이 가장 최신 봉, `output2[-1]`이 가장 과거 봉.
- §8 병합 로직: 구간별 output2를 이어붙인 뒤 **날짜 오름차순 정렬**로 정규화(내부 OHLCV는 과거→최신 권장). CSV 산출물은 KIS 원본 순서(최신 우선) 그대로 저장돼 있으니 소비 측에서 재정렬.

### 11.6 `acml_tr_pbmn`(거래대금) 존재 여부
- **D/W/M 3개 타임프레임 모두 존재.** 10종목 30호출 전부 `거래대금=O`. 유동성 판정(`MIN_AVG_TRADING_VALUE`, §7·`config.md §6`) 근거값을 타임프레임별로 확보 가능.

### 11.7 유량 제한(rate limit) 실측
- 호출 간격 0.35s(초당 ~2.8건)에서도 `EGW00201`("초당 거래건수를 초과") 간헐 발생 → **1초 백오프 후 재시도로 전부 복구, 최종 실패 0.**
- 실전계좌 조회 API의 초당 상한이 공표치보다 빡빡하게 걸릴 수 있음. **본 구현 권장:** 호출 간격을 0.5s 이상으로 넉넉히 두거나, `EGW00201` 수신 시 지수 백오프 재시도(1·2·4s)를 표준 방어로 포함(§10 재시도 정책과 정합).

### 11.8 stale 신선도 기준 제안 (`config.md STALE_CACHE_MAX_AGE_BY_PERIOD`)
- 관찰: **W 최신봉은 당주(월요일 시작, 20260629)**, **M 최신봉은 당월 진행분(20260703)**으로 갱신됨(장중에도 진행봉 반영).
- **제안값** (실운영 검증 후 확정): `D=1거래일`, `W=1주(약 5거래일)`, `M=1개월(약 22거래일)`. 상위 타임프레임은 갱신 주기가 길어 D보다 stale 허용을 넉넉히 둔다.

### 11.9 휴장일·거래정지 응답
- 이번 10종목은 모두 정상 상장·거래 종목이라 거래정지/상장폐지 케이스는 미검증. output2에 결측 없이 연속 반환됨. 거래정지 종목 응답 형태(빈 output2 / rt_cd 오류)는 **후속 검증 항목으로 남김.**

> (참고) 토큰 발급·인증은 KIS 공식 저장소 `kis_auth.py` 방식(앱키·앱시크릿)을 참고하되, 본 프로젝트는 `.env` + 파일 토큰 캐시 방식으로 구현했다(`ai/src/agents/technical/scripts/test_kis_ohlcv.py`).

---

## 12. 관련 문서

| 문서 | 역할 |
| --- | --- |
| `config.md` | `BATTERY_TICKERS` allowlist, 재시도·유동성 설정 |
| `schema.md` | Redis 캐시 구조 (§9와 동일) |
| `sequence.md` | KIS 장애 흐름 |
| `trace_schema.md` | KIS 호출 trace(retry/fallback) |
| `contracts.md` | 내부 OHLCV가 지표 계산 거쳐 산출로 이어짐 |
| `api_spec.md` | OUT_OF_SCOPE_TICKER 처리 |
