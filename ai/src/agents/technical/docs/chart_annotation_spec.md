# 18. 차트 Annotation 명세 (Chart Annotation Spec)

`docs/chart_annotation_spec.md`

가격/기술적 분석 에이전트가 차트 위에 표시할 기술적 신호, 보조선, 패턴 후보, 서브차트 데이터를 어떻게 계산하고 렌더링할지 정의한다.

이 문서는 화면 디자인 문서가 아니라, **차트에 표시되는 계산 결과의 의미와 JSON 구조**를 정의하는 문서다. 프론트엔드는 이 문서와 `contracts.md`의 `charts[].chart_data`를 기준으로 차트를 렌더링한다.

---

## 1. 문서 목적

1. 차트에 표시할 기술적 신호와 보조선을 정의한다.
2. 이동평균선, 거래량, RSI, 지지·저항, 패턴 후보의 계산 기준을 정한다.
3. 기간별 차트에서 어떤 annotation을 얼마나 표시할지 정한다.
4. Backend/AI가 반환할 `chart_data` 구조를 명확히 한다.
5. 프론트가 임의로 신호를 만들지 않고, 코드가 계산한 annotation만 렌더링하게 한다.

---

## 2. 기본 원칙

차트 annotation은 사용자의 투자 행동을 지시하는 것이 아니라, **기술적 관찰 지점**을 시각적으로 표시하는 것이다. 따라서 차트에는 다음 표현을 쓰지 않는다(`frontend_mapping.md` §14 금지 UI와 동일 기준).

| 금지 표현 | 대체 표현 |
| --- | --- |
| 매수 | 긍정 신호 |
| 매도 | 부정 신호 |
| 진입 | 관찰 구간 |
| 손절 | 리스크 관찰 |
| 목표가 | 참고 가격 |
| 추천 | 참고 |

차트 annotation은 모두 코드가 계산한다. LLM은 차트 위의 좌표, 신호 발생일, 지지·저항 가격, 패턴 구간을 만들지 않는다.

```text
계산/탐지: code
렌더링: frontend
설명 문장: LLM 또는 template
```

---

## 3. 차트 기간과 캔들 단위

MVP 차트 기간은 다음을 기준으로 한다. 각 봉은 KIS `inquire-daily-itemchartprice`의 D/W/M 원본이다(`kis_mapping.md`).

| 차트 기간 | 기본 봉 | 보조 봉 | 표시 목적 |
| --- | --- | --- | --- |
| `3m` | 일봉(D) | - | 최근 흐름과 단기 신호 확인 |
| `1y` | 일봉(D) | 주봉(W) | 중기 흐름과 주요 신호 확인 |
| `5y` | 주봉(W) | 월봉(M) | 장기 추세와 핵심 구간 확인 |

`period` enum 정본은 `enums.md` §10이며 MVP는 `3m`/`1y`/`5y`다.

`chart_data.candle_unit`은 화면에 직접 그리는 **주 봉 단위**를 의미한다(위 표의 "기본 봉"). 보조 봉은 상위 추세·annotation 중요도 판단에 사용하며, 별도 캔들 배열로 기본 제공하지 않는다. 보조 봉 데이터까지 화면에 표시해야 하는 경우 Future Work에서 `auxiliary_series`를 추가한다.

### 3.1 1일 장중 차트의 위치 (Beta / Future Work)

`1d` 차트는 **MVP 핵심 국면 판단에 사용하지 않는다.** MVP의 최종 기술 국면(`final_regime`), 신호 종합(`signal_score`), 신뢰도(`confidence`)는 일봉·주봉·월봉 기준으로만 계산한다. `1d` 차트는 장중 흐름을 참고하기 위한 **보조 화면**이며, 최종 판단 값을 변경하지 않는다.

| 항목 | MVP 반영 여부 |
| --- | --- |
| `final_regime` 계산 | 반영하지 않음 |
| `signal_score` 계산 | 반영하지 않음 |
| `confidence` 계산 | 반영하지 않음 |
| 차트 표시 | Beta / Future Work |
| 장중 거래량 급증 표시 | Future Work |
| 분봉 RSI 표시 | Future Work |

`1d`를 정식 지원하려면 다음이 필요하다: KIS **분봉 전용 API**(`inquire-daily-itemchartprice`의 D/W/M과 다른 TR), 분봉 캐시(`ohlcv:minute:{ticker}`, TTL 1분), 장중 갱신 주기, `enums.md`·`config.md`의 `period` 확장, 별도 테스트. MVP는 이 확장을 열어두되 스코프에 넣지 않는다.

용어 주의: "실시간"이 아니라 **"장중/분봉/준실시간 참고 차트"**로 표기한다. WebSocket 틱 스트리밍은 별개 기능이며 MVP·Beta 범위 밖이다. 분봉 REST 조회(1~5분 갱신)까지가 Beta 후보다.

---

## 4. 기간별 annotation 표시 정책

모든 기간에 모든 신호를 똑같이 표시하지 않는다. 기간이 길어질수록 신호가 많아져 차트가 복잡해지므로, 장기 차트에서는 핵심 annotation만 남긴다.

| 기간 | 표시 수준 | 표시 규칙 |
| --- | --- | --- |
| `3m` | 상세 | 최근 크로스, RSI 상태, 거래량 급증, 지지·저항 터치 |
| `1y` | 중간 | 주요 크로스, 강한 거래량 신호, 의미 있는 지지·저항 |
| `5y` | 요약 | 장기 추세, 핵심 지지·저항, 주요 패턴 후보만 |

표시 개수가 너무 많으면 최신 신호와 중요도가 높은 신호를 우선한다.

---

## 5. chart_data 기본 구조

`contracts.md`의 `charts[].chart_data`는 다음 구조를 따른다. `period`는 `charts[]` 레벨에, `candle_unit`과 실제 데이터(candles·overlays·subcharts·annotations)는 `chart_data` 안에 둔다(이중 중첩 없음).

이 구조는 `schemas/chart.py`의 `ChartData` Pydantic 모델로 계약 검증한다(자유 dict 아님). key 이름은 이 문서를 정본으로 하며 바꾸지 않는다 — 특히 `support_resistance`의 `from`은 alias로 유지한다. 하위 모델은 `extra="forbid"`(단 `annotation.meta`는 자유 `dict`)이고, candles는 내부 표준 `OHLCV`를 재사용한다.

**계약 강화 규칙:** 수치 필드는 **inf/nan을 허용하지 않는다**(비정상 값은 fail-fast, `_to_price`도 동일). 모든 date/from/to는 **ISO `YYYY-MM-DD`만** 허용한다(실제 달력 날짜 검증). `annotation.source`는 **필수**이며 `"code"`만 허용한다(§6). candle은 `high >= low`, RSI 서브차트는 `oversold < overbought`여야 한다. `ChartPayload.period`와 `chart_data.candle_unit`은 §3 규정(3m·1y=D, 5y=W)과 정합해야 한다.

```json
{
  "period": "1y",
  "chart_data": {
    "candle_unit": "D",
    "candles": [
      { "date": "2026-06-30", "open": 80000.0, "high": 81000.0, "low": 79000.0, "close": 80500.0, "volume": 12345678, "trading_value": 987654321000 }
    ],
    "overlays": {
      "moving_average": [
        { "window": 5, "points": [ { "date": "2026-06-30", "value": 80300.0 } ] },
        { "window": 20, "points": [] },
        { "window": 60, "points": [] }
      ],
      "support_resistance": [
        { "type": "support", "price": 79000.0, "from": "2026-03-01", "to": "2026-06-30", "touch_count": 3 },
        { "type": "resistance", "price": 84950.0, "from": "2026-03-01", "to": "2026-06-30", "touch_count": 2 }
      ]
    },
    "subcharts": {
      "rsi": { "period": 14, "overbought": 70, "oversold": 35, "points": [ { "date": "2026-06-30", "value": 58.2 } ] },
      "volume": { "avg_window": 20, "bars": [ { "date": "2026-06-30", "volume": 12345678, "avg_volume": 10000000, "is_spike": false } ] }
    },
    "annotations": [
      { "id": "ann_001", "kind": "golden_cross", "date": "2026-05-14", "price": 83200.0, "label": "골든크로스", "importance": "medium", "source": "code" }
    ]
  }
}
```

구조 요약: `charts[].period`=기간 / `chart_data.candle_unit`=봉 단위 / `chart_data.candles·overlays·subcharts·annotations`=실제 차트 데이터. `373220`(LG에너지솔루션) 기준 예시이며, 값은 설명용이다.

---

## 6. annotation 공통 필드

`annotations[]`의 각 항목은 다음 필드를 가진다.

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `id` | string | YES | annotation 고유 ID |
| `kind` | string | YES | annotation 종류 |
| `date` | string | YES | 발생일 |
| `price` | number/null | NO | 차트 위 표시 가격 |
| `label` | string | YES | 프론트 표시 라벨 |
| `importance` | string | YES | low/medium/high |
| `source` | string | YES | code |
| `meta` | object | NO | 세부 계산 근거 |

`source`는 MVP에서 항상 `code`다. LLM이 annotation을 생성하지 않는다.

---

## 7. annotation kind

| kind | 표시 라벨 | 의미 | MVP |
| --- | --- | --- | --- |
| `golden_cross` | 골든크로스 | 단기 이동평균선이 중장기 이동평균선을 상향 돌파 | ✅ |
| `dead_cross` | 데드크로스 | 단기 이동평균선이 중장기 이동평균선을 하향 돌파 | ✅ |
| `volume_spike` | 거래량 급증 | 거래량이 최근 평균 대비 크게 증가 | ✅ |
| `support_touch` | 지지선 근접 | 가격이 주요 지지 구간에 근접 | ✅ |
| `resistance_touch` | 저항선 근접 | 가격이 주요 저항 구간에 근접 | ✅ |
| `rsi_overbought` | RSI 과열 | RSI가 과열 기준 이상 | ✅ |
| `rsi_oversold` | RSI 과매도 | RSI가 과매도 기준 이하 | ✅ |
| `box_range_candidate` | 박스권 후보 | 일정 기간 가격이 제한된 범위에서 움직임 | ✅ |
| `box_breakout_candidate` | 박스권 이탈 관찰 | 박스권 상단/하단을 이탈한 후보 | ⏳ 후속 |
| `cup_handle_candidate` | 컵앤핸들 후보 | 컵앤핸들 형태로 볼 수 있는 후보 구간 | ⏳ 후속 |

크로스 kind는 MVP 구현에서 `golden_cross`/`dead_cross`로 확정한다(§8은 이동평균선 크로스 규칙을 정의한다). `box_breakout_candidate`·`cup_handle_candidate`는 오탐 가능성이 크고 구현 난도가 높아 **MVP 구현 범위에서 제외**하고 후속 단계에서 별도 문서·테스트 보강 후 구현한다(§12.2·§13 규칙은 정본으로 유지).

패턴 관련 annotation은 확정이 아니라 **후보(candidate)**로 표기한다. 패턴 탐지는 오탐 가능성이 높으므로 "확정" 표현을 쓰지 않는다(honest scoping).

`annotation.kind`의 허용값 정본은 이 문서다. 전역 enum(`enums.md`)에는 넣지 않고, 차트 렌더링 전용 값으로 이 문서에서 관리한다.

---

## 8. 이동평균선 annotation 규칙

### 8.1 계산 대상

이동평균선은 `config.md`의 `MA_WINDOWS`(= `[MA_SHORT_WINDOW, MA_MID_WINDOW, MA_LONG_WINDOW]`, 기본 `[5, 20, 60]`)를 따른다. short=단기, mid=중기, long=장기. 아래 표의 `5MA/20MA/60MA`는 기본값 기준 표기이며, 골든/데드크로스는 **고정 숫자가 아니라 역할(short·mid·long) 조합의 교차**로 판정한다 — window 값이 바뀌면 교차 대상 숫자도 함께 바뀐다.

### 8.2 골든크로스

이전 봉 `short_ma <= long_ma`, 현재 봉 `short_ma > long_ma`이면 `golden_cross`를 생성한다.

| 조합 (역할) | 중요도 |
| --- | --- |
| short MA 상향 돌파 mid MA (기본 5MA/20MA) | medium |
| mid MA 상향 돌파 long MA (기본 20MA/60MA) | high |

### 8.3 데드크로스

이전 봉 `short_ma >= long_ma`, 현재 봉 `short_ma < long_ma`이면 `dead_cross`를 생성한다.

| 조합 (역할) | 중요도 |
| --- | --- |
| short MA 하향 이탈 mid MA (기본 5MA/20MA) | medium |
| mid MA 하향 이탈 long MA (기본 20MA/60MA) | high |

### 8.4 중복 제거

같은 종류의 크로스가 가까운 기간 안에 반복되면 중복 표시를 줄인다.

중복 제거는 **달력일이 아니라 candle(봉) index 거리**로 계산한다(주말·휴장일 왜곡 방지). 창 값 정본은 `config.md §10 ANNOTATION_DEDUP_BARS`다.

| 기간 | 기본 봉 | 중복 제거 창(봉 index) |
| --- | --- | --- |
| `3m` | 일봉 | 5봉 이내 동일 kind 중복 제거 |
| `1y` | 일봉 | 10봉 이내 동일 kind 중복 제거 |
| `5y` | 주봉 | 4봉(≈4주) 이내 동일 kind 중복 제거 |

---

## 9. 거래량 annotation 규칙

### 9.1 계산 대상

거래량 평균은 `config.md`의 `VOLUME_AVG_WINDOW = 20`을 따른다.

### 9.2 거래량 급증

`현재 거래량 >= 최근 20봉 평균 거래량 × VOLUME_SPIKE_MULTIPLIER`이면 `volume_spike`를 생성한다. MVP 기본값 `VOLUME_SPIKE_MULTIPLIER = 2.0`(config.md에 정의).

### 9.3 거래대금 보조 기준

국내 시장은 거래대금도 중요하므로 함께 본다. `현재 거래대금 >= 최근 20봉 평균 거래대금 × TRADING_VALUE_SPIKE_MULTIPLIER`(MVP `= 2.0`, config.md에 정의).

거래량 또는 거래대금 중 하나만 급증해도 annotation을 생성할 수 있으며, `meta.triggered_by`에 어떤 기준으로 감지했는지 기록한다.

```json
{ "kind": "volume_spike", "date": "2026-06-30", "label": "거래량 급증", "importance": "medium",
  "meta": { "volume_ratio": 2.3, "trading_value_ratio": 1.8, "triggered_by": ["volume"] } }
```

주의: 이 급증 기준(`VOLUME_SPIKE_MULTIPLIER`)은 차트 표시용이며, 유동성 판정(`low_liquidity`, `MIN_AVG_VOLUME`/`MIN_AVG_TRADING_VALUE`, `config.md`)과는 별개 규칙이다.

---

## 10. 지지선·저항선 annotation 규칙

### 10.1 계산 대상

탐색 기간·근접 임계값은 `config.md`를 따른다: `SUPPORT_LOOKBACK_DAYS = 20`, `NEAR_SUPPORT_THRESHOLD_PCT = 0.02`, `NEAR_RESISTANCE_THRESHOLD_PCT = 0.02`.

### 10.2 지지선

최근 N봉 내 유사 가격대에서 저점이 2회 이상 발생하고 현재가가 그 가격대 ±2% 이내이면 `support_touch`를 생성한다.

### 10.3 저항선

최근 N봉 내 유사 가격대에서 고점이 2회 이상 발생하고 현재가가 그 가격대 ±2% 이내이면 `resistance_touch`를 생성한다.

### 10.4 표시 방식

지지·저항은 선과 annotation을 분리한다. `overlays.support_resistance`=수평선, `annotations[]`=터치·근접 이벤트.

```json
{ "type": "resistance", "price": 84950.0, "from": "2026-03-01", "to": "2026-06-30", "touch_count": 2 }
{ "kind": "resistance_touch", "date": "2026-06-15", "price": 84600.0, "label": "저항선 근접", "importance": "medium", "source": "code" }
```

---

## 11. RSI annotation 규칙

### 11.1 계산 대상

`config.md`: `RSI_PERIOD = 14`, `RSI_OVERBOUGHT = 70`, `RSI_OVERSOLD = 35`.

### 11.2 과열 / 과매도

`RSI >= RSI_OVERBOUGHT`이면 `rsi_overbought`("RSI 과열"), `RSI <= RSI_OVERSOLD`이면 `rsi_oversold`("RSI 과매도")를 생성한다.

### 11.3 표시 방식

RSI는 메인 차트가 아니라 서브차트(`subcharts.rsi`)에 표시한다. 프론트는 기준선 이상/이하 구간을 시각적으로 강조할 수 있다.

---

## 12. 박스권 annotation 규칙

박스권은 확정 패턴이 아니라 후보 구간으로 표시한다.

### 12.1 박스권 후보

최근 N봉 동안 고점·저점 범위가 일정 비율 이내이고 가격이 그 범위 안에서 2회 이상 왕복하면 `box_range_candidate`를 생성한다. MVP 기본값(config.md에 정의): `BOX_LOOKBACK_DAYS = 40`, `BOX_RANGE_THRESHOLD_PCT = 0.12`, `BOX_MIN_TOUCH_COUNT = 2`.

### 12.2 박스권 이탈 후보

현재 종가가 박스권 상단/하단을 이탈하고 거래량이 최근 평균 대비 증가하면 `box_breakout_candidate`를 생성한다. "돌파 확정"이 아니라 **"이탈 관찰"**로 표시한다.

---

## 13. 컵앤핸들 annotation 규칙

오탐 가능성이 높은 패턴이므로 MVP에서는 후보 탐지까지만 한다.

### 13.1 컵앤핸들 후보

① 이전 고점 형성 → ② 완만한 하락 후 둥근 저점 → ③ 이전 고점 부근 회복 → ④ 짧은 조정. MVP 기본값(config.md에 정의): `CUP_LOOKBACK_DAYS = 120`, `CUP_MIN_DEPTH_PCT = 0.10`, `CUP_MAX_DEPTH_PCT = 0.40`, `HANDLE_MAX_PULLBACK_PCT = 0.15`.

### 13.2 표시 방식

```json
{ "kind": "cup_handle_candidate", "date": "2026-06-30", "label": "컵앤핸들 후보", "importance": "low", "source": "code",
  "meta": { "cup_start": "2026-01-10", "cup_bottom": "2026-03-15", "cup_end": "2026-05-20", "handle_start": "2026-05-21", "handle_end": "2026-06-15" } }
```

---

## 14. annotation 중요도

차트가 복잡해지지 않도록 중요도를 둔다.

| importance | 의미 | 표시 방식 |
| --- | --- | --- |
| high | 장기 추세나 핵심 신호 | 라벨 표시 |
| medium | 중기 신호 | 작은 라벨 또는 강조 마커 |
| low | 참고 후보 | 작은 마커 또는 토글 표시 |

기간별 기본 표시: `3m`=high+medium+일부 low, `1y`=high+medium, `5y`=high 중심. 프론트는 토글로 low도 표시할 수 있다.

---

## 15. 중복 annotation 제한

### 15.1 동일 kind 중복 제거

같은 kind가 가까운 기간 안에 반복되면 가장 최근 또는 중요도가 높은 것만 남긴다(§8.4 기준).

### 15.2 같은 날짜 복수 신호

같은 날짜에 여러 신호가 발생하면 프론트가 묶어 표시할 수 있다. MVP에서는 별도 그룹 필드를 만들지 않고 프론트가 같은 날짜 annotation을 묶는다.

---

## 16. 프론트 렌더링 규칙

프론트는 `chart_data`를 그대로 렌더링하며, 별도로 신호를 계산하거나 annotation을 생성하지 않는다.

| 데이터 | 렌더링 |
| --- | --- |
| `candles` | 캔들 또는 라인 차트 |
| `overlays.moving_average` | 이동평균선 |
| `overlays.support_resistance` | 수평 지지·저항선 |
| `subcharts.rsi` | RSI 서브차트 |
| `subcharts.volume` | 거래량 서브차트 |
| `annotations[]` | 마커, 라벨, 음영, 툴팁 |

토글(이동평균선·RSI·거래량·지지저항·패턴 후보)은 표시 여부만 바꾸며, 신호 계산 결과 자체를 바꾸지 않는다.

---

## 17. 데이터 부족 처리

데이터가 부족하면 annotation을 억지로 생성하지 않는다(전체 흐름의 data_limited/regime_unavailable 원칙과 동일).

| 상황 | 처리 |
| --- | --- |
| MA 계산 봉 부족 | 해당 MA line/annotation 제외 |
| RSI 계산 봉 부족 | RSI subchart 제외 또는 unavailable |
| 거래량 평균 부족 | volume_spike annotation 제외 |
| 지지·저항 탐색 봉 부족 | support/resistance overlay 제외 |
| 패턴 탐지 기간 부족 | pattern candidate 제외 |

제외된 annotation은 trace에 기록한다.

```json
{ "indicator": "rsi", "status": "unavailable", "reason": "not enough bars for RSI_PERIOD=14" }
```

---

## 18. trace 기록

annotation 생성 과정은 trace(`chart_generate` 노드)에 남긴다: `period`, `candle_unit`, `calculated_overlays`, `generated_annotations`, `skipped_annotations`, `deduplicated_annotations`.

```json
{
  "node": "chart_generate",
  "output_summary": {
    "period": "1y", "candle_unit": "D",
    "generated_annotations": { "golden_cross": 2, "volume_spike": 3, "support_touch": 1, "resistance_touch": 2 },
    "skipped_annotations": [ { "kind": "cup_handle_candidate", "reason": "not enough bars" } ]
  }
}
```

---

## 19. 테스트 기준

`test_plan.md`에 다음을 추가한다.

| ID | 입력 | 기대 결과 |
| --- | --- | --- |
| CHART-01 | 5MA가 20MA를 상향 돌파 | golden_cross 생성 |
| CHART-02 | 5MA가 20MA를 하향 이탈 | dead_cross 생성 |
| CHART-03 | 거래량이 20봉 평균의 2배 이상 | volume_spike 생성 |
| CHART-04 | 현재가가 최근 지지선 ±2% 이내 | support_touch 생성 |
| CHART-05 | 현재가가 최근 저항선 ±2% 이내 | resistance_touch 생성 |
| CHART-06 | RSI >= 70 | rsi_overbought 생성 |
| CHART-07 | RSI <= 35 | rsi_oversold 생성 |
| CHART-08 | 박스권 조건 충족 | box_range_candidate 생성 |
| CHART-09 | 데이터 부족 | 해당 annotation 생성하지 않음 |
| CHART-10 | 같은 kind가 가까운 기간 내 반복 | 중복 제거 규칙 적용 |

---

## 20. 관련 문서

| 문서 | 역할 |
| --- | --- |
| `contracts.md` | `charts[].chart_data` 출력 계약 |
| `frontend_mapping.md` | 차트 UI 렌더링 기준 |
| `config.md` | 지표 기간·임계값 (chart 전용 신규 상수 포함) |
| `regime_rules.md` | 지표와 국면 판정 연결 |
| `test_plan.md` | annotation 계산 테스트 (CHART-*) |
| `trace_schema.md` | annotation 생성 trace |
