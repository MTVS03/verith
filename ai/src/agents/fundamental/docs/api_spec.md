# Fundamental Agent API Spec

`docs/api_spec.md`

재무(Fundamental) 에이전트의 내부 HTTP API와 공개 입력 계약을 정의한다. 프론트엔드는 AI 에이전트를 직접 호출하지 않고, backend 또는 Top Supervisor가 내부 API를 호출한다.

---

## 1. 문서 목적

1. Supervisor -> Fundamental 내부 API 계약을 고정한다.
2. 공개 입력(`ticker + query`)과 내부 파라미터(`intent`, `years`, `report_mode`, `fs_div`)의 경계를 분리한다.
3. 지원 밖 종목, corp_code 폴백, timeout, 내부 오류의 HTTP 응답 기준을 명확히 한다.
4. `FundamentalRequest`/`FundamentalResponse` 기존 내부 계약을 하위 호환으로 유지한다.

---

## 2. 전체 호출 흐름

```text
사용자 질문
  -> Top Supervisor
  -> 필요 시 backend stock_resolver로 ticker 확보
  -> POST /internal/fundamental/analyze
  -> Fundamental 내부 query 해석
  -> backend stock_corp_codes 정본으로 corp_code 조회
  -> DART 재무 분석
  -> FundamentalResponse
```

Supervisor는 `corp_code`를 만들지 않는다. Fundamental은 `ticker`로 `corp_code`를 조회한다.

---

## 3. 내부 API

### 3.1 Health Check

```http
GET /internal/fundamental/health
```

Response:

```json
{
  "status": "ok",
  "service": "fundamental-agent",
  "version": "0.1.0"
}
```

### 3.2 분석 실행

```http
POST /internal/fundamental/analyze
```

내부망 또는 내부 토큰으로만 호출한다. 프론트엔드는 직접 호출하지 않는다.

Request Body:

```json
{
  "request_id": "req_abc123",
  "trace_id": "trace_fundamental_001",
  "ticker": "005930",
  "query": "최근 3년 매출 성장률 알려줘"
}
```

| 필드 | 타입 | 필수 | 검증 | 설명 |
| --- | --- | --- | --- | --- |
| `request_id` | string | YES | blank 금지 | 사용자 요청 또는 Supervisor 실행 추적 ID |
| `trace_id` | string | YES | blank 금지 | Fundamental 실행 trace ID |
| `ticker` | string | YES | 6자리 숫자 | backend stock_resolver가 확정한 종목코드 |
| `query` | string | YES | blank 금지 | 사용자 자연어 질문 또는 Supervisor가 에이전트별로 성형한 자연어 지시 |

`extra="forbid"`이므로 `intent`, `years`, `report_mode`, `fs_div`, `corp_code` 같은 내부 필드를 요청에 넣으면 422 `VALIDATION_ERROR`다.

Response Body는 `FundamentalResponse`다. 아래는 구조를 보여주는 축약 예시다.

```json
{
  "agent": "fundamental",
  "request_id": "req_abc123",
  "ticker": "005930",
  "corp_name": "삼성전자",
  "verdict": "계산 가능한 재무 데이터 기준 설명 문장",
  "verdict_label": "moderate",
  "confidence": 0.72,
  "score": 68,
  "score_breakdown": {
    "score_type": "absolute_financial_health"
  },
  "analyst_plan": {},
  "evidence_graph": {},
  "retrieval_context": {},
  "ratios": {},
  "trend": {},
  "insights": {},
  "interpretation": "해석 문장",
  "evidence": [],
  "risk_flags": [],
  "report_html": "<section>...</section>",
  "meta": {
    "trace_id": "trace_fundamental_001",
    "corp_code": "00126380",
    "input_interpretation": {
      "intent": "growth",
      "fs_div": "CFS",
      "report_mode": "annual",
      "years": 3,
      "applied_rules": [
        "years:n_years",
        "intent:growth"
      ],
      "defaulted_fields": [
        "report_mode",
        "fs_div"
      ]
    },
    "corp_code_resolution": {
      "stock_code": "005930",
      "corp_code": "00126380",
      "corp_name": "삼성전자",
      "source": "backend_stock_corp_codes",
      "risk_flags": []
    }
  }
}
```

---

## 4. 지원 밖 종목 응답 원칙

지원하지 않는 종목코드는 HTTP 에러가 아니다. `corp_code`를 backend 정본과 static fallback에서 모두 찾지 못하면, API는 정상 HTTP 200으로 `FundamentalResponse`를 반환한다.

```json
{
  "agent": "fundamental",
  "request_id": "req_unsupported",
  "ticker": "000000",
  "corp_name": "000000",
  "verdict_label": "insufficient_data",
  "confidence": 0.3,
  "score": 0,
  "risk_flags": [
    "UNSUPPORTED_TICKER"
  ],
  "meta": {
    "workflow": [
      "collect",
      "report"
    ],
    "corp_code": ""
  }
}
```

Supervisor는 이 응답을 실패로 취급하지 말고, Fundamental 카드의 `insufficient_data` 상태로 렌더링해야 한다.

---

## 5. 공개 입력 -> 내부 파라미터 해석 규칙 v2

query 해석은 결정론 규칙만 사용한다. LLM 호출, 임의 추론, regex 외 자연어 생성은 금지한다.

| 조건 | 결정 | applied_rules |
| --- | --- | --- |
| `N년` 또는 `N개년` | `years=N`, 1~6 clamp | `years:n_years` |
| `분기`, `이번 분기`, `분기보고서` | `report_mode="latest"` | `report_mode:quarterly_keyword` |
| 분기 계열 명시어 없는 bare `최근`·`최신` | 기본 `report_mode="annual"` 유지 | 규칙 없음, `defaulted_fields`에 `report_mode` 기록 |
| `별도`만 있음 | `fs_div="OFS"` | `fs_div:standalone` |
| `연결`만 있음 | `fs_div="CFS"` | `fs_div:consolidated` |
| 정확히 1개 축: `수익성`, `마진`, `ROE`, `이익률` | `intent="profitability"` | `intent:profitability` |
| 정확히 1개 축: `부채`, `안정성`, `유동`, `건전성`, `레버리지`, `차입` | `intent="stability"` | `intent:stability` |
| 정확히 1개 축: `성장`, `매출 증가` | `intent="growth"` | `intent:growth` |
| 정확히 1개 축: `밸류`, `PER`, `PBR`, `저평가`, `고평가` | `intent="valuation"` | `intent:valuation` |
| 서로 다른 intent 축이 2개 이상 매칭 | `intent="fundamental_health"` | `intent:multi_axis_comprehensive` |
| intent 축 매칭 없음 | 기본 `intent="fundamental_health"` 유지 | 규칙 없음, `defaulted_fields`에 `intent` 기록 |

기본값은 `report_mode="annual"`, `years=4`, `fs_div="CFS"`, `intent="fundamental_health"`다.
한 축의 키워드가 여러 번 매칭돼도 한 축으로 센다.

### 5.1 Supervisor 성형 프로즈 내성 (v2, 2026-07-10)

| 실측 Supervisor 입력 | v1 드리프트 | v2 해석 |
| --- | --- | --- |
| `삼성전자의 최근 실적, 수익성, 안정성, 밸류에이션 관점에서 재무 상태를 분석해줘.` | 첫 축이 승리해 `profitability`, bare `최근` 때문에 `latest` | 다축 종합 `fundamental_health`, 기본 `annual` |
| `배터리 화재 이슈가 실적·수익성·안정성·성장성·밸류에이션에 줄 영향 중심으로…` | 첫 축이 승리해 `profitability` | 다축 종합 `fundamental_health`, 기본 `annual` |
| `재무 건전성 전반을 점검` / `레버리지 상황을 점검` | 동의어 미매칭으로 기본 intent에 전락 | 단일 축 `stability` |
| `최신 재무 상태로 안정성 점검` | bare `최신` 때문에 `latest` | 단일 축 `stability`, 기본 `annual` |

v2는 공개 계약 필드와 기본값을 바꾸지 않고 결정론 해석 규칙만 강화한다. query 해석 과정에 LLM 호출은 없다.

---

## 6. corp_code 해석

우선순위:

1. backend 정본 `stock_corp_codes` 직접 조회
2. 실패, 미설정, row 없음이면 static `CORP_CODE_MAP` 폴백

환경변수:

| 변수 | 설명 |
| --- | --- |
| `VERITH_DB_URL` | AI가 backend PostgreSQL 정본을 조회할 때 사용하는 DSN |
| `DATABASE_URL` | `VERITH_DB_URL` 미설정 시 호환 alias로 사용 |
| `CORP_CODE_DB_TIMEOUT_SECONDS` | DB 연결 및 statement timeout |
| `CORP_CODE_DB_RETRIES` | DB 조회 재시도 횟수 |

`postgresql+asyncpg://`와 `postgres+asyncpg://` 접두사는 psycopg 조회를 위해 각각 `postgresql://`, `postgres://`로 정규화한다.

static 폴백을 사용하면 `CORP_CODE_FALLBACK_STATIC`을 `risk_flags`와 `meta.corp_code_resolution.risk_flags`에 기록한다.

---

## 7. Error Envelope

`src/api/errors.py`의 공통 envelope를 사용한다.

```json
{
  "error": {
    "code": "AI_TIMEOUT",
    "message": "AI processing timed out.",
    "request_id": "req_abc123",
    "trace_id": null
  }
}
```

| 상황 | HTTP | code | 매핑 |
| --- | --- | --- | --- |
| JSON 파싱 실패 | 400 | `INVALID_REQUEST` | FastAPI validation handler |
| 필수값 누락/형식 오류/extra 필드 | 422 | `VALIDATION_ERROR` | FastAPI validation handler |
| 전체 처리 60초 초과 | 504 | `AI_TIMEOUT` | `ai_timeout(request_id)` |
| 예상 못한 내부 오류 | 500 | `INTERNAL_ERROR` | `internal_error(request_id)` |

지원 밖 종목은 이 표의 에러가 아니라 200 `FundamentalResponse(verdict_label="insufficient_data")`다.

---

## 8. Timeout / Retry 정책

| 항목 | 값 |
| --- | --- |
| endpoint timeout | 60초 |
| backend corp_code 조회 timeout | `CORP_CODE_DB_TIMEOUT_SECONDS` |
| backend corp_code 조회 retry | `CORP_CODE_DB_RETRIES` |

DART/LLM 세부 호출의 재시도와 fallback은 Fundamental 내부 노드 정책을 따른다.

---

## 9. 저장 경계

AI Fundamental Agent는 PostgreSQL에 분석 결과를 직접 저장하지 않는다. backend가 AI 응답을 검증하고 저장한다. 이 문서의 `corp_code` DB 접근은 DART 식별자 정본을 읽기 위한 조회 전용 경계다.

---

## 10. 관련 문서

| 문서 | 역할 |
| --- | --- |
| `README/03_DATA_CONTRACT.md` | 공개 입력 계약, 응답 JSON, 저장 미리보기 |
| `backend/docs/fundamental_corp_code_handoff.md` | backend `stock_corp_codes` 정본 소비 handoff |
| `backend/docs/dart_corp_code_sync.md` | DART corp_code 동기화 정본 |
| `backend/docs/supervisor_backend_integration.md` | Supervisor와 backend 정본 연결 방향 |
