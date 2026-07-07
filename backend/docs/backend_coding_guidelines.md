# veriθ Backend — 코드 작성 규칙

`docs/backend_coding_guidelines.md`

이 문서는 veriθ 백엔드 서버를 구현할 때 지켜야 할 코드 작성 기준을 정리한다. 목적은 단순한 스타일 통일이 아니라 **책임 범위 혼동, 하드코딩, 스파게티 코드, DB 저장 불일치, 비밀키 노출, API 계약 깨짐**을 방지하는 것이다.

백엔드는 veriθ에서 **요청을 받고, AI 에이전트를 호출하고, 결과 JSON을 저장하고, 프론트에 제공하는 계층**이다. 백엔드는 기술적 지표를 직접 계산하거나 LLM 해석을 생성하지 않는다.

---

## 1. 기본 원칙

### 1.1 문서가 먼저, 코드는 그다음

백엔드의 API, DB, 응답 구조는 문서가 정본이다.

- API 변경은 `docs/api_spec.md`를 먼저 수정한다.
- DB 컬럼·테이블 변경은 `docs/schema.md`를 먼저 수정한다.
- AI 응답 JSON 구조 변경은 `docs/contracts.md`를 먼저 수정한다.
- enum/code 값 변경은 `docs/enums.md`를 먼저 수정한다.
- 화면 표시용 매핑 변경은 `docs/frontend_mapping.md`와 충돌하지 않는지 확인한다.

코드가 문서와 다르면 코드가 틀린 것으로 본다.

### 1.2 백엔드는 저장과 전달의 책임을 가진다

백엔드의 주요 책임은 다음이다.

1. 프론트 요청 검증
2. AI 서버 호출
3. AI가 반환한 JSON 검증
4. PostgreSQL 저장
5. 저장된 리포트 조회 API 제공
6. trace_id/report_id 기준 추적 연결

백엔드는 기술적 국면·신호·신뢰도·리스크를 직접 계산하지 않는다.

---

## 2. 하드코딩 금지

### 2.1 금지하는 하드코딩

아래 값은 코드 중간에 직접 박아 넣지 않는다.

- DB URL
- AI 서버 URL
- JWT secret
- API timeout
- CORS 허용 origin
- enum 문자열
- HTTP status 규칙
- 테이블명·컬럼명 문자열 남발
- 사용자 노출 라벨
- 테스트용 유저 id, report id

나쁜 예:

```python
AI_SERVICE_URL = "http://localhost:8001"
```

좋은 예:

```python
from src.core.config import settings

ai_service_url = settings.AI_SERVICE_URL
```

### 2.2 비밀값은 코드·로그·응답에 노출하지 않는다

아래 값은 코드, 로그, API 응답에 노출하지 않는다.

- DB 비밀번호
- JWT secret
- access token / refresh token
- 외부 API key
- 사용자 개인정보

에러 응답에도 내부 설정값을 그대로 노출하지 않는다.

---

## 3. 백엔드 책임 경계

### 3.1 백엔드가 하지 말아야 할 것

백엔드는 아래 일을 하지 않는다.

- KIS 직접 호출
- RSI, 이동평균, 볼린저밴드 등 지표 계산
- regime 판정
- signal_score 계산
- confidence 계산
- risk flag 생성
- LLM 호출로 리포트 문장 생성
- HTML 생성
- 프론트 UI 라벨 임의 생성

이 값들은 AI 에이전트 또는 프론트의 책임이다.

### 3.2 백엔드는 AI 결과를 임의로 바꾸지 않는다

AI가 반환한 구조화 JSON은 백엔드에서 검증하고 저장한다. 단, 백엔드가 AI의 분석 값을 재해석하거나 바꾸면 안 된다.

금지:

```python
# AI가 sideways라고 했는데 백엔드가 임의로 변경
report.final_regime = "uptrend_intact"
```

허용:

```python
# contracts에 맞는지 검증 후 저장
validated_report = TechnicalReportResponse.model_validate(ai_response)
```

---

## 4. 모듈 구조 원칙

### 4.1 계층별 책임을 분리한다

권장 구조 예시는 다음과 같다.

```text
backend/src/
├── api/              # FastAPI 라우터
├── core/             # config, security, logging
├── clients/          # AI 서버 HTTP client
├── schemas/          # Pydantic request/response schema
├── models/           # SQLAlchemy ORM model
├── repositories/     # DB 접근
├── services/         # 비즈니스 흐름 조율
└── tests/            # 테스트
```

| 계층 | 책임 | 하지 말아야 할 것 |
| --- | --- | --- |
| `api/` | 요청/응답, status code | DB 쿼리 직접 작성, AI 호출 세부 로직 |
| `schemas/` | Pydantic 검증 | DB 접근, 외부 API 호출 |
| `models/` | DB 테이블 매핑 | 비즈니스 로직 |
| `repositories/` | DB CRUD | AI HTTP 호출 |
| `services/` | 유스케이스 조율 | SQL 세부사항 남발 |
| `clients/` | 외부 서버 호출 | DB 저장 |
| `core/` | 설정·보안·로깅 | 도메인 로직 |

### 4.2 라우터는 얇게 유지한다

라우터는 요청을 받고 service를 호출하고 response를 반환하는 역할만 한다.

나쁜 예:

```python
@router.post("/technical/reports")
def create_report(payload):
    # AI 호출
    # DB 저장
    # 여러 테이블 insert
    # 응답 가공
    ...
```

좋은 예:

```python
@router.post("/technical/reports")
def create_report(payload: CreateTechnicalReportRequest):
    return technical_report_service.create_report(payload)
```

---

## 5. DB 작성 규칙

### 5.1 DB 구조는 `schema.md`를 따른다

테이블명, 컬럼명, 관계는 `docs/schema.md`가 정본이다. 임의 컬럼을 추가하지 않는다.

DB 변경이 필요하면 순서가 중요하다.

1. `docs/schema.md` 수정
2. 관련 contracts/API 문서 수정
3. migration 작성
4. ORM model 수정
5. repository/service 수정
6. 테스트 수정

### 5.2 마이그레이션 없이 DB 구조를 바꾸지 않는다

금지:

```sql
ALTER TABLE technical_reports ADD COLUMN temp_value TEXT;
```

권장:

```bash
alembic revision --autogenerate -m "add technical report field"
alembic upgrade head
```

### 5.3 트랜잭션 경계를 명확히 한다

AI 리포트 저장은 본체와 상세 테이블이 함께 저장되어야 한다.

- 본체 저장 성공 + 상세 저장 실패 상태를 방치하지 않는다.
- 하나의 report 생성은 하나의 트랜잭션으로 묶는다.
- 실패 시 rollback한다.

---

## 6. AI 서버 호출 규칙

### 6.1 AI client를 별도 모듈로 둔다

AI 호출은 `clients/` 또는 이에 준하는 계층에 둔다.

금지:

```python
requests.post("http://ai:8001/internal/technical", json=payload)
```

권장:

```python
ai_response = ai_client.create_technical_report(payload)
```

### 6.2 timeout을 반드시 설정한다

AI 서버 호출은 무한 대기하지 않는다. Backend → AI 전체 timeout은 문서 기준을 따른다.

```python
httpx.Client(timeout=settings.AI_TIMEOUT_SECONDS)
```

### 6.3 백엔드에서 무리한 재시도는 하지 않는다

AI 내부에는 KIS 재시도·LLM 재생성·폴백이 있다. 백엔드는 AI 서버 호출 자체가 실패했을 때만 제한적으로 처리한다.

- 같은 분석 요청을 백엔드가 여러 번 중복 실행하지 않는다.
- 중복 저장 방지를 위해 request_id/trace_id/report_id 흐름을 확인한다.

---

## 7. API 응답 규칙

### 7.1 응답 schema를 반드시 사용한다

dict를 즉석에서 만들어 반환하지 않는다.

나쁜 예:

```python
return {"data": report}
```

좋은 예:

```python
return TechnicalReportResponse.model_validate(report)
```

### 7.2 예외 상태와 실패 상태를 구분한다

문서에서 정상 응답으로 정의한 상태는 HTTP 에러로 바꾸지 않는다.

예:

- `data_limited`
- `stale_cache`
- `regime_unavailable`
- `template_fallback`

이런 상태는 분석 결과의 일부일 수 있다. 서버 오류와 구분한다.

### 7.3 에러 응답은 사람이 이해할 수 있어야 한다

나쁜 예:

```json
{"detail": "Error"}
```

좋은 예:

```json
{
  "code": "AI_SERVICE_TIMEOUT",
  "message": "AI 분석 서버 응답 시간이 초과되었습니다."
}
```

---

## 8. 타입·검증 규칙

### 8.1 외부 입력은 Pydantic으로 검증한다

프론트에서 온 값은 신뢰하지 않는다.

검증 대상:

- ticker 형식
- query 길이
- request_id 형식
- as_of 날짜
- pagination 값

### 8.2 DB model과 API schema를 섞지 않는다

ORM model을 API 응답으로 그대로 내보내지 않는다.

금지:

```python
return db_report
```

권장:

```python
return TechnicalReportDetailResponse.from_orm(db_report)
```

---

## 9. 로그와 관측성

### 9.1 print 대신 logger를 쓴다

샘플 코드가 아닌 백엔드 본 코드에서는 `print`를 사용하지 않는다.

권장:

```python
logger.info("technical_report_created", extra={"report_id": report.id, "trace_id": trace_id})
```

### 9.2 trace_id를 흐름에 포함한다

AI 응답의 trace_id는 저장하고, 조회·디버깅에 사용할 수 있게 한다.

로그에 남길 것:

- request_id
- report_id
- trace_id
- ticker
- status
- elapsed_ms

로그에 남기지 말 것:

- 토큰
- 비밀번호
- API secret
- 민감한 사용자 정보

---

## 10. 테스트 규칙

### 10.1 DB 테스트와 서비스 테스트를 분리한다

테스트 유형을 나눈다.

- schema validation test
- repository test
- service test
- AI client mock test
- API route test

### 10.2 외부 AI 서버 없이 테스트 가능해야 한다

백엔드 단위테스트는 AI 서버를 실제 호출하지 않는다. AI client를 mock 처리한다.

테스트해야 할 것:

- AI 응답 JSON 저장 매핑
- 본체/상세 테이블 트랜잭션 저장
- AI timeout 처리
- allowlist 밖 종목 응답 처리
- data_limited 정상 응답 처리
- report list/detail 조회

---

## 11. 코드 생성 도구 사용 규칙

Claude/Codex에게 백엔드 작업을 맡길 때는 범위를 좁힌다.

좋은 지시:

```text
이번 단계에서는 TechnicalReport 저장 service와 repository만 구현하세요.
AI client mock을 사용하고, 실제 AI 호출은 하지 마세요.
```

나쁜 지시:

```text
백엔드 만들어줘.
```

결과 검토 기준:

- 문서에 없는 테이블·컬럼을 만들었는가?
- AI 계산을 백엔드에서 해버렸는가?
- ORM model을 응답으로 그대로 반환했는가?
- timeout 없는 외부 호출이 있는가?
- DB 트랜잭션이 깨져 있는가?
- 비밀값이 코드나 로그에 노출되는가?

---

## 12. 커밋 전 체크리스트

```bash
git status
git diff
```

체크리스트:

- [ ] 요청 범위의 파일만 변경했는가?
- [ ] `api_spec.md`, `schema.md`, `contracts.md`와 충돌하지 않는가?
- [ ] DB 변경이 있다면 migration이 있는가?
- [ ] 백엔드가 AI 분석 값을 임의로 만들거나 바꾸지 않는가?
- [ ] timeout 없는 외부 호출이 없는가?
- [ ] 트랜잭션 경계가 명확한가?
- [ ] API 응답 schema를 사용하는가?
- [ ] 비밀값이 코드·로그·응답에 노출되지 않는가?
- [ ] 테스트에서 실제 AI 서버에 의존하지 않는가?

---

## 13. 최종 원칙

백엔드는 분석가가 아니라 **신뢰할 수 있는 중계자와 저장소**다.

- Frontend 요청을 검증한다.
- AI에 분석을 요청한다.
- AI JSON을 검증한다.
- PostgreSQL에 저장한다.
- Frontend가 읽기 쉬운 API로 제공한다.

백엔드가 계산·해석·화면 역할까지 가져가면 경계가 무너진다. 경계가 지켜져야 테스트가 쉬워지고, 5개 에이전트 결과를 안정적으로 통합할 수 있다.
