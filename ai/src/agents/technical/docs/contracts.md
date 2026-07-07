# 4. 데이터 계약 (Contracts)

`docs/contracts.md`

가격/기술적 분석 에이전트의 입출력 계약을 정의한다. 에이전트는 **입력 스키마 1개**를 받고 **출력 JSON 1개**를 반환한다. 에이전트는 화면(HTML)을 만들지 않는다 — 데이터만 반환하며, 렌더링은 프론트가 담당한다. 출력 JSON의 각 필드가 ERD 어느 테이블·컬럼에 대응하는지도 함께 정의한다(backend 저장용).

### 의존 방향

`frontend → backend → ai(내 에이전트)   [HTTP only, 단방향]`

- 에이전트는 DB를 직접 만지지 않는다. **구조화된 JSON을 반환만** 한다.
- backend가 그 JSON을 받아 ERD에 저장하고 frontend에 제공한다.
- frontend가 데이터로 화면을 렌더한다(목록에선 요약, 클릭 시 상세).
- 시세 캐시(Redis)만 에이전트가 소유한다(분석의 일부).

> **화면 렌더링 규약:** 에이전트는 완성된 HTML을 출력하지 않는다. JSON 데이터만 반환하고, 프론트가 통일된 디자인으로 렌더한다. (이는 5개 에이전트 공통 계약이어야 한다 — 팀 차원에서 "데이터만 반환" 방식을 통일한다.)

### 1. 입력 계약 (Top Supervisor → ai)

Top Supervisor가 쿼리를 도메인별로 변형해 넘긴다. 에이전트는 아래만 받는다.

```json
{
  "ticker": "373220",
  "query": "LG에너지솔루션 최근 시세·거래량 패턴과 기술적 신호 분석해줘",
  "request_id": "req_abc123",
  "as_of": "2026-06-30T14:30:00+09:00"
}
```

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `ticker` | string | ✅ | 종목 코드 (6자리) |
| `query` | string | ✅ | 변형된 도메인 질의 (기술적 분석 관점) |
| `request_id` | string | ✅ | 요청 추적용 ID (trace 연결). **런타임 필드** — 출력 JSON에 그대로 되돌려주지만 DB에 저장하지 않는다(영구 추적은 `trace_id`·`report_id` 기준). 따라서 저장된 리포트 조회 응답에는 없을 수 있다. |
| `as_of` | ISO8601 | ✅ | 분석 기준 시점. **리포트 표시 기준일이자 KIS 조회 종료일(`end_date`)로도 사용된다** — supervisor가 `data_collect`에 넘겨 KIS D/W/M 조회의 종료일로 스레딩한다(생략 불가한 입력이라 항상 존재). **미래 `as_of`는 거부**(ValueError). 자세한 흐름은 `kis_mapping.md §8.2`. |

*에이전트는 다른 에이전트의 존재를 모른다. 위 4개만 받으면 독립 동작한다.*

### 2. 출력 계약 (ai → Top Supervisor → backend)

JSON 데이터만 반환한다. 의미 단위로 중첩 구조를 유지한다(backend가 테이블별로 flatten해 저장). 아래 JSON은 설명을 위한 축약 예시이며, 정상 리포트에서는 기본 5개 지표(moving_average·rsi·volume·support_resistance·pattern)가 `technical_signals[]`에 포함된다.

```json
{
  "request_id": "req_abc123",
  "ticker": "373220",
  "as_of": "2026-06-30T14:30:00+09:00",
  "source": "KIS",
  "trace_id": "trace_xyz789",
  "data_status": "normal",

  "regime": {
    "daily_regime": "overheated",
    "final_regime": "overheated",
    "weekly_trend": "up",
    "monthly_trend": "up",
    "alignment_flag": "neutral",
    "regime_context": "상위 추세는 상승이나 일봉 기준 단기 과열이 관찰됩니다."
  },

  "signal": {
    "consensus": "weak_positive",
    "signal_score": 0.30,
    "confidence": 0.42,
    "confidence_level": "medium",
    "confidence_basis": "5개 지표 중 긍정 2·중립 2·부정 1로 일부 신호가 엇갈립니다."
  },

  "technical_signals": [
    {
      "indicator": "moving_average",
      "signal": "positive",
      "value": 82900,
      "metrics": ["5MA 82,900", "20MA 81,400", "60MA 80,600"],
      "detail": "20일선이 60일선을 상향 돌파해 골든크로스가 관찰됩니다.",
      "detail_source": "llm",
      "weight": 0.30
    },
    {
      "indicator": "rsi",
      "signal": "neutral",
      "value": 58.2,
      "metrics": ["RSI(14) 58.2", "기준 35 / 70"],
      "detail": "RSI는 58로 과매수·과매도 어느 쪽도 아닌 중립 구간입니다.",
      "detail_source": "llm",
      "weight": 0.20
    }
  ],

  "risk": {
    "items": [
      {
        "flag": "volume_not_confirmed",
        "note": "거래량 확인이 약해 현재 신호의 강도는 제한적입니다.",
        "ref_price": null
      },
      {
        "flag": "near_resistance",
        "note": "현재 가격은 최근 저항 구간에 가까워, 이 구간에서의 가격 반응과 변동성 변화를 관찰할 필요가 있습니다.",
        "ref_price": 87500
      }
    ]
  },

  "charts": [
    { "period": "3m", "chart_data": {} },
    { "period": "1y", "chart_data": {} },
    { "period": "5y", "chart_data": {} }
  ],


  "interpretation": {
    "text": "현재 차트는 상승 추세 안에서 단기 과열 신호가 관찰되며, 거래량 확인이 충분하지 않아 신호 강도는 제한적으로 해석됩니다.",
    "source": "llm"
  },

  "verification": {
    "calc_passed": true,
    "regime_passed": true,
    "label_matched": true,
    "outcome": "passed",
    "regen_count": 0
  }
}
```

위 정상 출력 예시의 `charts[].chart_data: {}`는 축약 표기이며, 실제 구조는 `chart_annotation_spec.md`의 `candle_unit`·`candles`·`overlays`·`subcharts`·`annotations`를 따른다. 위 예시의 `charts`는 D/W/M 3종(`3m`·`1y`·`5y`)이며, 장중 분봉(`1d`)은 조건부로만 추가된다(아래 "1D intraday" 참조).

#### 필드 그룹 설명

| 그룹 | 의미 | 대응 테이블 |
| --- | --- | --- |
| 최상위 (ticker·source·trace_id·data_status·as_of) | 리포트 정체성·상태 | TECHNICAL_REPORTS |
| `regime` | 멀티프레임 국면 | TECHNICAL_REPORTS |
| `signal` | 신호 종합·신뢰도 | TECHNICAL_REPORTS |
| `technical_signals[]` | 지표별 기술 신호 | REPORT_SIGNALS |
| `risk.items[]` | 리스크 관찰점 | REPORT_RISK_NOTES |
| `charts[]` | 기간별 차트 | REPORT_CHARTS |
| `interpretation` | 국면 해석 문장 | REPORT_INTERPRETATION |
| `verification` | 검증 결과 | REPORT_VERIFICATION |

*`technical_signals`·`indicator`는 "전략"이 아니라 "지표"를 정확히 가리킨다(내용 정확성 + honest scoping). risk는 `items[]`로 flag·note·ref_price를 한 항목에 묶어 index 짝짓기 오류를 방지한다.*

> **`technical_signals.pattern` ≠ chart 패턴 탐지기 (역할 분리):** `technical_signals`의 `pattern` 지표는 컵앤핸들·박스권 같은 **chart pattern detector가 아니다** — 현재는 **최신 candle의 방향성(bullish/bearish/neutral) 요약**에 가깝다(`synthesis/signal_score.py`). `cup_handle_candidate`·`box_breakout_candidate`는 **chart annotations**(`chart_annotation_spec.md §1.1·§7.1`)에서 표현되는 **패턴 후보**이며, v1에서는 `signal_score`·`final_regime`·top-level `confidence`/`risk`에 **직접 반영하지 않는다**(annotation-only). `pattern` 지표 이름 재검토는 계약 변경이라 별도 phase.*

#### `technical_signals[]` — 코드 확정과 LLM 서술의 경계

한 항목 안에서 필드마다 출처가 다르다. **판정·수치는 코드가 확정하고, 설명 문장만 LLM이 그 확정값을 서술한다.** 이 경계가 veriθ 신뢰성 설계의 축이며, 리포트 화면에서도 시각적으로 구분해 표시한다(코드=청록, LLM=보라).

| 필드 | 출처 | 설명 |
| --- | --- | --- |
| `indicator` | **코드** | 지표 종류 (moving_average·rsi·volume·support_resistance·pattern) |
| `signal` | **코드** | 긍정/중립/부정 판정 (`enums.md` signal). LLM이 바꿀 수 없다 |
| `value` | **코드** | 대표 수치 (결정론 계산 결과). **계산 가능하면 숫자, 데이터 부족 등으로 계산 불가하면 `null`** (`float \| None`). `null`은 0을 의미하지 않는다 — 계산 불가를 정직히 표현한다(예: 봉 부족으로 거래량비 산출 불가). |
| `metrics[]` | **코드** | 화면 표시용 계산 수치 칩 배열 (예: `"5MA 82,900"`). 결정론 산출물 |
| `detail` | **LLM** | 위 확정값(signal·value·metrics)을 자연어로 푼 설명 문장 |
| `detail_source` | — | `detail`의 최종 출처: `llm` / `llm_regenerated` / `template_fallback` |
| `weight` | **코드** | 가중치 (`config.md` INDICATOR_WEIGHTS) |

**`detail` 생성·검증 규약:**

1. **단일 호출 원칙.** `detail` 문장들은 지표마다 LLM을 따로 부르지 않는다. 노드 10에서 `interpretation.text`(종합 해석)와 **함께 한 번의 LLM 호출**로 생성한다. LLM 호출 횟수·비용·지연은 기존 설계(LLM 3곳) 그대로다.
2. **판정 불변.** LLM은 `signal`·`value`·`metrics`를 바꿀 수 없다. `detail`은 이미 확정된 값을 서술만 한다. "긍정"인데 "약세" 뉘앙스로 쓰는 것도 왜곡이다.
3. **검증 ③ 대상.** 각 `detail`은 해당 지표의 코드 확정 `signal`과 일치하는지 trajectory eval로 검사한다(`interpretation.text`와 동일한 검증 축). 불일치 시 재생성 1회 → 실패 시 해당 지표의 `detail`을 코드 템플릿 문장으로 폴백하고 `detail_source="template_fallback"`으로 표기한다.
4. **매수/매도 금지.** `detail` 문장도 사용자 노출 문구이므로 "사라/팔라"가 아니라 관찰·서술 톤을 쓴다(`enums.md` 사용 규약 3).

#### 1D intraday (Beta) — `charts[].period="1d"` 조건부 + `intraday_context`(optional)

장중 분봉(1d)은 **보조 화면**이다(정본: `chart_annotation_spec.md §3.1`). **기존 D/W/M 계약은 그대로 유지되며**, 아래는 그 위에 얹히는 **선택적** 확장이다.

- **`ChartPeriod`에 `1d` 추가.** 기존 D/W/M 차트는 계속 `3m`·`1y`·`5y` 3종이며 **항상 존재**한다. `1d`는 **intraday 데이터가 있을 때만** `charts[]`에 조건부로 추가된다.
- **`charts`는 더 이상 항상 `len == 3`이 아니다.** 소비 측(프론트·backend)은 총개수가 아니라 **period 집합**으로 처리한다: `{3m, 1y, 5y}`는 반드시 존재하고, `1d`는 있을 수도 없을 수도 있다.
- **`charts[].chart_data`는 판별 유니온** `ChartData | IntradayChartData`이며 **판별자는 `candle_unit`**이다: D/W/M → `ChartData`(`candle_unit` ∈ {`D`,`W`,`M`}), 1d intraday → `IntradayChartData`(`candle_unit` = `1min`).
- **시간 축 분리.** 기존 `OHLCV.date`는 **날짜 전용(`YYYY-MM-DD`)** 을 그대로 유지한다(D/W/M candles·차트 계약 불변). intraday 봉은 별도 `IntradayCandle.timestamp`(`YYYY-MM-DDTHH:MM:SS`)를 쓴다.
- **`IntradayChartData` 필수 필드:** `candle_unit="1min"` · `candles[]`(IntradayCandle) · `previous_close` · `day_high` · `day_low` · `short_ma[]`. `vwap`·`rsi`는 선택(빈 배열로 예약). volume은 `candles[].volume`으로 표현한다.

**`intraday_context` (optional, top-level):** `TechnicalAgentOutput.intraday_context: IntradayContext | None`(기본 `null`). 없어도 기존 D/W/M 출력은 그대로 통과한다.

| 필드 | 의미 |
| --- | --- |
| 관측값 | `status` · `latest_price` · `intraday_return_pct` · `day_high`/`day_low` · `day_range_position` · `cumulative_volume` · `cumulative_trading_value` · `volume_spike` · `short_ma` · `vwap` 등. `latest_price`·`cumulative_volume`·`cumulative_trading_value`는 **KIS output1 정본값(fetcher metadata) 우선**, 없으면 candle fallback(마지막 close·분봉 volume 합; `cumulative_trading_value`는 candle 합산 불가라 metadata만) — `kis_mapping.md §12.5` |
| `intraday_regime_hint` | 장중 흐름 요약 힌트(`upward_intraday`/`downward_intraday`/`sideways_intraday`/`volatile_intraday`/`unavailable`). **판단이 아니라 힌트** |
| `regime_alignment` | D/W/M `final_regime`과 힌트의 정합(`aligned`/`counter`/`neutral`/`unavailable`) |
| `confidence_adjustment` | **context 내부 설명값.** 계약상 `[-cap, +cap]`(`cap = INTRADAY_CONFIDENCE_ADJUSTMENT_CAP = 0.05`, `config.md §12`) — **`IntradayContext` 스키마가 `Field(ge=-cap, le=cap)`로 직접 강제**한다. v1 구현: aligned=+cap, counter=−cap, 그 외 0.0(volatile은 양수 금지). **현재 top-level `signal.confidence`에 직접 반영하지 않는다** |
| `signal_score_adjustment` | 계약상 `[-cap, +cap]`(같은 `cap`, 스키마가 강제) — **v1 구현은 항상 0.0**(미조정). 범위를 `0.0`으로 고정(`Literal[0.0]`)하지 않고 ±cap을 열어 둔 것은 Phase 2에서 계약 변경 없이 사용하기 위함이다(B안) |
| `risk_notes` | 기존 `RiskFlag`(enums) 확장이 아니라 **`intraday_context` 내부 중립 표현 문자열 리스트**. **최대 `INTRADAY_RISK_NOTE_MAX_COUNT`(=3)개 — 스키마가 `Field(max_length=3)`로 강제**한다. 기존 `risk.items[]`와 별개 |

**불변식:** intraday는 **`final_regime`을 덮어쓰지 않는다**(읽기 전용). 현재 단계에서 **top-level `confidence`·`signal_score`·`risk` 구조는 intraday로 변경하지 않는다**(보정값은 `intraday_context` 내부 설명용). `confidence_adjustment`·`signal_score_adjustment`(±cap)·`risk_notes`(≤3) 경계는 **문서 관례가 아니라 Pydantic 스키마가 강제**하며, 그 정본 상수는 `config.py §14`/`config.md §12`다. `intraday_context`는 아직 전용 저장 테이블에 매핑하지 않는다(런타임/Beta — 저장 여부는 후속 결정).

**구현 상태 (Beta) — 리포트 생성 시 함께 포함(best-effort):** KIS 분봉 매핑은 공식 샘플로 확정됐고(`kis_mapping.md §12`), **`kis_client.fetch_minute_ohlcv`는 구현 완료**다. 1D intraday는 **프론트 1d 탭 클릭 시 따로 조회하는 구조가 아니라, 리포트 생성 요청 1회에 D/W/M(3m/1y/5y)과 함께 조립**된다. 활성 조건: `config.INTRADAY_FETCH_ENABLED=True`(`.env`/환경변수 override 가능) **또는** 명시 `intraday_fetcher` 주입. 이때 supervisor가 `run()` 안에서 D/W/M 뒤에 분봉을 조회해 `charts`에 `1d`와 `intraday_context`를 얹는다. **기본(flag False·미주입)** 이면 기존 D/W/M과 동일(1d 없음). **D/W/M은 필수 데이터, 1D intraday는 best-effort** — fetch 실패·빈 응답은 D/W/M output 실패로 전파되지 않고 intraday만 생략된다(`intraday_context=None`, 1d 미포함). **날짜 정합성:** KIS 주식당일분봉조회는 당일 데이터만 제공하므로, `as_of`가 당일이 아니면(반환 분봉 날짜 ≠ `as_of.date()`) 과거 리포트에 오늘 분봉이 붙지 않도록 **1d를 생략**한다. `intraday_candles` 직접 주입 경로는 테스트/fixture/manual 용도로 유지된다. intraday annotation(캔들 위 마커 등)은 **Phase 3 / Future Work**로 현재 구현된 것처럼 기술하지 않는다.

### 3. JSON ↔ ERD 매핑 (backend 저장 기준)

#### → `TECHNICAL_REPORTS` (본체, 1행)

| JSON 경로 | 컬럼 |
| --- | --- |
| `ticker` | ticker |
| `regime.final_regime` | final_regime |
| `regime.daily_regime` | daily_regime |
| `regime.weekly_trend` | weekly_trend |
| `regime.monthly_trend` | monthly_trend |
| `regime.alignment_flag` | alignment_flag |
| `regime.regime_context` | regime_context |
| `signal.consensus` | consensus |
| `signal.signal_score` | signal_score |
| `signal.confidence` | confidence |
| `signal.confidence_basis` | confidence_basis |
| `data_status` | data_status |
| `trace_id` | trace_id |
| `source` | source |
| `as_of` | as_of |
| (저장 시각) | created_at |

*`signal.confidence_level`은 저장하지 않는다 — confidence float에서 재계산 가능한 파생값이며, 경계값이 바뀌면 저장값이 꼬인다. 프론트가 confidence로 매핑한다.*

*`alignment_flag`·`regime_context`는 저장한다 — 재계산이 아니라 그 시점의 판단 결과이며, 필터("정합 리포트만")·재현성 추적에 쓰인다.*

#### → `REPORT_INTERPRETATION` (1:1)

| JSON 경로 | 컬럼 |
| --- | --- |
| `interpretation.text` | interpretation |
| `interpretation.source` | interpretation_source |

*긴 text라 본체에서 분리 — 목록 조회 시 딸려오지 않게 해 리스트를 가볍게 유지한다.*

#### → `REPORT_SIGNALS` (1:N, 지표 수만큼)

| JSON 경로 (`technical_signals[]`) | 컬럼 |
| --- | --- |
| `indicator` | indicator |
| `signal` | signal |
| `value` | value |
| `metrics` | metrics (json 배열) |
| `detail` | detail |
| `detail_source` | detail_source |
| `weight` | weight |

*JSON·DB 모두 `indicator`로 통일 — "전략"이 아니라 "지표"를 정확히 가리키며, 필드명이 같아 매핑에 번역이 없다.*
*`metrics`는 화면 표시용 계산 수치 칩 배열이라 json으로 저장한다. `detail_source`는 그 지표 설명 문장이 LLM 원문인지 템플릿 폴백인지 사후 구분용(`interpretation_source`와 같은 축).*

#### → `REPORT_CHARTS` (1:N, 기간 수만큼)

| JSON 경로 (`charts[]`) | 컬럼 |
| --- | --- |
| `period` | period |
| `chart_data` | chart_data (json) |

`chart_data`의 세부 구조(`candles`·`overlays`·`subcharts`·`annotations`)와 annotation 계산·표시 규칙은 `chart_annotation_spec.md`를 따른다.

`chart_data`는 자유 dict가 아니라 **`schemas/chart.py`의 `ChartData` Pydantic 계약으로 검증**한다(`ChartPayload.chart_data: ChartData`). 모든 하위 모델은 `extra="forbid"`이며(단, `ChartAnnotation.meta`는 계산 근거용 자유 `dict`), candles는 내부 표준 `OHLCV`를 재사용한다. `support_resistance`의 `from` key는 파이썬 예약어라 `Field(alias="from")` + `serialize_by_alias=True`로 처리해 **입력·출력 모두 `"from"`을 유지**한다. `annotation.kind`는 `chart_annotation_spec.md §7`의 **전체 10종을 계약상 허용**한다(chart_builder는 MVP 8종만 생성).

**계약 강화:** chart_data 수치는 **inf/nan 불허**(fail-fast), date/from/to는 **ISO `YYYY-MM-DD`만**, `annotation.source`는 **필수·`"code"`만**, candle은 `high >= low`, RSI는 `oversold < overbought`, `ChartPayload.period ↔ chart_data.candle_unit`은 정합(3m·1y=D, 5y=W)해야 한다. `pydantic>=2.11`(`serialize_by_alias`).

#### → `REPORT_RISK_NOTES` (1:N)

`risk.items[]`의 각 항목을 그대로 한 행으로 저장(짝짓기 불필요).

| JSON 경로 (`risk.items[]`) | 컬럼 |
| --- | --- |
| `flag` | flag |
| `note` | note |
| `ref_price` | ref_price |

#### → `REPORT_VERIFICATION` (1:1)

| JSON 경로 (`verification`) | 컬럼 |
| --- | --- |
| `calc_passed` | calc_passed |
| `regime_passed` | regime_passed |
| `label_matched` | label_matched |
| `outcome` | outcome |
| `regen_count` | regen_count |

### 4. 예외 상태의 출력

정상이 아닐 때도 계약은 유지되며, 상태 필드로 표현한다. 아래 예외 예시는 핵심 필드만 보여주는 축약 예시다. 실제 출력 JSON에는 정상 출력과 동일하게 `request_id`·`ticker`·`as_of`·`source`·`trace_id`·`data_status` 등 최상위 필드가 항상 포함된다.

**regime 판단 불가 (봉 부족):** (아래 예시는 차트 생성에 필요한 최소 데이터도 부족해 `charts`가 빈 배열인 경우다.)

```json
{
  "data_status": "regime_unavailable",
  "regime": {
    "final_regime": "unavailable",
    "daily_regime": "unavailable",
    "weekly_trend": "unavailable",
    "monthly_trend": "unavailable",
    "alignment_flag": "neutral",
    "regime_context": "분석 가능한 데이터가 부족해 멀티프레임 국면을 판정하지 않습니다."
  },
  "signal": null,
  "technical_signals": [],
  "risk": null,
  "charts": [],
  "interpretation": {
    "text": "분석 가능한 데이터가 부족해 국면을 판정하지 않습니다.",
    "source": "template_fallback"
  },
  "verification": {
    "calc_passed": false,
    "regime_passed": false,
    "label_matched": true,
    "outcome": "template_fallback",
    "regen_count": 0
  }
}
```

*regime이 unavailable이면 signal·risk는 null(종합·신뢰도 스킵). `charts`는 가능한 차트 데이터가 있으면 제공하고, 차트 생성에 필요한 최소 데이터도 부족하면 빈 배열로 둔다(위 예시는 후자). interpretation은 null이 아니라 템플릿 문장.*

**data_limited — A. 상위 타임프레임 일부 미확보 (D 정상):**

일봉(D)은 확보됐으나 주봉(W) 또는 월봉(M)을 확보하지 못한 경우다. **일봉 기준 분석은 계속 수행**하므로 final_regime·signal·charts가 정상적으로 나온다.

```json
{
  "data_status": "data_limited",
  "regime": {
    "final_regime": "overheated",
    "daily_regime": "overheated",
    "weekly_trend": "up",
    "monthly_trend": "unavailable",
    "alignment_flag": "neutral",
    "regime_context": "월봉 데이터가 없어 주봉 추세(상승)를 상위 기준으로 사용합니다. 상위 타임프레임 데이터가 일부 제한됩니다."
  },
  "signal": { "consensus": "weak_positive", "signal_score": 0.30, "confidence": 0.42, "...": "..." },
  "technical_signals": [ { "indicator": "rsi", "signal": "neutral", "...": "..." } ],
  "risk": { "items": [] },
  "charts": [ { "period": "1y", "...": "..." } ],
  "interpretation": { "text": "...", "source": "llm" },
  "verification": { "outcome": "passed", "...": "..." }
}
```

- `data_status=data_limited`, 미확보 상위 타임프레임은 `weekly_trend`/`monthly_trend=unavailable`
- `alignment_flag`는 확보된 상위 추세로 판정(월봉 우선, 없으면 주봉 — `regime_rules.md`). 둘 다 없으면 `neutral`. 단, `final_regime`이 과열·과매도·횡보 같은 중립 국면이면 상위 추세가 확보되어 있어도 `alignment_flag=neutral`로 둔다.
- `regime_context`에 상위 타임프레임 제한 명시
- `signal`·`technical_signals`·`risk`·`charts`는 **일봉 기준으로 정상 제공**

**data_limited — B. 일봉 데이터 미확보:**

일봉(D)도 확보하지 못하고 stale daily 캐시도 없는 경우다. 기술적 분석을 억지로 수행하지 않고 안전 착지한다(regime_unavailable과 유사한 형태).

```json
{
  "data_status": "data_limited",
  "regime": {
    "final_regime": "unavailable",
    "daily_regime": "unavailable",
    "weekly_trend": "unavailable",
    "monthly_trend": "unavailable",
    "alignment_flag": "neutral",
    "regime_context": "시세 데이터를 확보하지 못해 국면을 판정하지 않습니다."
  },
  "signal": null,
  "technical_signals": [],
  "risk": null,
  "charts": [],
  "interpretation": {
    "text": "시세 데이터를 확보하지 못해 분석을 수행하지 않습니다.",
    "source": "template_fallback"
  },
  "verification": { "calc_passed": false, "regime_passed": false, "label_matched": true, "outcome": "template_fallback", "regen_count": 0 }
}
```

- A와 B 모두 `data_status=data_limited`지만, **A는 부분 분석 가능(일봉 결과 존재), B는 분석 불가(안전 착지)**로 구분된다. 프론트는 `regime.final_regime`이 `unavailable`인지로 A/B를 구분해 렌더링한다(`frontend_mapping.md` §13.4).


**KIS 장애 폴백:**

```json
{ "data_status": "stale_cache", "source": "KIS (stale)", ... }
```

*나머지 구조 동일. `data_status`로 제한 상태만 표기.*

**템플릿 폴백 (검증 실패):**

```json
{
  "interpretation": {
    "text": "현재 국면은 과열입니다. signal_score는 …",
    "source": "template_fallback"
  },
  "verification": {
    "label_matched": false,
    "outcome": "template_fallback",
    "regen_count": 1
  }
}
```

### 5. 계약 규약

1. **필드 이름·타입 불변.** enum 값은 `enums.md`를 따른다.
2. **에이전트는 HTML을 출력하지 않는다.** JSON 데이터만 반환하고, 렌더링은 프론트 책임. (5개 에이전트 공통.)
3. **null 허용 필드:** `signal`·`risk`는 판단 불가 시 null 가능하다. **`interpretation`은 원칙적으로 항상 존재한다** — LLM 해석이 불가능하거나 검증 실패 시 null로 두지 않고 `template_fallback` 문장으로 안전 착지한다. 나머지 필드는 항상 존재. 단, `request_id`는 Agent Output 및 생성 응답에 포함되는 **런타임 필드**이며, 저장된 리포트 조회 API에서는 제외될 수 있다(DB 미저장).
4. **저장 파생값 규칙:** 재계산 가능한 파생값(`confidence_level`)은 저장 안 함. 판단 결과(`alignment_flag`·`regime_context`)는 저장.
5. **본체는 목록용 요약만.** 상세에서만 보는 것(interpretation·charts·signals·risk)은 분리 테이블 → 클릭 시 JOIN. 목록 조회를 가볍게 유지.
6. **신호 판정은 코드, 설명 문장은 LLM.** `technical_signals[]`에서 `signal`·`value`·`metrics`·`weight`는 코드가 확정하고, `detail`만 LLM이 그 확정값을 서술한다. LLM은 판정을 바꿀 수 없으며 `detail`은 검증 ③ 대상이다. 화면에서도 이 경계를 색으로 구분 표시한다(코드=청록, LLM=보라).
7. **에이전트는 DB를 모른다.** 3장 매핑은 backend가 수행하는 참고용. 에이전트는 JSON 구조만 책임진다.
8. **변경 시 소스 문서 순서:** JSON 계약(필드·구조)은 `contracts.md`를 먼저 고친다. DB 컬럼명·저장 구조 변경은 `schema.md`를 먼저 고친다(schema가 DB 이름의 최종 기준). enum 값 변경은 `enums.md`를 기준으로 삼는다. 세 경우 모두 소스 문서를 고친 뒤 나머지 문서 → 코드·backend 순으로 반영한다.
9. **1D intraday는 조건부·보조(Beta).** `charts`는 `{3m, 1y, 5y}`가 항상 존재하고 `1d`는 조건부다 — 소비 측은 `len == 3`이 아니라 **period 집합**으로 처리한다. `chart_data`는 `candle_unit` 판별 유니온(D/W/M=`ChartData`, 1d=`IntradayChartData`)이며 `OHLCV.date`(날짜 전용)는 불변, intraday는 `IntradayCandle.timestamp`를 쓴다. `intraday_context`는 optional이고, intraday는 `final_regime`·top-level `confidence`/`signal_score`/`risk`를 바꾸지 않는다(보정값은 context 내부 설명용, cap ±0.05·signal_score_adjustment는 0.0). KIS 분봉 fetcher(`fetch_minute_ohlcv`)는 구현 완료이고, **`INTRADAY_FETCH_ENABLED=True`(또는 명시 `intraday_fetcher` 주입)면 리포트 생성 1회에 D/W/M과 함께 1d를 조립**한다(기본 False면 미포함). 프론트가 1d를 따로 호출하지 않는다. intraday annotation은 Phase 3다.
