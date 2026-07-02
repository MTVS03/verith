# 15. API 명세 (API Spec)

`docs/api_spec.md`

가격/기술적 분석 리포트 생성·조회에 필요한 HTTP API를 정의한다. `contracts.md`의 JSON 계약을 실제 API에서 어떻게 주고받을지 정리한다.

> 프론트엔드는 AI 에이전트를 직접 호출하지 않고, 항상 백엔드를 통해 리포트를 요청한다(`frontend → backend → ai`).

---

## 1. 문서 목적

1. 프론트엔드 ↔ 백엔드 API를 정의한다.
2. 백엔드 ↔ AI 에이전트 내부 API를 정의한다.
3. `request_id`·`trace_id`·`report_id`의 생성 주체와 전달 범위를 명확히 한다.
4. 분석 성공·판단 불가·폴백·실패 상황의 응답 기준을 정의한다.
5. API 응답이 `contracts.md`·`schema.md`·`frontend_mapping.md`와 어긋나지 않게 한다.

---

## 2. 전체 호출 흐름

```
Frontend → Backend API → AI Technical Agent → Backend DB 저장 → Frontend 렌더링
```

| 구간 | 역할 |
| --- | --- |
| Frontend → Backend | 리포트 생성 요청, 저장된 리포트 조회 |
| Backend → AI Agent | 가격/기술적 분석 실행 요청 (내부 API) |
| Backend → DB | 최종 리포트 저장 (PostgreSQL) |
| Frontend | `frontend_mapping.md` 기준 화면 렌더링 |

프론트엔드는 AI 서버를 직접 호출하지 않는다.

---

## 3. 처리 방식

**MVP는 동기 처리를 기본으로 한다.**

```
POST /api/technical/reports
→ 백엔드가 AI 에이전트 호출 → 결과 저장 → report_id와 리포트 JSON 반환
```

분석 시간이 길어지거나 동시 요청이 늘면 Future Work에서 비동기 Job 방식으로 확장한다.

### Future Work

```text
POST /api/technical/report-jobs
GET  /api/technical/report-jobs/{job_id}
GET  /api/technical/reports/{report_id}
```

---

## 4. 식별자 규칙

| 식별자 | 생성 주체 | 저장 여부 | 설명 |
| --- | --- | --- | --- |
| `request_id` | Backend 또는 Top Supervisor | DB 미저장 | 런타임 요청 추적 ID. contracts JSON 안에 포함, 저장·조회 대상 아님 |
| `trace_id` | AI Technical Supervisor | DB 저장 | AI 실행 추적 ID. `technical_reports.trace_id`에 저장 |
| `report_id` | Backend | DB 저장 | API 조회용 ID. **별도 컬럼이 아니라 `technical_reports.id`(UUID)를 의미** |

### 4.1 request_id

MVP 단독 구조에서는 백엔드가 생성한다. 전체 멀티에이전트 구조에서는 Top Supervisor가 생성한 값을 백엔드가 전달받아 AI에 넘긴다. 런타임 추적용이며 DB에는 저장하지 않는다(`contracts.md` 런타임 필드 규약).

### 4.2 trace_id

AI Technical Supervisor 진입 시 생성된다. AI 응답 JSON에 포함되며, 백엔드는 이 값을 `technical_reports.trace_id`에 저장한다. 영구 추적의 기준이다.

### 4.3 report_id

백엔드가 리포트 저장 시 생성한다. **별도의 짧은 ID를 만들지 않고 `technical_reports.id`(UUID PK)를 그대로 조회 ID로 쓴다.** 자식 테이블이 이미 `report_id`로 이 UUID를 FK 참조하므로, 별도 컬럼을 만들면 식별자가 중복된다.

---

## 5. 공통 요청/응답 규칙

- **Content-Type:** `application/json`
- **시간:** 모든 시각은 ISO8601 문자열 (`"2026-06-30T14:30:00+09:00"`)
- **응답 원칙:**
  - 백엔드는 HTML을 반환하지 않는다. 화면 렌더링용 구조화 JSON만 반환한다.
  - 프론트엔드는 `frontend_mapping.md` 기준으로 렌더링한다.
  - AI 최종 출력 구조는 `contracts.md`를 따른다.
  - **판단 불가·폴백도 가능한 경우 실패가 아니라 정상 응답으로 처리한다**(§8).
- **응답 wrapper:** 백엔드 응답은 `{ report_id, report }` 형태다. `report`는 `contracts.md`의 Agent Output JSON을 그대로 담고, 백엔드는 `report_id`만 추가한다. `request_id`는 `report` 내부에 이미 있으므로 wrapper 최상위에 중복으로 두지 않는다. 단, **저장된 리포트 조회 응답에서는 `request_id`가 제외될 수 있다** — 런타임 필드라 DB에 저장하지 않기 때문이며, 영구 조회는 `report_id`·`trace_id`를 기준으로 한다(§6.2).

---

## 6. Frontend → Backend API

### 6.1 기술 리포트 생성

```
POST /api/technical/reports
```

**Request Body**
```json
{
  "ticker": "373220",
  "query": "LG에너지솔루션 최근 기술적 흐름을 분석해줘",
  "as_of": "2026-06-30T14:30:00+09:00"
}
```

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `ticker` | string | YES | 종목 코드 |
| `query` | string | YES | 사용자 질의 |
| `as_of` | string | NO | 분석 기준 시각. 없으면 서버 현재 시각 |

**Backend 처리 흐름:** 요청 검증 → `request_id` 생성 → AI 내부 API 호출 → AI 응답 검증 → PostgreSQL 저장(`report_id`=저장된 UUID) → 리포트 JSON 반환.

**Response Body** — 아래는 응답 **wrapper 구조**를 보여주기 위한 축약 예시다. `report` 내부의 전체 필드 구조는 `contracts.md`의 Agent Output JSON을 따른다.
```json
{
  "report_id": "550e8400-e29b-41d4-a716-446655440000",
  "report": {
    "request_id": "req_abc123",
    "ticker": "373220",
    "as_of": "2026-06-30T14:30:00+09:00",
    "source": "KIS",
    "trace_id": "trace_xyz789",
    "data_status": "normal",
    "regime": { "final_regime": "overheated", "alignment_flag": "neutral", "...": "..." },
    "signal": { "consensus": "neutral", "signal_score": 0.12, "confidence": 0.62, "...": "..." },
    "technical_signals": [ { "indicator": "rsi", "signal": "neutral", "...": "..." } ],
    "risk": { "items": [] },
    "charts": [ { "period": "1y", "...": "..." } ],
    "interpretation": { "text": "...", "source": "llm" },
    "verification": { "outcome": "passed", "...": "..." }
  }
}
```

> `risk`는 계약상 `{ "items": [...] }` 또는 판단 불가 시 `null`이다(빈 `{}`가 아니다). `interpretation`은 항상 `text`·`source`를 가지며, `verification`은 `calc_passed`·`regime_passed`·`label_matched`·`outcome`·`regen_count`를 가진다. 전체 구조는 `contracts.md` 참조.

| 상태 | 의미 |
| --- | --- |
| 201 Created | 리포트 생성·저장 성공 (판단 불가·폴백 포함) |
| 400 Bad Request | 요청 JSON 오류 |
| 422 Unprocessable Entity | ticker·query 검증 실패 |
| 502 Bad Gateway | AI 에이전트 호출 실패 |
| 504 Gateway Timeout | AI 에이전트 응답 시간 초과 |

### 6.2 기술 리포트 단건 조회

```
GET /api/technical/reports/{report_id}
```

**Response Body** (wrapper 구조 축약 예시 — `report` 전체 구조는 `contracts.md`)
```json
{
  "report_id": "550e8400-e29b-41d4-a716-446655440000",
  "report": {
    "ticker": "373220",
    "as_of": "2026-06-30T14:30:00+09:00",
    "source": "KIS",
    "trace_id": "trace_xyz789",
    "data_status": "normal",
    "regime": { "final_regime": "overheated", "...": "..." },
    "signal": { "consensus": "neutral", "...": "..." },
    "technical_signals": [ "..." ],
    "risk": { "items": [] },
    "charts": [ "..." ],
    "interpretation": { "text": "...", "source": "llm" },
    "verification": { "outcome": "passed", "...": "..." }
  }
}
```

> `request_id`는 런타임 필드라 DB에 저장하지 않으므로, **저장된 리포트 조회 응답에는 포함되지 않는다**(`contracts.md` 런타임 필드 규약). 영구 조회·디버깅은 `report_id`·`trace_id`를 기준으로 한다. 그 외 `report` 구조는 생성 응답과 동일하게 contracts를 따른다.

| 상태 | 의미 |
| --- | --- |
| 200 OK | 조회 성공 |
| 404 Not Found | 해당 리포트 없음 |

### 6.3 기술 리포트 목록 조회

```
GET /api/technical/reports?ticker=373220&limit=20
```

| 파라미터 | 필수 | 설명 |
| --- | --- | --- |
| `ticker` | NO | 종목 코드 |
| `limit` | NO | 조회 개수 (기본 20) |
| `cursor` | NO | 페이지네이션 커서 |

**Response Body** (목록은 요약만 — schema.md의 목록용 요약 필드)
```json
{
  "items": [
    {
      "report_id": "550e8400-e29b-41d4-a716-446655440000",
      "ticker": "373220",
      "as_of": "2026-06-30T14:30:00+09:00",
      "final_regime": "overheated",
      "consensus": "neutral",
      "confidence": 0.62,
      "data_status": "normal",
      "trace_id": "trace_xyz789",
      "created_at": "2026-06-30T14:30:08+09:00"
    }
  ],
  "next_cursor": null
}
```

목록은 요약만 반환한다. 전체 내용은 단건 조회 API를 쓴다.

### 6.4 Trace 조회 (관리자/디버그)

```
GET /api/technical/reports/{report_id}/trace
```

일반 사용자 화면이 아니라 관리자/디버그 용도다.

**Response Body** (`trace_schema.md`의 Summary + 이벤트 요약)
```json
{
  "report_id": "550e8400-e29b-41d4-a716-446655440000",
  "trace_id": "trace_xyz789",
  "status": "completed",
  "data_status": "normal",
  "outcome": "passed",
  "regen_count": 0,
  "events_summary": [
    { "node": "data_collect", "status": "success", "duration_ms": 320 },
    { "node": "regime_classify", "status": "success", "duration_ms": 12 },
    { "node": "interpret_report", "status": "success", "duration_ms": 1250 }
  ]
}
```

MVP는 전체 JSONL 원문이 아니라 요약만 반환한다. 전체 trace log 조회는 Future Work.

---

## 7. Backend → AI Agent 내부 API

### 7.1 분석 실행

```
POST /internal/technical/analyze
```

내부망 또는 내부 토큰으로만 호출한다. 프론트엔드는 직접 호출하지 않는다.

**Request Body**
```json
{
  "request_id": "req_abc123",
  "ticker": "373220",
  "query": "LG에너지솔루션 최근 기술적 흐름을 분석해줘",
  "as_of": "2026-06-30T14:30:00+09:00"
}
```

`contracts.md`의 입력 계약(ticker·query·request_id·as_of) 4개를 그대로 받는다.

**Response Body:** `contracts.md`의 Agent Output JSON 그대로 (최상위에 request_id·ticker·as_of·source·trace_id·data_status + regime·signal·technical_signals·risk·charts·interpretation·verification).

| 상태 | 의미 |
| --- | --- |
| 200 OK | 분석 완료 (판단 불가·폴백도 정상 응답에 포함) |
| 400 Bad Request | 요청값 오류 |
| 500 Internal Server Error | AI 내부 오류 |
| 504 Gateway Timeout | AI 에이전트 전체 처리 시간 초과. 단, KIS 개별 호출 실패·timeout은 AI 내부 재시도·폴백으로 처리 가능하면 200 응답의 `stale_cache` 또는 `data_limited`로 반환한다 |

### 7.2 Health Check

```
GET /internal/technical/health
```

```json
{ "status": "ok", "service": "technical-agent", "version": "0.1.0" }
```

---

## 8. 예외 상태 응답 원칙

**아래는 API 실패가 아니라 정상 리포트 응답으로 처리한다** (200/201). 이것이 "판단 불가도 정직하게 반환"이 HTTP 레벨까지 일관되는 지점이다.

| 상황 | HTTP | data_status / outcome |
| --- | --- | --- |
| 정상 분석 | 200/201 | normal / passed |
| stale cache 사용 | 200/201 | stale_cache |
| 봉 수 부족 | 200/201 | regime_unavailable |
| 데이터 제한 | 200/201 | data_limited |
| LLM 재생성 성공 | 200/201 | outcome=regenerated |
| 템플릿 폴백 | 200/201 | outcome=template_fallback |

> `data_limited`는 특히 주의: **에러(502/504)가 아니라 정상 응답**이다. W/M만 미확보된 경우 일봉 기준 분석 결과가 정상적으로 담겨 나가므로, 백엔드·프론트는 이를 실패로 처리하지 말고 "일부 데이터 제한" 상태로 렌더링한다(`frontend_mapping.md` §13.4). D도 미확보된 경우만 분석 불가 형태로 안전 착지한다.

**아래는 API 실패로 처리한다:**

| 상황 | HTTP | 설명 |
| --- | --- | --- |
| 요청 JSON 오류 | 400 | JSON 파싱 실패 |
| 필수값 누락 | 422 | ticker/query 누락 |
| 종목 코드 형식 오류 | 422 | 지원하지 않는 ticker 형식 |
| MVP 범위 밖 종목 | 422 | allowlist(2차전지 10종목) 밖 → OUT_OF_SCOPE_TICKER |
| AI 서버 응답 없음 | 502/504 | AI 서버 장애 또는 timeout |
| DB 저장 실패 | 500 | 리포트 저장 실패 |

---

## 9. 공통 Error Response

```json
{
  "error": {
    "code": "AI_TIMEOUT",
    "message": "AI 에이전트 응답 시간이 초과되었습니다.",
    "request_id": "req_abc123",
    "trace_id": null
  }
}
```

| 코드 | HTTP | 의미 |
| --- | --- | --- |
| `INVALID_REQUEST` | 400 | 요청 JSON 오류 |
| `VALIDATION_ERROR` | 422 | 필수값 누락/형식 오류 |
| `OUT_OF_SCOPE_TICKER` | 422 | MVP 조사 범위(2차전지 10종목) 밖 종목 |
| `REPORT_NOT_FOUND` | 404 | 리포트 없음 |
| `AI_TIMEOUT` | 504 | AI 응답 시간 초과 |
| `AI_UNAVAILABLE` | 502 | AI 호출 불가 |
| `DB_ERROR` | 500 | DB 저장 실패 |
| `INTERNAL_ERROR` | 500 | 알 수 없는 서버 오류 |

`error.trace_id`는 AI trace가 생성된 경우에만 포함된다(생성 전 실패면 null).

---

## 10. Timeout / Retry 정책

**Frontend → Backend:** 프론트는 동일 요청을 자동 반복하지 않는다. 사용자가 새로 요청한 경우에만 다시 호출한다.

**Backend → AI Agent:**

| 항목 | 값 |
| --- | --- |
| timeout | 60초 |
| retry | 기본 미사용 |
| 이유 | AI 내부에서 KIS/LLM 재시도·폴백을 이미 처리(`config.md`·`sequence.md`) |

백엔드가 전체 분석을 재시도하면 중복 리포트가 생기므로, MVP에서는 백엔드 레벨 자동 재시도를 두지 않는다. Future Work에서 idempotency key(`Idempotency-Key: <client-key>`) 도입 가능.

---

## 11. 저장 경계

| 계층 | 저장 여부 | 설명 |
| --- | --- | --- |
| Frontend | 저장 안 함 | API 응답을 화면 렌더링에 사용 |
| Backend | 저장함 | PostgreSQL에 최종 리포트 저장 |
| AI Agent | 최종 리포트 DB 저장 안 함 | Redis 가격 캐시·trace log만 관리 |

AI Agent는 PostgreSQL에 직접 쓰지 않는다. 백엔드가 AI 응답을 검증하고 저장한다(`schema.md` §2 저장 책임 경계와 일치).

---

## 12. 보안 및 접근 범위

| API | 접근 범위 |
| --- | --- |
| `/api/technical/*` | 프론트엔드에서 호출 |
| `/internal/technical/*` | 백엔드 내부 호출만 허용 |

내부 API는 외부에 노출하지 않는다. 배포 시 내부망·API key·service token 중 하나로 보호한다. MVP에서는 인증을 단순화할 수 있다.

---

## 13. 버전 관리

API 변경 시 **변경 성격에 따라 기준(정본) 문서를 먼저 수정**한다. 하나의 고정 순서가 아니다.

| 변경 유형 | 먼저 수정할 문서 | 이후 반영 |
| --- | --- | --- |
| 요청/응답 JSON 필드 변경 | `contracts.md` | `api_spec.md` → `frontend_mapping.md` → 구현 |
| 엔드포인트·HTTP status·timeout 변경 | `api_spec.md` | 관련 문서 → 구현 |
| DB 컬럼명·저장 구조 변경 | `schema.md` | `contracts.md` → `api_spec.md` → 구현 |
| enum 코드값·표시 라벨 변경 | `enums.md` | `contracts.md` → `frontend_mapping.md` → 구현 |

응답 JSON 필드가 바뀌면 `contracts.md`, 저장 구조가 바뀌면 `schema.md`, enum 값이 바뀌면 `enums.md`를 먼저 수정한다. **어느 경우든 문서를 먼저 고치고 구현이 따라온다**(README 변경 규약과 일치).

---

## 14. 관련 문서

| 문서 | 역할 |
| --- | --- |
| `contracts.md` | AI 입출력 JSON 계약 (`report` 본문의 구조) |
| `schema.md` | PostgreSQL 저장 구조 (report_id = technical_reports.id) |
| `frontend_mapping.md` | JSON → 화면 렌더링 규칙 |
| `trace_schema.md` | trace 로그 구조 (§6.4 trace 조회) |
| `enums.md` | 코드값과 표시 라벨 |
| `config.md` | timeout·retry·threshold 설정 |
