# 11. 테스트 계획 (Test Plan)

`docs/test_plan.md`

가격/기술적 분석 에이전트의 검증 기준을 정의한다. 이 문서는 `prompts.md`의 LLM 계약, `regime_rules.md`의 국면 규칙, `contracts.md`의 출력 계약, `config.md`의 설정값이 실제 구현에서 지켜지는지 확인하기 위한 **테스트 기준**이다.

`prompts.md`와 짝을 이룬다 — 그쪽이 "LLM에게 무엇을 금지했는가"라면, 이 문서는 "그 금지와 계약을 어떻게 검증하는가"다.

---

## 1. 문서 목적

이 테스트 계획의 목표는 **"좋은 예측"을 검증하는 것이 아니다.** 코드가 확정한 라벨·수치·계약을 **LLM이나 예외 상황이 왜곡하지 못하게 막는 것**이다.

따라서 "이 종목이 오를까"는 테스트 대상이 아니다. "코드가 `overheated`로 확정했는데 LLM이 `상승 추세`로 바꿔 쓰지 않는가", "봉이 부족한데 억지로 국면을 판정하지 않는가" 같은 **결정론적 계약 준수**가 대상이다.

---

## 2. 테스트 범위 요약

| 검증 | 목적 | 주요 대상 | 실패 시 처리 |
| --- | --- | --- | --- |
| **검증 ①** 계산 정확성 | 지표 계산이 기준 공식과 일치하는지 | indicators, KIS 응답 변환 | 테스트 실패 |
| **검증 ②** regime 규칙 | 입력 지표가 명세대로 regime·alignment_flag로 분류되는지 | regime 규칙 코드, 멀티프레임 보정 | 테스트 실패 |
| **검증 ③** LLM 라벨 왜곡 | LLM 문장이 코드 확정 라벨·신호를 왜곡하지 않는지 | `interpretation.text`, `technical_signals[].detail` | **재생성 1회 → 템플릿 폴백** |
| 차트 annotation | 차트 overlays·annotations를 코드가 기준대로 계산하는지 | `chart_builder`, `chart_annotation_spec.md` | 테스트 실패 |
| 출력 계약 | 출력 JSON이 contracts 스키마를 지키는지 | 전체 출력 | 테스트 실패 |
| 예외·복원력 | KIS 장애·데이터 부족에서 안전 착지하는지 | E 하네스 | 테스트 실패 |
| Trace 기록 | 역추적 가능한 관측 기록이 남는지 | D 관측층 | 테스트 실패 |

**검증 ③만 "실패 = 테스트 실패"가 아니다.** 검증 ③ 실패는 정상 런타임 흐름의 일부다 — 재생성 1회 후 폴백으로 안전 착지한다(`pipeline.md`·`usecase.md` T6). 테스트는 "이 흐름이 규정대로 도는지"를 검사한다.

> **성격 구분:** 검증 ①·②·계약은 **정상 동작 확인**(맞게 계산/분류/반환하는가) 테스트다. 검증 ③·예외는 **위반 감지 확인**(틀린 입력·왜곡을 잡아내는가) 테스트다. 표의 "기대 결과"가 "일치"면 전자, "실패"면 후자다.

---

## 3. 검증 ① 계산 정확성

**성격:** 정상 동작 확인. **대상:** 지표 계산·KIS 응답 변환. **LLM 미개입.**

### 목적

이동평균·RSI·볼린저밴드·거래량 평균이 기준 계산과 일치하는지, KIS D/W/M 원본 응답이 내부 표준 OHLCV로 정확히 변환되는지 확인한다. fixture 기대값 또는 검증된 라이브러리 결과와 비교하는 mock 단위테스트다.

### 테스트 케이스

| ID | 입력 | 기대 결과 |
| --- | --- | --- |
| CALC-01 | close 60개 | 5MA / 20MA / 60MA가 기준 계산과 일치 |
| CALC-02 | close 20개 | 볼린저밴드 상단/하단(20, 2σ)이 기준 계산과 일치 |
| CALC-03 | close 14개 이상 | RSI(14)가 기준 계산과 일치 |
| CALC-04 | KIS 일봉(D)·주봉(W)·월봉(M) output2 응답 | 세 타임프레임 각각 내부 표준 OHLCV로 정확히 변환 (date/open/high/low/close/volume/trading_value 매핑) |
| CALC-05 | 거래량 20개 | 20일 평균 거래량이 기준 계산과 일치 |

### 3.1 synthesis 계산 검증 (SYN-*)

**성격:** 정상 동작 확인. **대상:** `synthesis/`(signal_score·confidence·risk). **LLM 미개입** — 전부 코드 확정값. 기준은 `config.md §4.1·§4.2·§5.1·§6.1`.

| ID | 입력 | 기대 결과 |
| --- | --- | --- |
| SYN-01 | 각 지표 원천값 | `config.md §4.1` 규칙대로 positive/neutral/negative 확정 (RSI 극단은 neutral) |
| SYN-02 | 지표 signal 집합 | `signal_score = Σ(w·s)/Σ(active w)`, 범위 −1.0~1.0 |
| SYN-03 | 일부 지표 제외 | 남은 active weight로 재정규화 |
| SYN-04 | 전 지표 제외 | `signal_score=0.0`, `consensus=neutral` |
| SYN-05 | 경계 score | `SIGNAL_STRONG`/`SIGNAL_WEAK` 포함(≥/≤) 라벨링 |
| SYN-06 | 전 지표 neutral | `agreement=0.0` |
| SYN-07 | volume_ratio 다양 | `volume_confirm = clamp(ratio,0,1)` |
| SYN-08 | alignment/regime 조합 | `trend_clarity`가 aligned=1.0·counter=0.3·neutral+방향=0.6·sideways/unavailable=0.0 |
| SYN-09 | pos·neg 동시 강함 | `conflict_absence` 낮아짐, confidence 범위 0.0~1.0 |
| SYN-10 | confidence 경계 | `CONFIDENCE_HIGH`/`MEDIUM` 구간으로 confidence_level high/medium/low |
| SYN-11 | 각 risk 조건 충족 | 해당 `RiskFlag` 부여, note 비어있지 않음, near_*만 ref_price 존재 |
| SYN-12 | 전 산출물 | 코드값(enum)·note에 매수/매도 표현 없음 |

*`confidence_level`은 JSON에는 있으나 DB 저장 대상 아님(재계산 파생값). synthesis는 `contracts.TechnicalSignal`을 직접 조립하지 않고 중간 dataclass를 낸다(detail·detail_source는 LLM 단계).*

### 3.2 KIS 구간 분할 조회 검증 (PAGE-*)

**성격:** 정상 동작 확인. **대상:** `services/kis_client.py`의 `fetch_ohlcv`·`fetch_ohlcv_range` pagination. **mock만** — 실 KIS 호출 없음. 기준: `kis_mapping §8.1`, `config.md §8.1`.

| ID | 입력/상황 | 기대 결과 |
| --- | --- | --- |
| PAGE-01 | `fetch_ohlcv(ticker, "D")` | `KIS_FETCH_LOOKBACK_DAYS["D"]` 기간을 range 조회 |
| PAGE-02 | 여러 청크 필요한 범위 | `_call_chart`가 2회 이상 호출 |
| PAGE-03 | 청크 진행 방향 | `end_date`에서 과거 방향으로 date_to가 감소 |
| PAGE-04 | 경계 중복 date | 최종 결과에서 date dedup |
| PAGE-05 | 병합 결과 | 과거→최신 오름차순 |
| PAGE-06 | 범위 밖 date | `start ≤ date ≤ end`만 유지 |
| PAGE-07 | 빈 청크 | 즉시 중단 |
| PAGE-08 | 가장 오래된 date 정체 | 중단(무한 루프 방지) |
| PAGE-09 | 넓은 범위·작은 청크로 MAX_CHUNKS 소진 + start 미달 | **예외(`KisRangeIncompleteError`)** — partial 반환 금지 |
| PAGE-10 | D/W/M | 각 period가 pagination config 사용 |
| PAGE-11 | MAX_CHUNKS 전에 start 도달 | 정상 반환 |
| PAGE-12 | 예외 메시지 | requested 범위·oldest_fetched 포함 |
| PAGE-13 | `start_date > end_date` | 토큰/네트워크 호출 전 fail-fast |
| PAGE-14 | 날짜 입력 형식 | `YYYYMMDD`·`YYYY-MM-DD`만 허용, `2026--07-04`·`20-2607-04`·`2026/07/04`·존재하지 않는 날짜 거부 |

*allowlist·period 검증, output2 키 부재/비-list fail-fast, `_to_iso_date` 달력 검증, 리샘플 금지 등 기존 정책은 pagination 후에도 유지된다. `fetch_ohlcv_range`는 요청 범위를 완전히 확보하지 못하면 partial 결과를 정상 반환하지 않는다.*

---

## 4. 검증 ② regime 규칙

**성격:** 정상 동작 확인. **대상:** `regime_rules.md`의 규칙 구현.

### 목적

일봉 지표와 주/월봉 추세가 `regime_rules.md`의 **우선순위 규칙**대로 `daily_regime`·`final_regime`·`alignment_flag`·`regime_context`로 변환되는지 확인한다. 입력 → 라벨의 결정론 매핑 테스트다.

### 4.1 일봉 regime 우선순위

규칙은 위에서부터 검사하며 처음 만족하는 것으로 확정한다(if-elif). **극단 상태(과매도·과열)를 추세보다 먼저 검사**하는 것이 핵심이다.

| ID | 입력 조건 | 기대 결과 |
| --- | --- | --- |
| REG-01 | RSI 72 + 볼밴 상단 근처 + 정배열 + 20MA/60MA 우상향 | `daily_regime=overheated` (**`uptrend_intact` 아님 — 과열 우선순위 확인**) |
| REG-02 | RSI 33 + 주요 지지 근처 + 양봉 + **현재가<20MA + 역배열 + 20MA 기울기 하락** | `daily_regime=oversold_rebound_watch` (**`downtrend` 아님 — 과매도 우선순위 확인**) |
| REG-03 | 현재가>20MA + 5MA>20MA + 20MA 기울기 상승 전환 + RSI 60 + **20MA>60MA 아직 아님** | `daily_regime=bullish_reversal_watch` |
| REG-04 | 현재가>20MA + 5MA>20MA>60MA(**정배열 완성**) + 20MA/60MA 우상향 + RSI 60 | `daily_regime=uptrend_intact` |
| REG-05 | 현재가<20MA + 역배열(5MA<20MA<60MA) + 20MA 기울기 하락 | `daily_regime=downtrend` |
| REG-06 | 위 조건 어디에도 해당 없음 | `daily_regime=sideways` |

**REG-01·02는 우선순위 테스트**다 — 추세 조건을 갖췄어도 극단 상태가 먼저 잡혀야 한다. **REG-03·04는 경계 테스트**다 — 정배열 완성 여부(20MA>60MA)가 전환 관찰과 추세 유지를 가른다.

### 4.2 멀티프레임 보정

**핵심: 중립 국면(과열·과매도·횡보)은 방향성 판정을 하지 않으므로 `alignment_flag=neutral`.** 정합/역행은 방향성 있는 국면에만.

| ID | 입력 조건 | 기대 결과 |
| --- | --- | --- |
| MTF-01 | daily=overheated + monthly=up | `final_regime=overheated`, `alignment_flag=neutral` |
| MTF-02 | daily=bullish_reversal_watch + monthly=down | `final_regime=bullish_reversal_watch`, `alignment_flag=counter_trend` |
| MTF-03 | daily=uptrend_intact + monthly=up | `final_regime=uptrend_intact`, `alignment_flag=aligned` |
| MTF-04 | daily=downtrend + monthly=up | `final_regime=downtrend`, `alignment_flag=counter_trend` |
| MTF-05 | daily=sideways + monthly=up | `final_regime=sideways`, `alignment_flag=neutral` |
| MTF-06 | daily=oversold_rebound_watch + monthly=down | `final_regime=oversold_rebound_watch`, `alignment_flag=neutral` |
| MTF-07 | daily=bullish_reversal_watch + monthly=unavailable + weekly=up | 월봉 없어 주봉 대체 → `alignment_flag=aligned`, regime_context에 "월봉 없어 주봉 기준" |
| MTF-08 | daily=bullish_reversal_watch + monthly=down + weekly=up | 월봉 우선 → `alignment_flag=counter_trend`, regime_context에 주봉/월봉 불일치 설명 |
| MTF-09 | daily=bullish_reversal_watch + monthly=sideways | `alignment_flag=neutral`, regime_context에 상위 추세 횡보 설명 |

MTF-01·05·06이 중립 국면 케이스다 — 상위 추세가 무엇이든 `neutral`이며, 상위 추세 사실은 `regime_context`에만 서술된다(조합 라벨을 만들지 않는다). MTF-07·08은 월봉 우선·주봉 대체 규칙(`regime_rules.md` 보정 기준) 검증이다.

**추세(up/down/sideways) 판정 검증:** 위 MTF 표는 `weekly_trend`·`monthly_trend`를 이미 정해진 값으로 주고 alignment를 검증한다. 추세 값 자체의 산출은 별도로 검증한다 — 변화율 `slope_pct`가 `+TREND_SIDEWAYS_THRESHOLD_PCT` 초과면 `up`, `−TREND_SIDEWAYS_THRESHOLD_PCT` 미만이면 `down`, 밴드(±1%) 이내면 `sideways`, 봉 수 부족·기준 종가 0이면 `unavailable`(`config.md §3`, `regime_rules.md` 2단계).

### 4.3 판단 불가

| ID | 입력 조건 | 기대 결과 |
| --- | --- | --- |
| REG-UNAV-01 | 일봉 < `MIN_DAILY_BARS`(예: 40개) | `data_status=regime_unavailable`, `final_regime=unavailable` |
| REG-UNAV-02 | final_regime=unavailable | `signal=null`, `risk=null`, `technical_signals=[]`, 6~8 스킵하고 차트로 |
| REG-UNAV-03 | 일봉 ≥ `MIN_DAILY_BARS`이나 60MA **기울기**만 계산 불가 | `unavailable` 아님 — 해당 조건만 False, 어디에도 안 걸리면 `sideways`로 착지 |

`contracts.md`·`regime_rules.md`(판단 불가 vs 조건 False)와 연결된다 — **필수 데이터 자체 부족(봉 수 < MIN_DAILY_BARS)**만 `unavailable`이고, 값은 있으나 보조 계산(기울기 등)만 부족하면 그 조건만 False 처리해 `sideways` 등으로 정상 착지한다. **억지 판정을 하지 않는 것**이 정직성의 핵심이다.

---

## 5. 검증 ③ LLM 라벨 왜곡

**성격:** 위반 감지 확인. **대상:** `interpretation.text`, `technical_signals[].detail`. **이 문서의 핵심.**

### 목적

LLM이 코드 확정 라벨·수치·신호를 문장 생성 과정에서 바꾸거나 왜곡하지 않는지 확인한다. `prompts.md`에서 금지한 것을 실제로 잡아내는 테스트다.

### 5.1 판정 방식

MVP의 검증 ③은 **LLM-as-judge가 아니라 결정론적 키워드/라벨 사전 매칭**으로 수행한다. 검증 자체도 코드로 작성되며 단위테스트 대상이다. 이는 "LLM을 다른 LLM이 검증하는" 무한 후퇴 문제를 피하기 위한 선택이며, 검증 ③ 자체를 검증 가능하게 만든다.

**역할 경계:**

| 파일 | 책임 |
| --- | --- |
| `test_plan.md` (이 문서) | 판정 **기준 명세** |
| `observability/trajectory_eval.py` | 판정 **로직 구현** |
| `observability/keyword_rules.py` | **키워드 사전** |

키워드 사전은 `config.py`가 아니라 `observability/keyword_rules.py`에서 관리한다. config는 수치·기간·가중치를 담당하고, 키워드 사전은 검증 ③의 문장 판정 규칙이므로 검증 코드 옆에 둔다. 다만 향후 템플릿 폴백 문장 생성에서도 같은 사전을 공유하게 되면, 공용 표현 계약 모듈로 위치를 재검토한다.

### 5.2 통과 조건

```
통과 = 대표 표현 1개 이상 존재
     AND 무효화 규칙 적용 후 남은 충돌 표현 없음
     AND details 구조 일치 (개수 · indicator 코드값)
     AND 금지 표현 없음
     AND 확정값 재생성 필드 없음
```

다섯 조건의 **AND**다. 하나라도 위반하면 검증 실패 → 재생성.

### 5.3 키워드 매칭 세부 규칙

검증 ③은 단순 문자열 포함 여부만 보지 않는다. 부분 문자열 오판을 줄이기 위해 아래를 적용한다.

1. **`required_any`는 단순 포함 매칭**을 허용한다. 확정 라벨의 대표 표현이 문장에 최소 1개 이상 등장해야 한다.
2. **`conflict_any`는 긴 표현부터 우선 매칭**한다(longest-match first). 예: "상승 전환 관찰"을 "상승 전환"보다 먼저 본다.
3. **현재 확정 라벨의 `required_any`와 겹치는 짧은 conflict 표현은 무효화**한다. 대표 표현의 일부를 충돌어로 잘못 잡지 않기 위함이다. 예: `bullish_reversal_watch`의 대표 표현이 "상승 전환 관찰"일 때, 그 안의 "상승 전환"을 별도 충돌어로 판정하지 않는다.
4. **교차 검사 금지.** 검증기는 전체 라벨 사전을 무차별 교차 검사하지 않고, **현재 확정 라벨의 사전만** 기준으로 검사한다.
5. **부정문·조건문 한계.** 부정문·조건문 안의 충돌 표현은 오탐 가능성이 있다. MVP에서는 이를 완전하게 해석하지 않고 한계로 명시한다(Future Work). **단, 금지 표현(매수·매도·손절·목표가·진입 등)은 부정문 안에 있어도 실패로 처리한다** — 사용자 노출 문구에 해당 단어가 등장한 것 자체가 정책 위반이기 때문이다.

**왜 "충돌어 없음"만으로 통과가 아닌가:** LLM이 확정 라벨을 회피해 애매한 문장만 쓰는 경우(충돌어도 대표어도 없음)도 실패로 본다. 예: `final_regime=sideways`인데 "현재 시장은 흥미로운 국면입니다"만 쓰면, 충돌어는 없지만 대표어(횡보 등)가 없어 계약 위반이다. 그래서 조건 1(대표어 존재)이 필수다.

### 5.4 라벨 사전 예시 (`keyword_rules.py`)

**regime:**

| 코드값 | required_any (대표) | conflict_any (충돌) |
| --- | --- | --- |
| `sideways` | 횡보, 박스권, 방향성 제한 | 상승 전환, 상승 추세, 하락 추세 |
| `overheated` | 과열, 단기 과열, 과매수 | 과매도, 하락 추세 |
| `oversold_rebound_watch` | 과매도, 과매도 반등, 반등 관찰 | 과열, 상승 추세 유지 |
| `bullish_reversal_watch` | 상승 전환 관찰, 반등 신호 관찰 | 하락 추세, 부정 우세 |
| `uptrend_intact` | 상승 추세 유지, 정배열 유지 | 하락 추세, 횡보 |
| `downtrend` | 하락 추세, 약세 흐름 | 상승 전환, 상승 추세 |

**consensus:**

| 코드값 | required_any | conflict_any |
| --- | --- | --- |
| `strong_positive` | 강한 긍정, 긍정 우세 | 부정, 약세 |
| `weak_positive` | 약한 긍정, 제한적 긍정, 긍정 신호 일부 | 부정 우세, 약세 우세 |
| `neutral` | 중립, 신호 엇갈림, 방향성 제한 | 긍정 우세, 부정 우세 |
| `weak_negative` | 약한 부정, 부정 신호 일부 | 긍정 우세, 강한 긍정 |
| `strong_negative` | 강한 부정, 부정 우세 | 긍정, 강세 |

**alignment_flag:** (LLM-03의 역행 맥락 누락을 잡는 사전)

| 코드값 | required_any | conflict_any |
| --- | --- | --- |
| `aligned` | 정합, 상위 추세와 일치, 방향이 일치 | 역행, 상위 추세와 반대 |
| `counter_trend` | 역행, 상위 추세와 반대, 대세 흐름과 반대 | 정합, 방향이 일치 |
| `neutral` | 중립, 방향성 판정 없음, 정합/역행 판정 대상 아님 | 정합, 역행 |

단, `neutral`의 대표 표현인 "정합/역행 판정 대상 아님" 안에 포함된 "정합"·"역행"은 규칙 3(§5.3)에 따라 충돌어로 보지 않는다(대표어와 겹치는 짧은 충돌어 무효화).

`counter_trend`의 검증이 LLM-03에 대응한다 — 확정값이 `counter_trend`인데 문장에 역행 대표어가 하나도 없으면(대표어 부재 = 상위 추세 역행 맥락 누락) 검증 실패다.

**forbidden_terms:** 매수, 매도, 손절, 목표가, 진입, 예상 수익률, 목표 수익률, 수익 보장 (부정문 안에서도 실패). 과거 등락률·변동률처럼 데이터에 기반한 값은 허용하되, 미래 수익률을 예측·보장하는 표현은 금지한다.

### 5.5 종합 해석 왜곡 테스트

| ID | 코드 확정값 | LLM 출력 | 기대 결과 |
| --- | --- | --- | --- |
| LLM-01 | `final_regime=sideways` | "상승 전환이 관찰됩니다." | 실패 (충돌어) |
| LLM-02 | `consensus=weak_positive` | "부정 신호가 우세합니다." | 실패 (충돌어) |
| LLM-03 | `alignment_flag=counter_trend` | 상위 추세 역행 맥락 누락하고 단정 | 실패 (맥락 누락) |
| LLM-04 | 입력에 목표가 없음 | "목표가는 90,000원입니다." | 실패 (금지어 + 수치 생성) |
| LLM-05 | — | "매수 관점입니다." | 실패 (금지어) |
| LLM-06 | `final_regime=sideways` | "현재 시장은 흥미로운 국면입니다." | 실패 (대표어 부재 = 회피형) |
| LLM-07 | `final_regime=bullish_reversal_watch` | "상승 전환 관찰 신호가 나타납니다." | **통과** (교차 오판 방지 확인) |

LLM-07이 중요하다 — 정상 문장인데 "상승 전환"이 downtrend 충돌어와 교차 검사되면 오판된다. 현재 라벨 사전만 검사 + 겹침 무효화로 **통과해야** 한다.

### 5.6 지표별 detail 왜곡 테스트

| ID | 코드 확정값 | LLM 출력 | 기대 결과 |
| --- | --- | --- | --- |
| DETAIL-01 | moving_average `signal=positive` | "이동평균선은 부정적입니다." | 실패 (신호 왜곡) |
| DETAIL-02 | rsi `signal=neutral` | "RSI는 과매수라 부정적입니다." | 실패 (신호 왜곡) |
| DETAIL-03 | 입력 indicator 5개 | detail 4개만 반환 | 실패 (개수 불일치) |
| DETAIL-04 | 입력 `moving_average` | LLM이 `ma`로 반환 | 실패 (코드값 불일치) |
| DETAIL-05 | 입력에 없음 | LLM이 `macd` 생성 | 실패 (없는 indicator) |

`prompts.md` §4.2의 details 병합 안전장치와 연결된다 — 개수·코드값이 입력 `technical_signals`와 정확히 일치해야 한다.

### 5.7 재생성 / 폴백 테스트

| ID | 상황 | 기대 결과 |
| --- | --- | --- |
| REGEN-01 | Prompt 10 출력이 검증 실패 | Prompt 10-R로 1회 재생성 |
| REGEN-02 | 재생성 결과 통과 | `interpretation.source=llm_regenerated` 또는 `detail_source=llm_regenerated` |
| REGEN-03 | 재생성 결과도 실패 | `interpretation.source=template_fallback` 또는 `detail_source=template_fallback` (LLM 문장 버림) |
| REGEN-04 | detail 하나만 실패 | 해당 detail만 `detail_source=template_fallback`, 나머지 유지 |
| REGEN-05 | 재생성 호출 횟수 | `REGEN_MAX_COUNT=1` 초과하지 않음 (무한 루프 없음) |

`usecase.md` T6과 연결된다. 판정은 검증 ③ 코드가 하고, Prompt 10-R은 재생성만 한다(책임 분리, `prompts.md` §5).

### 5.8 한계와 Future Work

키워드 매칭은 결정론적이고 테스트 가능하지만, 문장의 모든 뉘앙스를 완벽히 이해하지는 못한다. MVP에서는 **명시적 라벨 왜곡·반대 방향 표현·금지 표현·indicator 불일치**처럼 확실한 위반을 잡는 데 집중한다.

부정 범위 인식, 조건문 해석, 미묘한 의미 일치 판정은 Future Work로 둔다(LLM-as-judge 또는 분류 모델로 확장 가능). 이는 "모든 문장 의미를 완벽히 검증한다"고 과장하지 않고, **확실히 잡을 수 있는 위반부터 결정론적으로 잡는다**는 honest scoping이다.

---

## 6. 차트 annotation 계산 테스트 (CHART-*)

**성격:** 정상 동작 확인 (코드 계산 검증, 검증 ① 계열). **대상:** `charts/chart_builder.py`의 overlays·subcharts·annotations 계산. 상세 규칙은 `chart_annotation_spec.md`.

| ID | 입력 | 기대 결과 |
| --- | --- | --- |
| CHART-01 | 5MA가 20MA를 상향 돌파 | `golden_cross` 생성 |
| CHART-02 | 5MA가 20MA를 하향 이탈 | `dead_cross` 생성 |
| CHART-03 | 거래량이 20봉 평균의 2배 이상 | `volume_spike` 생성 |
| CHART-04 | 현재가가 최근 지지선 ±2% 이내 | `support_touch` 생성 |
| CHART-05 | 현재가가 최근 저항선 ±2% 이내 | `resistance_touch` 생성 |
| CHART-06 | RSI >= 70 | `rsi_overbought` 생성 |
| CHART-07 | RSI <= 35 | `rsi_oversold` 생성 |
| CHART-08 | 박스권 조건 충족 | `box_range_candidate` 생성 |
| CHART-09 | 데이터 부족 | 해당 annotation 생성하지 않음 (억지 생성 없음) |
| CHART-10 | 같은 kind가 가까운 기간 내 반복 | 중복 제거 규칙 적용 |

**MVP 구현 범위 주의:** 크로스 kind는 `golden_cross`/`dead_cross`로 확정한다(chart_annotation_spec §7). `box_breakout_candidate`·`cup_handle_candidate`는 **이번 MVP 구현 범위에서 제외**(후속). 기간별 candles는 `config.md §10 CHART_PERIOD_DAYS`(3m=90/1y=365/5y=1825일) 기준으로 기본 candle source의 마지막 candle date에서 slice하며, 데이터 부족 시 확보된 봉까지만 쓰고 예외를 내지 않는다. chart_data에는 regime/synthesis/risk 값을 넣지 않는다(순수 chart JSON).

**chart_data 계약 검증(CONTRACT-CHART-*):** `ChartPayload.chart_data`는 `schemas/chart.py`의 `ChartData`로 검증한다(자유 dict 아님). 잘못된 구조·문서에 없는 key(extra)·잘못된 Literal(`candle_unit`·SR `type`·annotation `source`/`importance`)·범위 밖 수치(음수 가격/volume, RSI 0~100 밖, window/period ≤0)는 거부한다. `annotation.kind`는 문서 10종 전체를 계약상 허용하되 chart_builder는 8종만 생성한다. `from` key는 `model_dump(mode="json")`(by_alias 유무 무관)에서 `"from"`으로 유지되고 `"from_"`은 새어나오지 않는다. `test_chart_builder`는 dict 접근 대신 `payload.chart_data.model_dump(mode="json", by_alias=True)`로 최종 JSON을 검증한다.

추가 강화 검증: **inf/nan 거부**(`_to_price` 및 chart/OHLCV float 필드), date/from/to **ISO `YYYY-MM-DD`만**(형식·달력), `annotation.source` **누락 거부(필수)**, candle **`high < low` 거부**, RSI **`oversold >= overbought` 거부**, `ChartPayload` **`period ↔ candle_unit` 불일치 거부**(3m·1y=D, 5y=W).

annotation은 전부 코드가 계산하며 `source=code`다. LLM은 좌표·발생일·가격·패턴 구간을 만들지 않는다.

---

## 7. 출력 계약 테스트

**성격:** 정상 동작 확인. **대상:** `contracts.md` 스키마.

| ID | 입력/상황 | 기대 결과 |
| --- | --- | --- |
| CONTRACT-01 | 정상 리포트 | 필수 최상위 필드(ticker·source·trace_id·data_status·as_of) 모두 존재 |
| CONTRACT-02 | `confidence_level` 포함 | JSON에는 있어도 DB 저장 대상 아님 (재계산 파생값) |
| CONTRACT-03 | `technical_signals[].indicator` 누락 | 실패 |
| CONTRACT-04 | `risk.items[]`에 flag·note·ref_price 포함 | 통과 (index 짝짓기 불필요) |
| CONTRACT-05 | 에이전트가 `html` 필드 반환 | 실패 (에이전트는 JSON만, HTML 안 만듦) |
| CONTRACT-06 | DB 저장 enum이 한글 라벨 | 실패 (DB엔 코드값) |
| CONTRACT-07 | `technical_signals[].detail_source` 존재 | 통과 (llm/llm_regenerated/template_fallback) |

### enum 값 검증

출력의 모든 enum 필드가 `enums.md`의 코드값과 정확히 일치하는지 확인한다. 검증 대상 필드와 허용값:

- `final_regime`: overheated · oversold_rebound_watch · bullish_reversal_watch · uptrend_intact · downtrend · sideways · unavailable
- `alignment_flag`: aligned · counter_trend · neutral
- `consensus`: strong_positive · weak_positive · neutral · weak_negative · strong_negative
- `signal`(개별): positive · neutral · negative
- `data_status`: normal · stale_cache · data_limited · regime_unavailable
- 최상위 `source`(시세 출처): KIS · KIS (stale)
- `interpretation.source` / `detail_source`(문장 출처): llm · llm_regenerated · template_fallback

이 목록 밖의 값이 나오면 실패다. **`source`(최상위, 시세 출처)와 `interpretation.source`·`detail_source`(문장 출처)는 이름은 비슷하나 다른 필드다** — 최상위 `source`에 `llm`이 오거나, 문장 출처에 `KIS`가 오면 실패다.

---

## 8. 예외·복원력 테스트

**성격:** 위반 감지 확인. **대상:** E 하네스.

| ID | 상황 | 기대 결과 |
| --- | --- | --- |
| RES-01 | KIS 1회 실패 후 2회차 성공 | 정상 흐름 복귀 |
| RES-02 | D 호출 3회 모두 실패 + stale daily 있음(1거래일 내) | `data_status=stale_cache`, 최신 시세 미반영 표기 |
| RES-03 | D 호출 3회 모두 실패 + daily 캐시 없음 | `data_status=data_limited`, **환각 데이터 생성 없음** |
| RES-04 | D stale daily가 허용 기간(1거래일) 초과 | `data_status=data_limited` (W/M stale 초과는 RES-10) |
| RES-05 | 봉 수 부족(60MA 불가) | `data_status=regime_unavailable` |
| RES-06 | 재시도 백오프 간격 | 1·2·4초, 최대 3회 초과하지 않음 |
| RES-07 | D 정상, W 실패 + stale weekly 있음 | weekly stale 사용, 최신 주봉 미반영 표시 |
| RES-08 | D 정상, M 실패 + 캐시 없음 | `monthly_trend=unavailable`, `data_status=data_limited`, 일봉 기준 분석 계속 |
| RES-10 | W/M stale 허용 기간(`STALE_CACHE_MAX_AGE_BY_PERIOD`) 초과 | 해당 타임프레임 미확보 처리, trend=unavailable |

`sequence.md`·`config.md`와 연결된다. **핵심은 RES-03** — 데이터가 없으면 없다고 정직하게 빠지고, 환각으로 채우지 않는다.

---

## 9. Trace 기록 테스트

**성격:** 정상 동작 확인. **대상:** D 관측층.

| ID | 상황 | 기대 결과 |
| --- | --- | --- |
| TRACE-01 | 정상 흐름 | request_id·trace_id·노드별 입출력 요약 기록 |
| TRACE-02 | regime 분류 | daily_regime·final_regime·alignment_flag 기록 |
| TRACE-03 | LLM 검증 실패 | 실패 원인·regen_count·최종 문장 출처(`interpretation.source`/`detail_source`) 기록 |
| TRACE-04 | KIS 장애 | retry_count·fallback 여부 기록 |

"왜 이런 결과가 나왔는지" 역추적 가능성을 보장한다. veriθ의 검증 가능성을 데이터로 뒷받침하는 층이다.

---

## 10. 테스트 운영 규약

1. **기대값의 근거는 문서다.** 테스트 기대값은 `regime_rules.md`·`enums.md`·`contracts.md`·`config.md`를 기준으로 한다. 코드가 아니라 문서가 정답이다.
2. **config 변경 시 테스트 검토.** config 값(임계값·가중치)을 바꾸면 관련 테스트 기대값(REG·RES 등)을 함께 검토한다.
3. **검증 ③은 품질이 아니라 위반을 본다.** LLM 출력은 비결정론적이므로, 검증 ③은 "문장이 좋은가"가 아니라 "금지 조건을 위반했는가"만 검사한다.
4. **실패 시 원인 문서를 추적한다.** 테스트가 실패하면 프롬프트를 고칠지(`prompts.md`), 코드 규칙을 고칠지(`regime_rules.md`) 원인 문서를 먼저 특정한다.
5. **검증 ③ 자체도 테스트 대상이다.** `trajectory_eval.py`와 `keyword_rules.py`는 단위테스트로 검증한다(LLM-07 같은 교차 오판 방지 케이스 포함).

---

## 관련 문서

| 문서 | 담당 |
| --- | --- |
| `prompts.md` | 이 테스트가 검증하는 LLM 계약·금지 규칙 |
| `regime_rules.md` | 검증 ② 기대값의 근거 (우선순위·경계 규칙) |
| `enums.md` | enum 값 검증 기준 |
| `contracts.md` | 출력 계약 테스트 기준 |
| `config.md` | 검증 ①·복원력 테스트의 수치 기준 |
| `usecase.md` | T5(검증 ②)·T6(검증 ③) 시나리오 |
| `chart_annotation_spec.md` | 차트 annotation 계산 테스트(CHART-*) 기준 |
