# 12. 데이터베이스 스키마 (Schema)

`docs/schema.md`

가격/기술적 분석 에이전트의 **논리 스키마(output 계약)와 Redis 캐시 구조**를 정의한다. 컬럼의 의미·enum·nullable 규칙·검증 정책의 설계 근거를 담는다.

> **⚠️ 물리 스키마 정본 = backend 통합 schema.** PostgreSQL 실제 테이블명·제약(FK/CASCADE/UNIQUE/NOT NULL)·마이그레이션의 **정본은 `backend/db/models/*` + `backend/db/migrations/*`**(통합 ERD)다. 이 문서와 물리 테이블명이 다르면 **backend 물리 스키마를 따른다.** 이 문서는 논리 설계·output 계약·nullable 근거를 설명한다.
>
> **논리명 → 물리 테이블명 매핑** (backend 통합 schema):
>
> | 이 문서(논리명) | backend 물리 테이블 |
> | --- | --- |
> | `technical_reports` | `technical_reports` |
> | `report_signals` | `technical_report_signals` |
> | `report_charts` | `technical_report_charts` |
> | `report_risk_notes` | `technical_report_risk_notes` |
> | `report_interpretation` | `technical_report_interpretations` |
> | `report_verification` | `technical_report_verifications` |
> | (신규) 후속 질의 | `technical_report_followups` |
>
> 물리 스키마는 이 문서의 무결성 규칙을 흡수한다: 자식 FK **ON DELETE CASCADE**, `report_id` **UNIQUE**(1:1), `report_signals` **UNIQUE(report_id, indicator)**, degraded에도 sentinel로 채워지는 `final_regime`·`daily_regime`·`alignment_flag`는 **NOT NULL**. 단 `consensus`·`signal_score`·`confidence`·`weekly_trend`·`monthly_trend`는 degraded에서 NULL 가능하므로 nullable(§9). 통합 ERD 신규 컬럼(`timeframe`, `chart_payload` 등)은 보장 근거 확정 전까지 nullable.

---

## 1. 문서 목적

1. PostgreSQL에 영구 저장할 테이블·컬럼을 정의한다.
2. 각 컬럼의 타입·nullable·FK·index 기준을 명시한다.
3. `contracts.md`의 출력 JSON이 DB에 어떻게 저장되는지 매핑한다(§12).
4. Redis 캐시 키 구조와 TTL을 정의한다(§11).
5. 기존 ERD 초안과 최신 설계의 차이를 정리한다(§3).

> **AI 에이전트는 DB에 직접 쓰지 않는다.** 에이전트는 JSON만 반환하고, 백엔드가 이 JSON을 PostgreSQL에 저장한다.

---

## 2. 저장 책임 경계

| 영역 | 책임 |
| --- | --- |
| AI 에이전트 | 기술적 분석 JSON 생성 |
| Backend | JSON 수신·검증·PostgreSQL 저장·조회 API 제공 |
| PostgreSQL | 완성된 기술 분석 리포트 영구 저장 |
| Redis | OHLCV 원천 데이터 캐시 |
| Frontend | 저장된 JSON/조회 API 기반 화면 렌더링 |

에이전트는 HTML을 저장하거나 반환하지 않는다. 화면 구성은 Frontend가 구조화 데이터를 기반으로 수행한다.

---

## 3. 기존 ERD 기준과 최신 스키마 방향

기존 ERD의 6테이블 구조(`technical_reports`·`report_signals`·`report_charts`·`report_risk_notes`·`report_interpretation`·`report_verification`)는 **유지**한다. 다만 최신 `contracts.md`·`test_plan.md`·`regime_rules.md`와 맞추기 위해 컬럼명과 일부 컬럼을 수정한다.

| 기존 ERD/매핑 | 최신 schema.md | 이유 |
| --- | --- | --- |
| `market_regime` | `final_regime` | JSON 필드명과 DB 컬럼명 통일. "시장 전체"가 아니라 종목의 기술적 최종 국면 |
| `strategy` | `indicator` | 전략이 아니라 지표별 기술 신호 |
| `kind` | `flag` | `risk.items[].flag`와 DB 컬럼명 통일 |
| 없음 | `alignment_flag` | 멀티프레임 정합/역행/중립 저장 |
| 없음 | `regime_context` | 상위 추세 맥락 설명 저장 |
| 없음 | `metrics` | 지표별 세부 계산값 저장 |
| 없음 | `detail_source` | 지표별 설명 출처 추적 (검증 ③ 연결) |

**설계 원칙:** JSON 필드명과 DB 컬럼명을 최대한 일치시켜 백엔드 매핑에서 "번역"을 없앤다. `indicator`가 이미 그렇고, 이번에 `final_regime`·`flag`도 통일한다.

---

## 4. PostgreSQL ERD 요약

- `technical_reports`: 리포트 대표 정보와 최종 국면·신호 요약
- `report_signals`: 지표별 기술 신호와 지표 설명
- `report_charts`: 차트 렌더링용 데이터
- `report_risk_notes`: 리스크 관찰 포인트
- `report_interpretation`: 종합 해석 문장 (1:1)
- `report_verification`: 검증 결과 요약 (1:1)

```
technical_reports 1 ─ N report_signals
technical_reports 1 ─ N report_charts
technical_reports 1 ─ N report_risk_notes
technical_reports 1 ─ 1 report_interpretation
technical_reports 1 ─ 1 report_verification
```

---

## 5. 테이블 정의

### 5.1 technical_reports

기술적 분석 리포트의 대표 테이블. 한 번의 분석 요청 결과를 1행으로 저장한다.

| 컬럼 | 타입 | Nullable | 설명 |
| --- | --- | --- | --- |
| id | UUID | NO | PK |
| request_id | VARCHAR | NO | 요청 추적 ID(생성=Chat/Supervisor·직접 호출 시 backend). UNIQUE. 정본 api_spec §4 |
| ticker | VARCHAR(20) | NO | 종목 코드 |
| final_regime | VARCHAR(50) | NO | 최종 기술 국면 |
| daily_regime | VARCHAR(50) | NO | 일봉 기준 국면 |
| weekly_trend | VARCHAR(50) | YES | 주봉 추세 |
| monthly_trend | VARCHAR(50) | YES | 월봉 추세 |
| alignment_flag | VARCHAR(50) | NO | aligned/counter_trend/neutral |
| regime_context | TEXT | YES | 멀티프레임 맥락 설명 |
| consensus | VARCHAR(50) | YES | 종합 신호 방향 |
| signal_score | DOUBLE PRECISION | YES | 가중 종합 신호 점수 |
| confidence | DOUBLE PRECISION | YES | 신뢰도 점수 |
| confidence_basis | TEXT | YES | 신뢰도 산출 근거 |
| data_status | VARCHAR(50) | NO | normal/stale_cache/data_limited/regime_unavailable |
| trace_id | VARCHAR(100) | NO | 추적 ID |
| source | VARCHAR(50) | NO | 시세 제공자 기준 (KIS / KIS (stale)). data_limited B처럼 실제 시세를 확보하지 못한 경우에도 요청·폴백 기준 제공자가 KIS이면 KIS로 둔다 |
| as_of | TIMESTAMPTZ | NO | 분석 기준 시각 |
| created_at | TIMESTAMPTZ | NO | 저장 시각 |

`confidence_level`은 저장하지 않는다 — `confidence` float에서 재계산 가능한 파생값이며, 경계값이 바뀌면 저장값이 꼬인다.

### 5.2 report_signals

지표별 기술 신호를 저장한다. 하나의 정상 리포트는 기본 5개 지표 신호를 가진다. 단, 데이터 부족으로 일부 지표가 계산 불가능한 경우에는 계산 가능한 지표만 저장하고, 제외 사실은 confidence_basis 또는 trace에 남긴다.

| 컬럼 | 타입 | Nullable | 설명 |
| --- | --- | --- | --- |
| id | UUID | NO | PK |
| report_id | UUID | NO | technical_reports.id FK |
| indicator | VARCHAR(50) | NO | moving_average/rsi/volume/support_resistance/pattern |
| signal | VARCHAR(20) | NO | positive/neutral/negative |
| value | DOUBLE PRECISION | YES | 대표 수치 |
| metrics | JSONB | YES | 지표별 세부 계산값 (화면 표시용 칩) |
| detail | TEXT | YES | 지표별 설명 문장 (LLM 서술) |
| detail_source | VARCHAR(50) | YES | llm/llm_regenerated/template_fallback |
| weight | DOUBLE PRECISION | NO | 신호 종합 가중치 |

**지표별 detail 검증 결과는 별도 테이블을 만들지 않고 `detail_source`로 추적한다.** detail은 지표마다 출처가 다를 수 있으므로(하나는 llm, 하나는 template_fallback) 지표 테이블에 두는 것이 자연스럽다.

### 5.3 report_charts

프론트엔드 차트 렌더링에 필요한 데이터를 저장한다.

| 컬럼 | 타입 | Nullable | 설명 |
| --- | --- | --- | --- |
| id | UUID | NO | PK |
| report_id | UUID | NO | technical_reports.id FK |
| period | VARCHAR(20) | NO | 3m/1y/5y |
| chart_data | JSONB | NO | 차트 렌더링용 candles·overlays·subcharts·annotations 데이터 (`chart_annotation_spec.md`) |

### 5.4 report_risk_notes

리스크 관찰 포인트를 저장한다. 투자 행동 지시가 아니라 관찰용 문장만 저장한다.

| 컬럼 | 타입 | Nullable | 설명 |
| --- | --- | --- | --- |
| id | UUID | NO | PK |
| report_id | UUID | NO | technical_reports.id FK |
| flag | VARCHAR(50) | NO | risk flag 코드 |
| note | TEXT | NO | 관찰 포인트 설명 |
| ref_price | DOUBLE PRECISION | YES | 참고 가격 |

### 5.5 report_interpretation

종합 해석 문장을 저장한다. 리포트당 1개만 생성된다.

| 컬럼 | 타입 | Nullable | 설명 |
| --- | --- | --- | --- |
| id | UUID | NO | PK |
| report_id | UUID | NO | technical_reports.id FK, **UNIQUE** |
| interpretation | TEXT | NO | 종합 해석 문장 |
| interpretation_source | VARCHAR(50) | NO | llm/llm_regenerated/template_fallback |

### 5.6 report_verification

계산 검증·regime 규칙 검증·LLM 라벨 왜곡 검증 결과를 리포트 단위로 저장한다.

| 컬럼 | 타입 | Nullable | 설명 |
| --- | --- | --- | --- |
| id | UUID | NO | PK |
| report_id | UUID | NO | technical_reports.id FK, **UNIQUE** |
| calc_passed | BOOLEAN | NO | 검증 ① 통과 여부 |
| regime_passed | BOOLEAN | NO | 검증 ② 통과 여부 |
| label_matched | BOOLEAN | NO | 검증 ③ 통과 여부 (리포트 단위 요약) |
| outcome | VARCHAR(50) | NO | passed/regenerated/template_fallback/failed |
| regen_count | INTEGER | NO | LLM 재생성 횟수 |

`label_matched`는 종합 해석(`interpretation`)과 지표별 detail 검증을 **모두** 통과했는지에 대한 리포트 단위 요약값이다. 지표별 detail의 최종 출처는 `report_signals.detail_source`로 확인한다.

---

## 6. FK / 관계 규칙

| 자식 테이블 | FK | 부모 | 삭제 정책 |
| --- | --- | --- | --- |
| report_signals | report_id | technical_reports.id | ON DELETE CASCADE |
| report_charts | report_id | technical_reports.id | ON DELETE CASCADE |
| report_risk_notes | report_id | technical_reports.id | ON DELETE CASCADE |
| report_interpretation | report_id | technical_reports.id | ON DELETE CASCADE |
| report_verification | report_id | technical_reports.id | ON DELETE CASCADE |

리포트 삭제 시 자식 레코드가 함께 삭제되어 고아 레코드가 남지 않는다.

---

## 7. Index 설계

| 테이블 | 인덱스 | 목적 |
| --- | --- | --- |
| technical_reports | idx_technical_reports_ticker_created_at (ticker, created_at DESC) | 종목별 최신 리포트 조회 |
| technical_reports | idx_technical_reports_trace_id | trace_id 기반 디버깅 |
| technical_reports | idx_technical_reports_data_status | 상태별 조회 |
| report_signals | idx_report_signals_report_id | 리포트별 지표 조회 |
| report_signals | ux_report_signals_report_indicator (report_id, indicator) UNIQUE | 리포트 내 지표 중복 방지 |
| report_charts | idx_report_charts_report_id_period (report_id, period) | 리포트별 기간 차트 조회 |
| report_risk_notes | idx_report_risk_notes_report_id | 리포트별 리스크 조회 |
| report_interpretation | ux_report_interpretation_report_id UNIQUE | 리포트당 해석 1개 보장 |
| report_verification | ux_report_verification_report_id UNIQUE | 리포트당 검증 결과 1개 보장 |

`report_signals`의 (report_id, indicator) UNIQUE는 같은 지표가 한 리포트에 중복 저장되는 것을 막는다 — `prompts.md`의 details 병합 안전장치(지표당 1개)를 DB 레벨에서 한 번 더 보장한다.

---

## 8. Enum 저장 규칙

DB에는 사용자 표시용 한글 라벨을 저장하지 않는다. 모든 enum성 필드는 `enums.md`의 영문 snake_case 코드값을 저장한다.

| 필드 | 허용값 |
| --- | --- |
| final_regime / daily_regime | overheated, oversold_rebound_watch, bullish_reversal_watch, uptrend_intact, downtrend, sideways, unavailable |
| weekly_trend / monthly_trend | up, down, sideways, unavailable |
| alignment_flag | aligned, counter_trend, neutral |
| consensus | strong_positive, weak_positive, neutral, weak_negative, strong_negative |
| signal (report_signals) | positive, neutral, negative |
| data_status | normal, stale_cache, data_limited, regime_unavailable |
| source | KIS, KIS (stale) |
| interpretation_source / detail_source | llm, llm_regenerated, template_fallback |
| period | 3m, 1y, 5y |
| outcome | passed, regenerated, template_fallback, failed |

MVP는 애플리케이션 레벨에서 검증하고 VARCHAR로 저장한다. 값 집합이 안정되면 PostgreSQL ENUM 타입 또는 CHECK 제약으로 강화할 수 있다(Future Work).

---

## 9. Nullable 규칙

정상 리포트와 판단 불가 리포트의 nullable 기준을 분리한다.

### 9.1 정상 리포트

`final_regime`·`daily_regime`·`alignment_flag`·`consensus`·`signal_score`·`confidence`는 NOT NULL. `report_signals` 5개, `report_interpretation` 1개, `report_verification` 1개 생성. `report_risk_notes`는 0개 이상.

### 9.2 regime_unavailable (판단 불가)

- `final_regime = unavailable`, `daily_regime = unavailable`
- `data_status = regime_unavailable`
- `alignment_flag = neutral`
- `consensus = NULL`, `signal_score = NULL`, `confidence = NULL`
- `report_signals`: 생성하지 않음
- `report_risk_notes`: 생성하지 않음
- `report_charts`: 가능한 경우 생성
- `report_interpretation`: template_fallback 문장으로 생성 (null로 두지 않고 안전 착지)
- `report_verification`: 생성

`contracts.md`의 판단 불가 출력과 일치한다 — 억지 판정을 하지 않고 정직하게 빠진다.

### 9.3 data_limited

data_limited는 두 케이스로 나뉜다(`contracts.md` §4).

**A. 상위 타임프레임 일부 미확보 (D 정상):** 일봉 기준 분석 결과가 **존재**한다.
- `data_status = data_limited`
- `final_regime`·`daily_regime`·`consensus`·`signal_score`·`confidence`: 정상 리포트처럼 NOT NULL (일봉 기준 산출)
- 미확보 상위 타임프레임의 `weekly_trend` 또는 `monthly_trend = unavailable`
- `alignment_flag`: 확보된 상위 추세로 판정(월봉 우선, 없으면 주봉), 둘 다 없으면 `neutral`. 단 `final_regime`이 중립 국면(과열·과매도·횡보)이면 상위 추세가 있어도 `neutral`
- `report_signals`·`report_charts`·`report_interpretation`·`report_verification`: 정상 생성

**B. 일봉 미확보 (D도 없음):** 안전 착지, regime_unavailable과 동일 형태.
- `data_status = data_limited`
- `final_regime = unavailable`, `daily_regime = unavailable`, `weekly_trend = unavailable`, `monthly_trend = unavailable`
- `alignment_flag = neutral`
- `consensus = NULL`, `signal_score = NULL`, `confidence = NULL`
- `report_signals`·`report_risk_notes`: 생성하지 않음
- `report_charts`: 가능한 경우 생성
- `report_interpretation`: template_fallback 문장으로 생성
- `report_verification`: 생성

A와 B는 `final_regime`이 `unavailable`인지로 구분한다.

---

## 10. PostgreSQL DDL

Alembic 마이그레이션 작성 전 기준 DDL이다.

```sql
-- 1. 본체
CREATE TABLE technical_reports (
    id                UUID PRIMARY KEY,
    ticker            VARCHAR(20)  NOT NULL,
    final_regime      VARCHAR(50)  NOT NULL,
    daily_regime      VARCHAR(50)  NOT NULL,
    weekly_trend      VARCHAR(50),
    monthly_trend     VARCHAR(50),
    alignment_flag    VARCHAR(50)  NOT NULL,
    regime_context    TEXT,
    consensus         VARCHAR(50),
    signal_score      DOUBLE PRECISION,
    confidence        DOUBLE PRECISION,
    confidence_basis  TEXT,
    data_status       VARCHAR(50)  NOT NULL,
    trace_id          VARCHAR(100) NOT NULL,
    source            VARCHAR(50)  NOT NULL,
    as_of             TIMESTAMPTZ  NOT NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_technical_reports_ticker_created_at
    ON technical_reports (ticker, created_at DESC);
CREATE INDEX idx_technical_reports_trace_id
    ON technical_reports (trace_id);
CREATE INDEX idx_technical_reports_data_status
    ON technical_reports (data_status);

-- 2. 지표 신호 (1:N)
CREATE TABLE report_signals (
    id             UUID PRIMARY KEY,
    report_id      UUID NOT NULL REFERENCES technical_reports(id) ON DELETE CASCADE,
    indicator      VARCHAR(50) NOT NULL,
    signal         VARCHAR(20) NOT NULL,
    value          DOUBLE PRECISION,
    metrics        JSONB,
    detail         TEXT,
    detail_source  VARCHAR(50),
    weight         DOUBLE PRECISION NOT NULL
);

CREATE INDEX idx_report_signals_report_id
    ON report_signals (report_id);
CREATE UNIQUE INDEX ux_report_signals_report_indicator
    ON report_signals (report_id, indicator);

-- 3. 차트 (1:N)
CREATE TABLE report_charts (
    id          UUID PRIMARY KEY,
    report_id   UUID NOT NULL REFERENCES technical_reports(id) ON DELETE CASCADE,
    period      VARCHAR(20) NOT NULL,
    chart_data  JSONB NOT NULL
);

CREATE INDEX idx_report_charts_report_id_period
    ON report_charts (report_id, period);

-- 4. 리스크 관찰점 (1:N)
CREATE TABLE report_risk_notes (
    id          UUID PRIMARY KEY,
    report_id   UUID NOT NULL REFERENCES technical_reports(id) ON DELETE CASCADE,
    flag        VARCHAR(50) NOT NULL,
    note        TEXT NOT NULL,
    ref_price   DOUBLE PRECISION
);

CREATE INDEX idx_report_risk_notes_report_id
    ON report_risk_notes (report_id);

-- 5. 종합 해석 (1:1)
CREATE TABLE report_interpretation (
    id                     UUID PRIMARY KEY,
    report_id              UUID NOT NULL REFERENCES technical_reports(id) ON DELETE CASCADE,
    interpretation         TEXT NOT NULL,
    interpretation_source  VARCHAR(50) NOT NULL
);

CREATE UNIQUE INDEX ux_report_interpretation_report_id
    ON report_interpretation (report_id);

-- 6. 검증 결과 (1:1)
CREATE TABLE report_verification (
    id             UUID PRIMARY KEY,
    report_id      UUID NOT NULL REFERENCES technical_reports(id) ON DELETE CASCADE,
    calc_passed    BOOLEAN NOT NULL,
    regime_passed  BOOLEAN NOT NULL,
    label_matched  BOOLEAN NOT NULL,
    outcome        VARCHAR(50) NOT NULL,
    regen_count    INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX ux_report_verification_report_id
    ON report_verification (report_id);
```

---

## 11. Redis 캐시 키 구조

| 키 패턴 | 값 타입 | TTL | 내용 | 비고 |
| --- | --- | --- | --- | --- |
| `ohlcv:daily:{ticker}` | JSON 봉 배열 | 없음(장기) | 과거 일봉 전체 (KIS D) | 거의 안 바뀌므로 장기 보관, 오늘 봉만 갱신 |
| `ohlcv:weekly:{ticker}` | JSON 봉 배열 | 없음(장기) | 주봉 (KIS W) | KIS 원본 |
| `ohlcv:monthly:{ticker}` | JSON 봉 배열 | 없음(장기) | 월봉 (KIS M) | KIS 원본 |
| `ohlcv:today:{ticker}` | JSON 봉 1개 | 15분 | 오늘 일봉 | 장중 자주 바뀌어 짧은 TTL |
| `ohlcv:minute:{ticker}` | JSON 분봉 배열 | 1분 | 분봉 | 1d Beta/Future Work용, MVP 필수 아님 |

**일봉·주봉·월봉은 모두 KIS `inquire-daily-itemchartprice`를 `FID_PERIOD_DIV_CODE`만 다르게(D/W/M) 호출한 원본을 캐시한다.** 리샘플로 파생하지 않는다 — 세 타임프레임 전부 KIS 실제 시세를 정본으로 쓰므로, 상위 추세·차트가 검증 가능한 실제 데이터에 근거한다(`kis_mapping.md` §3·§9).

---

## 12. contracts.md → DB 저장 매핑

| contracts.md 필드 | 저장 테이블 | 저장 컬럼 |
| --- | --- | --- |
| request_id | technical_reports | request_id |
| ticker | technical_reports | ticker |
| source | technical_reports | source |
| trace_id | technical_reports | trace_id |
| data_status | technical_reports | data_status |
| as_of | technical_reports | as_of |
| regime.final_regime | technical_reports | final_regime |
| regime.daily_regime | technical_reports | daily_regime |
| regime.weekly_trend | technical_reports | weekly_trend |
| regime.monthly_trend | technical_reports | monthly_trend |
| regime.alignment_flag | technical_reports | alignment_flag |
| regime.regime_context | technical_reports | regime_context |
| signal.consensus | technical_reports | consensus |
| signal.signal_score | technical_reports | signal_score |
| signal.confidence | technical_reports | confidence |
| signal.confidence_basis | technical_reports | confidence_basis |
| technical_signals[].indicator | report_signals | indicator |
| technical_signals[].signal | report_signals | signal |
| technical_signals[].value | report_signals | value |
| technical_signals[].metrics | report_signals | metrics |
| technical_signals[].detail | report_signals | detail |
| technical_signals[].detail_source | report_signals | detail_source |
| technical_signals[].weight | report_signals | weight |
| risk.items[].flag | report_risk_notes | flag |
| risk.items[].note | report_risk_notes | note |
| risk.items[].ref_price | report_risk_notes | ref_price |
| charts[].period | report_charts | period |
| charts[].chart_data | report_charts | chart_data |
| interpretation.text | report_interpretation | interpretation |
| interpretation.source | report_interpretation | interpretation_source |
| verification.calc_passed | report_verification | calc_passed |
| verification.regime_passed | report_verification | regime_passed |
| verification.label_matched | report_verification | label_matched |
| verification.outcome | report_verification | outcome |
| verification.regen_count | report_verification | regen_count |

`signal.confidence_level`은 DB 저장 대상이 아니다 — `confidence` 숫자값에서 프론트/백엔드가 파생한다.

`request_id`는 Agent Output 필드이자 backend 통합 물리 스키마에 **저장된다** — `technical_reports.request_id`(UNIQUE NOT NULL, 요청 추적·중복 식별 키)이며 위 §12 매핑표에도 포함된다. 물리 정본은 backend schema이고 식별자 소유권 정본은 api_spec §4다. 반면 `report_id`는 Agent Output 필드가 아니라 backend가 부여하는 저장 ID(= `technical_reports.id`)이므로 이 매핑표에는 없다(이전 request_id '미저장' 규정은 통합 스키마 확정으로 폐기).

---

## 13. contracts.md와의 컬럼명 정합성

schema.md가 DB 기준 문서이므로, `contracts.md`의 기존 DB 매핑 표를 여기 맞춰 갱신한다. (이 문서 작성과 함께 반영 완료.)

| 기존 매핑 | 수정 매핑 |
| --- | --- |
| `regime.final_regime → technical_reports.market_regime` | `regime.final_regime → technical_reports.final_regime` |
| `risk.items[].flag → report_risk_notes.kind` | `risk.items[].flag → report_risk_notes.flag` |

이후 컬럼명 변경이 생기면 이 문서를 먼저 고치고 contracts를 맞춘다(schema → contracts 순).

---

## 관련 문서

| 문서 | 담당 |
| --- | --- |
| `contracts.md` | 출력 JSON 구조 (이 문서가 그 저장 대상) |
| `enums.md` | 컬럼 허용값(코드값) 기준 |
| `test_plan.md` | 계약 테스트(CONTRACT-*)·enum 검증 |
| `architecture.md` | 저장 구조의 전체 위치 (B층 저장) |
