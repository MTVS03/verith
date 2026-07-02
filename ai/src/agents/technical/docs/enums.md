# 3. 열거값 정의 (Enums)

`docs/enums.md`

에이전트가 산출하는 모든 열거형 값을 정의한다. **코드값(영문)**은 코드·DB·API에서 쓰고, **표시 라벨(한글)**은 프론트 화면에서 쓴다. 이 문서가 세 계층(코드·DB·프론트)의 단일 기준이다. 값을 추가·변경하면 이 문서를 먼저 고친다.

---

## 1. regime (국면) — `final_regime`, `daily_regime`

| 코드값 | 표시 라벨 | 성격 |
| --- | --- | --- |
| `oversold_rebound_watch` | 과매도 반등 관찰 | 중립 |
| `overheated` | 과열 | 중립 |
| `bullish_reversal_watch` | 상승 전환 관찰 | 긍정 |
| `uptrend_intact` | 상승 추세 유지 | 긍정 |
| `downtrend` | 하락 추세 | 부정 |
| `sideways` | 횡보 | 중립 |
| `unavailable` | 판단 불가 | — |

`daily_regime`과 `final_regime`은 같은 값 집합을 쓴다. 멀티프레임 보정은 라벨을 바꾸지 않는다.

**성격**과 `risk_flags`는 별개 축이다. 성격은 `alignment_flag` 판정에만 쓴다. 예를 들어 `overheated`는 성격상 중립이다. 방향성이 없고 정합/역행 판정을 하지 않는다. 하지만 리스크로는 `overheated_momentum` flag가 붙을 수 있다. 방향성 판단과 리스크 판단을 섞지 않는다.

---

## 2. consensus (신호 종합)

| 코드값 | 표시 라벨 | `signal_score` 범위 |
| --- | --- | --- |
| `strong_positive` | 긍정 우세 | score ≥ 0.5 |
| `weak_positive` | 약한 긍정 | 0.3 ≤ score < 0.5 |
| `neutral` | 중립 | -0.3 < score < 0.3 |
| `weak_negative` | 약한 부정 | -0.5 < score ≤ -0.3 |
| `strong_negative` | 부정 우세 | score ≤ -0.5 |

매수·매도 동시 존재 + `|score| < 0.3`이면 `neutral`로 표기하고 **신호 엇갈림**을 함께 표시한다.

`signal_score` 경계값은 MVP 잠정값이며 백테스트로 조정할 수 있다.

---

## 3. signal (지표별 개별 신호) — `report_signals.signal`

| 코드값 | 표시 라벨 |
| --- | --- |
| `positive` | 긍정 |
| `neutral` | 중립 |
| `negative` | 부정 |

5개 지표 각각이 이 세 값 중 하나를 낸다. 가중 집계되어 `signal_score`가 된다.

개별 카드도 “매수/매도”가 아니라 긍정/부정으로 표시한다. 종합(`consensus`)과 톤을 통일해 화면 전체가 사실 서술을 유지하도록 한다.

---

## 4. trend (타임프레임 추세) — `weekly_trend`, `monthly_trend`

| 코드값 | 표시 라벨 |
| --- | --- |
| `up` | 상승 |
| `down` | 하락 |
| `sideways` | 횡보 |
| `unavailable` | 판단 불가 |

봉 수 부족으로 주/월봉 추세를 낼 수 없으면 `unavailable`로 처리한다.

---

## 5. alignment_flag (멀티프레임 정합)

| 코드값 | 표시 라벨 | 의미 |
| --- | --- | --- |
| `aligned` | 정합 | 일봉 국면과 상위 추세 방향 일치 |
| `counter_trend` | 역행 | 일봉 국면과 상위 추세 방향 반대 |
| `neutral` | 중립 | 판정 대상 아님. 횡보·과열·과매도 등 성격 중립 국면 |

---

## 6. confidence_level (신뢰도 구간) — 표시용

`confidence`는 `0.0~1.0` float로 저장하되, 화면에는 구간 라벨로 표시한다.

| 코드값 | 표시 라벨 | `confidence` 범위 |
| --- | --- | --- |
| `high` | 높음 | ≥ 0.7 |
| `medium` | 보통 | 0.4 ≤ c < 0.7 |
| `low` | 낮음 | < 0.4 |

경계값은 config에서 관리한다.

```python
CONFIDENCE_HIGH = 0.7
CONFIDENCE_MEDIUM = 0.4
```

위 값은 MVP 잠정값이다.

화면에서는 숫자보다 `confidence_basis`를 더 크게 보여준다.

예:

```text
신뢰도: 보통
근거: 5개 중 긍정 2·중립 2·부정 1로 일부 엇갈림
```

---

## 7. risk_flags (리스크 라벨) — 코드 생성 배열

코드가 생성하는 구조화된 리스크 라벨이다. `risk_notes` 문장은 이 플래그 안에서만 생성된다. `regime` 성격과 별개 축이며, 방향성이 아니라 리스크 경고를 담당한다.

| 코드값 | 표시 라벨 | 판정 |
| --- | --- | --- |
| `volume_not_confirmed` | 거래량 확인 약함 | 거래량이 20일 평균 대비 뚜렷이 증가하지 않음 |
| `near_resistance` | 저항 구간 근접 | 현재가가 주요 저항 구간 근처 |
| `near_support` | 지지 구간 근접 | 현재가가 주요 지지 구간 근처. 양면적이므로 사실 서술만 사용 |
| `mixed_signals` | 신호 엇갈림 | 지표 신호가 긍정·부정으로 엇갈림 |
| `overheated_momentum` | 단기 과열 관찰 | RSI 과매수 구간 |
| `counter_higher_trend` | 상위 추세와 역행 | 일봉 신호가 기준 상위 추세(월봉 우선, 월봉 unavailable 시 주봉)와 반대 |
| `low_liquidity` | 유동성 낮음 | 최근 20일 평균 거래량 또는 거래대금이 기준 미만 |

목록은 확장 가능하다. 각 flag는 하나 이상의 정해진 `risk_notes` 문장 템플릿에 대응한다.

### near_support 주의

지지 근처는 양면적이다. “반등 관찰 지점”일 수도 있고, “이탈 시 약화”일 수도 있다. 문장은 절대 “매수 기회”로 쓰지 않고 사실 서술로만 간다.

예:

```text
현재 가격은 최근 지지 구간에 가까워, 이 구간에서의 가격 반응이 기술적 해석에 중요한 참고 지점입니다.
```

### low_liquidity 기준

한국 시장은 거래량보다 거래대금이 유동성 지표로 유의미할 수 있다. 저가주는 거래량이 많아도 거래대금이 작을 수 있기 때문이다.

MVP는 거래량 기준(`MIN_AVG_VOLUME`)과 거래대금 기준(`MIN_AVG_TRADING_VALUE`)을 함께 사용한다. 둘 중 하나라도 기준 미만이면 `low_liquidity`를 부여한다.

---

## 8. data_status (데이터/분석 상태) — `technical_reports.data_status`

| 코드값 | 표시 라벨 | 언제 |
| --- | --- | --- |
| `normal` | 정상 | 데이터 정상 확보 |
| `stale_cache` | 최신 시세 미반영 | KIS 실패 + stale 캐시 폴백. 일부 또는 전체 타임프레임이 최신봉까지 반영되지 않음 |
| `data_limited` | 데이터 제한 | KIS 실패 + 캐시도 없음, 또는 상위 타임프레임(W/M) 일부 미확보 |
| `regime_unavailable` | 판단 불가 | 봉 수 부족으로 국면 판정 불가. 종합·신뢰도 스킵 |

`regime_unavailable`은 엄밀히는 데이터 수집 실패가 아니라 분석 봉 수 부족이다. MVP에서는 넓은 의미의 “분석 상태”로 하나에 묶는다.

Future Work:

```text
data_status: normal / stale_cache / data_limited
analysis_status: normal / regime_unavailable
```

---

## 9. 해석 출처 (source) — `interpretation_source` · `detail_source`

LLM이 생성하는 자연어 문장의 최종 출처를 나타낸다. **`interpretation_source`(종합 해석)와 `detail_source`(지표별 설명)가 이 값 집합을 공유한다.**

| 코드값 | 표시 라벨 | 의미 |
| --- | --- | --- |
| `llm` | AI 설명 | 1차 LLM 문장이 검증 통과 |
| `llm_regenerated` | AI 재생성 설명 | 검증 실패 후 재생성한 문장이 통과 |
| `template_fallback` | 검증된 템플릿 설명 | 재생성도 실패해 코드 템플릿으로 대체 |

`trace`와 함께 어떤 문장이 LLM 원문인지 템플릿 폴백인지 사후 구분에 쓰인다. veriθ의 **검증 가능한 리포트 생성**을 데이터로 증명하는 필드다.

- **`interpretation_source`** — 리포트 상단 종합 해석 문장(`interpretation.text`)의 출처. 리포트당 1개.
- **`detail_source`** — 각 지표 설명 문장(`technical_signals[].detail`)의 출처. 지표마다 1개. 지표 detail도 검증 ③ 대상이며, 실패 시 해당 지표만 템플릿 폴백으로 떨어진다.

---

## 10. period (차트 기간) — `report_charts.period`

| 코드값 | 표시 라벨 | 봉 종류 |
| --- | --- | --- |
| `3m` | 3개월 | 일봉 |
| `1y` | 1년 | 일봉/주봉 |
| `5y` | 5년 | 주봉/월봉 |

기간 토글에 대응한다. 각 봉 종류(일봉/주봉/월봉)는 KIS D/W/M 원본을 쓴다.

Future Work: `1m`, `6m`, `3y` 등 확장 가능.

---

## 사용 규약

1. **코드값은 영문 snake_case, 불변.** 한 번 정하면 안 바꾼다. DB 마이그레이션·API 호환 때문이다. 라벨(한글)은 UI 사정으로 바꿔도 된다.
2. **DB에는 코드값 저장.** 표시 라벨은 프론트에서 매핑한다. DB에 한글 저장 금지.
3. **매수/매도 단어 — 사용자 노출 문구에서 금지.** 사용자에게 노출되는 코드값·라벨·리포트 문장에서는 "매수/매도"를 쓰지 않는다. honest scoping을 지키기 위함이다. 단, 코드 내부 주석이나 도메인 설명에서 불가피한 경우는 예외다. 미래 수익률을 예측·보장하는 표현(예상 수익률·목표 수익률·수익 보장)도 사용자 노출 문구에서 쓰지 않는다(과거 등락률·변동률 같은 데이터 기반 값은 허용).
4. **regime 성격과 risk_flags는 별개 축.** 성격은 방향성(alignment) 판정용, `risk_flags`는 리스크 경고용이다. 섞지 않는다.
5. **값 추가 시 이 문서 먼저.** 코드·DB·프론트보다 이 문서를 먼저 고치고 세 곳에 반영한다.
