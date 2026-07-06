# 14. 프론트엔드 매핑 (Frontend Mapping)

`docs/frontend_mapping.md`

가격/기술적 분석 에이전트의 출력 JSON을 프론트엔드 화면에 어떻게 렌더링할지 정의한다. 이 문서는 화면 디자인 자체가 아니라, **`contracts.md`의 JSON 필드와 UI 섹션의 매핑 기준**을 정의한다.

---

## 1. 문서 목적

1. `contracts.md`의 출력 JSON 필드를 화면 섹션에 매핑한다.
2. enum 코드값을 사용자 표시 라벨로 변환하는 기준을 정의한다(`enums.md` 기준).
3. null·fallback·data_limited 상태에서 화면이 어떻게 안전하게 표시될지 정의한다.
4. **코드 확정값과 LLM 설명 문장을 화면에서 구분해 표시한다**(코드=청록, LLM=보라).
5. 사용자에게 매수/매도 판단처럼 보이는 표현을 피하는 UI 규칙을 정의한다.

---

## 2. 기준 문서와 역할

| 문서 | 역할 |
| --- | --- |
| `contracts.md` | 프론트가 받는 JSON 구조의 기준 |
| `enums.md` | enum 코드값과 표시 라벨 기준 |
| `schema.md` | backend 저장 구조 기준 |
| `trace_schema.md` | 실행 과정 trace 기준 |
| `frontend_mapping.md` | JSON 필드 → 화면 렌더링 기준 |

> HTML 시안은 화면 배치·디자인 참고용이며, 데이터 매핑의 최종 기준은 `contracts.md`다(§15).

---

## 3. 화면 전체 구조

1. 리포트 헤더
2. 최종 국면 요약
3. 신호·신뢰도 요약
4. 멀티프레임 국면
5. 지표별 기술 신호
6. 리스크 관찰 포인트
7. 차트 영역
8. 종합 해석
9. 검증·출처 표시
10. 예외 상태 화면

**색 규칙 (전 화면 공통):** 코드가 확정한 값(판정·수치·국면)은 **청록**, LLM이 서술한 문장(detail·interpretation)은 **보라**. 사용자가 "무엇이 계산이고 무엇이 해석인지" 한눈에 구분하게 한다.

---

## 4. 리포트 헤더 매핑

| 화면 요소 | JSON 경로 | 표시 방식 |
| --- | --- | --- |
| 종목 코드 | `ticker` | 텍스트 |
| 분석 기준 시각 | `as_of` | `YYYY.MM.DD HH:mm` |
| 데이터 출처 | `source` | 작은 텍스트 또는 배지 (KIS / KIS (stale)) |
| 데이터 상태 | `data_status` | 상태 배지 |

**data_status 표시 라벨 (§13 예외 렌더링과 연결):**

| 코드값 | 표시 라벨 | 화면 처리 |
| --- | --- | --- |
| `normal` | 정상 | 기본 표시 (배지 생략 가능) |
| `stale_cache` | 최신 시세 미반영 | 주의 배지 (+ 보조 안내 문구) |
| `data_limited` | 데이터 제한 | 제한 안내 |
| `regime_unavailable` | 판단 불가 | 판단 불가 카드 |

---

## 5. 최종 국면 요약 매핑

| 화면 요소 | JSON 경로 | 표시 방식 |
| --- | --- | --- |
| 최종 국면 | `regime.final_regime` | 국면 배지 (청록) |
| 일봉 국면 | `regime.daily_regime` | 보조 텍스트 |
| 정합/역행 여부 | `regime.alignment_flag` | 배지 |
| 국면 맥락 | `regime.regime_context` | 설명 문장 |

**국면 표시 라벨 (`enums.md` 기준):**

| 코드값 | 표시 라벨 |
| --- | --- |
| `overheated` | 과열 |
| `oversold_rebound_watch` | 과매도 반등 관찰 |
| `bullish_reversal_watch` | 상승 전환 관찰 |
| `uptrend_intact` | 상승 추세 유지 |
| `downtrend` | 하락 추세 |
| `sideways` | 횡보 |
| `unavailable` | 판단 불가 |

**alignment_flag 표시 라벨:** `aligned`=정합 / `counter_trend`=역행 / `neutral`=중립

---

## 6. 신호·신뢰도 요약 매핑

| 화면 요소 | JSON 경로 | 표시 방식 |
| --- | --- | --- |
| 종합 신호 | `signal.consensus` | 배지 |
| 신호 점수 | `signal.signal_score` | 숫자 또는 게이지 |
| 신뢰도 | `signal.confidence` | 퍼센트/게이지 |
| 신뢰도 등급 | `signal.confidence_level` | high/medium/low 라벨 |
| 신뢰도 근거 | `signal.confidence_basis` | 설명 문장 |

`confidence_level`은 출력 JSON에는 포함되지만 DB에는 저장하지 않는 파생값이다(`confidence` float에서 산출). 프론트는 출력 JSON의 값을 그대로 쓰거나, 없을 경우 `confidence`에서 파생한다.

**consensus 표시 라벨:** `strong_positive`=긍정 우세 / `weak_positive`=약한 긍정 / `neutral`=중립 / `weak_negative`=약한 부정 / `strong_negative`=부정 우세

> **UI 규칙:** `signal_score`는 방향성·강도이고 `confidence`는 신뢰도다. 두 값을 같은 의미로 표시하지 않는다. (예: score 게이지와 confidence 게이지를 시각적으로 구분)

---

## 7. 멀티프레임 국면 매핑

| 화면 요소 | JSON 경로 | 표시 방식 |
| --- | --- | --- |
| 일봉 | `regime.daily_regime` | 카드 또는 칩 |
| 주봉 | `regime.weekly_trend` | 카드 또는 칩 |
| 월봉 | `regime.monthly_trend` | 카드 또는 칩 |
| 정합 여부 | `regime.alignment_flag` | 정합/역행/중립 배지 |
| 설명 | `regime.regime_context` | 문장 |

**trend 표시 라벨:** `up`=상승 / `down`=하락 / `sideways`=횡보 / `unavailable`=판단 불가

중립 국면(과열·과매도·횡보)은 `alignment_flag=neutral`이므로 정합/역행 배지 대신 "중립" 또는 배지 미표시로 처리한다.

---

## 8. 지표별 기술 신호 매핑

`technical_signals[]`는 지표별 카드로 렌더링한다.

| 화면 요소 | JSON 경로 | 표시 방식 | 출처 |
| --- | --- | --- | --- |
| 지표명 | `technical_signals[].indicator` | 표시 라벨 | 코드 |
| 신호 | `technical_signals[].signal` | 긍정/중립/부정 배지 (청록) | 코드 |
| 대표 수치 | `technical_signals[].value` | 숫자 (청록). **`null`이면 0이 아니라 "계산 불가"/"—"로 표시**(`contracts.md` `float \| None` — 데이터 부족 등으로 산출 불가) | 코드 |
| 계산 지표 칩 | `technical_signals[].metrics[]` | 칩 리스트 (청록) | 코드 |
| 설명 | `technical_signals[].detail` | 문장 (보라) | LLM |
| 설명 출처 | `technical_signals[].detail_source` | 작은 출처 표시 | — |
| 가중치 | `technical_signals[].weight` | 보조 정보 | 코드 |

> **핵심 UI 경계:** `signal`·`value`·`metrics`·`weight`는 **코드 확정값(청록)**이고, `detail`만 **LLM/템플릿 문장(보라)**이다. 한 카드 안에서 이 경계를 색으로 구분한다. 이것이 "판정은 코드, 설명은 LLM"을 화면에서 증명하는 지점이다.

**indicator 표시 라벨:** `moving_average`=이동평균 / `rsi`=RSI / `volume`=거래량 / `support_resistance`=지지·저항 / `pattern`=패턴

**signal 표시 라벨:** `positive`=긍정 / `neutral`=중립 / `negative`=부정

**detail_source 표시:**

| 출처 | 표시 |
| --- | --- |
| `llm` | AI 설명 |
| `llm_regenerated` | AI 재생성 설명 |
| `template_fallback` | 검증된 템플릿 설명 |

---

## 9. 리스크 관찰 포인트 매핑

| 화면 요소 | JSON 경로 | 표시 방식 |
| --- | --- | --- |
| 리스크 유형 | `risk.items[].flag` | 라벨 |
| 설명 | `risk.items[].note` | 문장 |
| 참고 가격 | `risk.items[].ref_price` | 가격 또는 `-` |

> 리스크 관찰 포인트는 투자 행동 지시가 아니다. "진입"·"손절"·"매수"·"매도"처럼 보이는 UI 문구를 쓰지 않는다(§14).

**risk flag 표시 라벨 (`enums.md` 기준):**

| 코드값 | 표시 라벨 |
| --- | --- |
| `volume_not_confirmed` | 거래량 확인 약함 |
| `near_resistance` | 저항 구간 근접 |
| `near_support` | 지지 구간 근접 |
| `mixed_signals` | 신호 엇갈림 |
| `overheated_momentum` | 단기 과열 관찰 |
| `counter_higher_trend` | 상위 추세와 역행 |
| `low_liquidity` | 유동성 낮음 |

---

## 10. 차트 영역 매핑

| 화면 요소 | JSON 경로 | 표시 방식 |
| --- | --- | --- |
| 기간 탭 | `charts[].period` | 3m/1y/5y 탭 |
| 차트 데이터 | `charts[].chart_data` | 캔들/라인 차트 |

**period 표시 라벨:** `3m`=3개월 / `1y`=1년 / `5y`=5년 / `1d`=1일(장중, 조건부)

차트 annotation 렌더링은 `chart_annotation_spec.md`의 `annotations[]`·`overlays`·`subcharts` 구조를 따른다. 프론트는 별도로 신호를 계산하지 않고 코드가 준 `chart_data`만 렌더링한다.

**`charts`는 개수 고정이 아니다 — period 집합으로 처리:** `3m`·`1y`·`5y`는 항상 존재하고, `1d`(장중 분봉)는 **intraday 데이터가 있을 때만 조건부로** 포함된다. 프론트는 `charts.length == 3`을 가정하지 말고 `charts[].period` 집합으로 탭을 구성한다. `chart_data`는 **`candle_unit` 판별 유니온**이다: D/W/M은 `ChartData`(candle_unit `D`/`W`/`M`, 봉 시각은 `date`=`YYYY-MM-DD`), `1d`는 `IntradayChartData`(candle_unit `1min`, 봉 시각은 `timestamp`=`YYYY-MM-DDTHH:MM:SS`). 프론트는 `candle_unit`으로 두 구조를 분기해 렌더한다.

**1일(`1d`) 탭 (Beta):** 장중 흐름 참고용이며 MVP 핵심 판단에 미반영이다. 최종 국면·신호·신뢰도는 일봉·주봉·월봉 기준으로 계산된 값을 그대로 표시한다. `IntradayChartData`는 `candles`(1분봉)·`previous_close`·`day_high/low`·`short_ma`를 담고(vwap·rsi는 선택), 관측·힌트 요약은 **`intraday_context`**(optional)로 온다: `intraday_regime_hint`(장중 흐름 힌트)·`regime_alignment`(D/W/M 국면과의 정합)·`confidence_adjustment`·`risk_notes`. **`confidence_adjustment`는 참고용 설명값(cap ±0.05)이며 top-level `signal.confidence`에 이미 반영된 값이 아니다** — 프론트는 최종 신뢰도를 바꾸는 값으로 표시하지 않는다. `signal_score_adjustment`는 0.0이다. `risk_notes`는 `intraday_context` 내부의 중립 표현 문자열 리스트로, 기존 `risk.items[]`와 별개다. 프론트는 `1d` 탭에 안내 문구를 표시할 수 있다: "장중 차트는 현재 흐름 참고용이며, 최종 기술 국면은 일봉·주봉·월봉 기준으로 계산됩니다." (상세: `chart_annotation_spec.md` §3.1) intraday 마커 annotation은 아직 제공하지 않는다(Phase 3).

---

## 11. 종합 해석 매핑

| 화면 요소 | JSON 경로 | 표시 방식 |
| --- | --- | --- |
| 종합 해석 | `interpretation.text` | 본문 문장 (보라) |
| 해석 출처 | `interpretation.source` | 출처 표시 |

> `interpretation.text`는 코드 확정값을 바탕으로 생성된 설명 문장이다. 최종 국면·신호·신뢰도 값을 덮어쓰지 않는다. 화면에서는 보라 계열로 "LLM 해석"임을 표시한다.

`interpretation.source`는 §8의 detail_source와 같은 값 집합(llm/llm_regenerated/template_fallback)을 쓴다.

---

## 12. 검증·출처 표시

`verification`은 출력 JSON에 포함되지만, **일반 사용자 화면에는 요약 배지만** 표시하고 상세는 관리자/디버그 뷰에서 본다.

| 화면 요소 | JSON 경로 | 표시 방식 |
| --- | --- | --- |
| 검증 결과 요약 | `verification.outcome` | 배지 (일반 사용자용: passed면 "검증 완료" 정도) |
| 계산 검증 | `verification.calc_passed` | 통과/실패 (상세 뷰) |
| 국면 규칙 검증 | `verification.regime_passed` | 통과/실패 (상세 뷰) |
| 라벨 일치 검증 | `verification.label_matched` | 통과/실패 (상세 뷰) |
| 재생성 횟수 | `verification.regen_count` | 숫자 (상세 뷰) |
| trace ID | `trace_id` | 디버그/관리자용 |

일반 사용자 화면에서는 "계산 검증·재현 가능" 같은 신뢰 배지 수준으로 작게 표시하고, 상세 검증 항목은 관리자/디버그 뷰로 분리한다.

**verification.outcome 표시 라벨:**

| 코드값 | 일반 사용자 표시 | 관리자/디버그 표시 |
| --- | --- | --- |
| `passed` | 검증 완료 | passed |
| `regenerated` | 재검증 후 완료 | regenerated |
| `template_fallback` | 안전 문장으로 대체 | template_fallback |
| `failed` | 검증 실패 | failed |

일반 사용자에겐 기술 용어(template_fallback 등)를 그대로 노출하지 않고, 디버그 뷰에서만 원본 코드값을 보여준다.

---

## 13. 예외 상태 렌더링

### 13.1 regime_unavailable (판단 불가)

| 조건 | 화면 처리 |
| --- | --- |
| `data_status=regime_unavailable` | 판단 불가 안내 카드 표시 |
| `signal=null` | 신호·신뢰도 영역 숨김 또는 비활성 |
| `technical_signals=[]` | 지표별 신호 영역 숨김 |
| `risk=null` | 리스크 영역 숨김 |
| `interpretation.source=template_fallback` | 템플릿 안내 문장 표시 |

### 13.2 stale_cache

| 조건 | 화면 처리 |
| --- | --- |
| `data_status=stale_cache` | "최신 시세 미반영" 배지 표시 + 보조 문구 "최신 시세가 아직 반영되지 않아 이전 캐시 기준으로 표시됩니다." |
| `source=KIS (stale)` | 출처에 stale 표시 |

### 13.3 template_fallback

| 조건 | 화면 처리 |
| --- | --- |
| `interpretation.source=template_fallback` | 검증된 템플릿 문장 표시 |
| `detail_source=template_fallback` | 해당 지표 설명에 템플릿 출처 표시 |

### 13.4 data_limited

`data_limited`는 두 가지 경우로 나뉜다. D가 확보된 경우(A)에는 부분 분석 가능 상태이고, D도 확보하지 못한 경우(B)에는 분석 불가 상태로 안전 착지한다. 프론트는 `regime.final_regime`이 `unavailable`인지로 A/B를 구분한다.

| 조건 | 화면 처리 |
| --- | --- |
| `data_status=data_limited` + `final_regime != unavailable` (A) | "일부 데이터 제한" 배지 표시, 일봉 기준 분석 결과 표시 |
| `weekly_trend=unavailable` 또는 `monthly_trend=unavailable` | 해당 타임프레임 카드에 "데이터 제한" 표시 |
| `data_status=data_limited` + `final_regime=unavailable` (B) | 분석 불가 안내 카드 표시 |

> Future Work: 타임프레임별 stale 여부를 세밀히 구분해야 하면 `timeframe_status.daily/weekly/monthly`를 별도 필드로 분리한다. MVP는 리포트 전체 `data_status`+보조 문구로 처리한다(W만 stale이어도 전체를 stale로 표시).

> 예외 상태에서도 화면이 깨지지 않고 "왜 이 정보가 없는지"를 사용자에게 정직하게 안내한다. 빈 값을 억지로 채우지 않는다.

---

## 14. 금지 UI 문구

프론트엔드는 사용자에게 투자 행동을 지시하는 문구를 표시하지 않는다. `prompts.md`의 LLM 금지어가 화면 출력단까지 이어지는 지점이다.

| 금지 표현 | 대체 표현 |
| --- | --- |
| 매수 | 긍정 신호 |
| 매도 | 부정 신호 |
| 손절 | 리스크 관찰 |
| 진입 | 관찰 구간 |
| 목표가 | 참고 가격 |
| 추천 | 참고 |
| 예상 수익률 | 과거 등락률 또는 변동률 |
| 목표 수익률 | 사용하지 않음 |
| 수익 보장 | 사용하지 않음 |

과거 등락률·변동률처럼 데이터에 기반한 값은 허용하되, 미래 수익률을 예측·보장하는 표현은 쓰지 않는다(`prompts.md`·`test_plan.md` 금지어와 동일 기준).

---

## 15. HTML 시안과의 관계

HTML 시안은 화면 레이아웃·스타일 참고용이다. `frontend_mapping.md`의 최종 기준은 HTML 구조가 아니라 `contracts.md`의 출력 JSON이다.

HTML 시안의 섹션 구성은 참고할 수 있지만, **JSON에 없는 필드를 화면에서 임의로 만들지 않는다.** 화면에 필요한 데이터가 JSON에 없다면 `contracts.md`를 먼저 수정한다(그다음 이 문서 → 화면).

> HTML은 디자인 참고 자료이고, 데이터 계약의 기준은 아니다. 지금까지 "이 칸이 코드냐 LLM이냐"의 혼란은 HTML을 데이터 기준으로 착각한 데서 왔다 — 기준은 항상 contracts JSON이다.

---

## 16. 관련 문서

| 문서 | 담당 |
| --- | --- |
| `contracts.md` | 출력 JSON 구조 (매핑의 기준) |
| `schema.md` | backend 저장 구조 |
| `enums.md` | 코드값과 표시 라벨 |
| `trace_schema.md` | 실행 과정 추적 로그 |
| `prompts.md` | LLM 출력 금지 표현 (화면 금지어와 연결) |
| `chart_annotation_spec.md` | 차트 overlays·subcharts·annotations 렌더링 기준 |
