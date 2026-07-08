# Industry Backend Handoff

`docs/industry_backend_handoff.md`

이 문서는 Industry(산업/섹터) 담당자가 backend 쪽 구현을 이어받을 때 참고할 handoff 문서다.
목표는 Industry AI의 `research-report.v1` 결과를 backend에 안전하게 저장/조회할 수 있도록
경계, 책임, 금지사항, 구현 순서를 정리하는 것이다.

이 문서는 backend 구현 지시와 범위를 다룬다. PostgreSQL 물리 스키마 정본은
[`schema.md`](schema.md), 마이그레이션 절차는 [`migrations.md`](migrations.md),
공통 종목 식별 경계는 [`stock_resolver.md`](stock_resolver.md), 공통 종목 마스터(KIS)는
[`stock_master_sync.md`](stock_master_sync.md)를 따른다.

---

## 1. 현재 상태 요약

현재 repository 기준으로 확인된 사실:

- Industry AI는 이미 동작하는 agent/payload export 경로를 가진다
- payload 정본은 `research-report.v1` JSON이다
- backend PostgreSQL에는 `industry_reports` 테이블이 이미 존재한다
- `industry_reports.payload`가 전체 JSON 정본이고, `report_id`는 `payload.reportId`와 대응한다
- Industry AI는 현재 AI 패키지 내부의 `COMPANIES` 10종 리스트와 raw/extracted data를 전제로 움직인다
- Industry AI는 종목을 `stock_code` 중심으로 다루며, DART/Neo4j/벡터 검색을 사용한다

관련 근거:

- AI 종목 목록: [companies.py](/Users/parkjinhee/AI/verith/ai/src/agents/industry/companies.py:1)
- AI 최종 payload export: [report_export.py](/Users/parkjinhee/AI/verith/ai/src/agents/industry/report_export.py:439)
- backend 저장 테이블: [industry_report.py](/Users/parkjinhee/AI/verith/backend/db/models/industry/industry_report.py:1)

---

## 2. 이번 backend 작업의 목표

이번 industry backend 작업의 핵심은 아래 2개다.

- Industry AI가 만든 `research-report.v1` payload를 backend가 저장/조회할 수 있게 만들기
- Industry에서 종목이 필요할 때 공통 backend `stocks` / `stock_resolver` 경계를 재사용하게 만들기

즉, 이번 작업의 본질은:

- 새 Industry 전용 종목 마스터를 만드는 것 아님
- 새 Industry 전용 KIS sync를 만드는 것 아님
- backend가 Industry payload를 저장하고, 종목 식별은 공통 경계를 쓰게 만드는 것

---

## 3. KIS 관련 원칙

Industry도 결과적으로는 KIS/종목코드를 참고할 수 있지만, backend에서 새로 전용 경계를 만들면 안 된다.

### 3.1 공통 경계 재사용

Industry backend는 아래를 공통 자산으로 재사용한다.

- `stocks`: 공통 종목 마스터
- `stock_aliases`: 공통 별칭
- `stock_resolver`: 자연어 질의 -> 종목 식별
- `stock master sync`: KIS -> `stocks`

즉, Industry 때문에 별도로:

- `industry_stocks`
- `industry_stock_resolver`
- `industry_kis_sync`

같은 것을 만들지 않는다.

### 3.2 backend가 직접 KIS를 새로 호출해야 하는가

기본 원칙은 `아니오`다.

Industry backend의 1차 책임은:

- AI가 만든 payload 저장
- 필요 시 공통 종목 정본 확인

이지, Industry를 위해 backend가 또 다른 KIS 시세/마스터 호출 계층을 늘리는 것이 아니다.

예외적으로 Industry AI가 정말 KIS 가격/시총/시장정보 같은 보조 메타를 payload에 안 넣고 backend가
추가로 채워야 하는 요구가 생기면, 그때도 Industry 전용으로 만들지 말고 공통 서비스 확장으로 간다.
이번 단계에서는 그런 확장을 하지 않는다.

---

## 4. 저장 정본과 책임 분리

### 4.1 저장 정본

Industry의 backend 저장 정본은 `industry_reports.payload` 이다.

즉:

- `payload` = research-report.v1 전체 JSON 정본
- `report_id` = `payload.reportId`
- `question` = `payload.question.text`
- `question_type` = `payload.question.type`
- `answer_text` = `payload.answer.body` 또는 headline/body 조합 정책
- `schema_version` = `payload.schemaVersion`
- `status` = backend lifecycle 정본

### 4.2 backend가 하지 말아야 할 것

backend는 Industry payload를 받아서 아래처럼 “재해석”하면 안 된다.

- graph/evidence를 다시 계산
- answer를 다시 만들기
- payload 내부의 관계를 backend 로직으로 수정
- KIS/DART/Neo4j를 다시 호출해서 payload를 증강

이번 단계의 backend는 `저장/조회 경계`이지, `산업 분석 재실행기`가 아니다.

---

## 5. 권장 구현 범위

이번 브랜치에서 backend 담당자가 구현하면 좋은 범위는 아래다.

### 5.1 저장 API

권장:

- `POST /industry/reports`
- 요청: Industry AI payload 또는 backend가 정의한 thin wrapper
- 응답: 생성된 report summary

역할:

- payload 기본 검증
- `industry_reports` 저장
- `agent_reports` 인덱스 row 추가
- 필요 시 `stocks`와 논리 연결

### 5.2 조회 API

권장:

- `GET /industry/reports/{report_id}`
- `GET /reports?agent_type=industry ...`

역할:

- payload 원본 조회
- report root + agent_reports 인덱스 조회

### 5.3 삭제 API

선택:

- `DELETE /industry/reports/{report_id}`

다른 에이전트 패턴과 정합을 맞추려면 넣을 수 있으나, 꼭 이번 브랜치에서 필수는 아니다.

---

## 6. stocks / resolver 연동 방식

Industry도 질의 기반으로 동작한다면, 종목 식별은 공통 resolver를 따라야 한다.

추천 흐름:

1. 사용자 질의
2. 상위 Supervisor/Chat 계층이 필요할 때만 `stock_resolver` 호출
3. `resolved.stock.stock_code`를 Industry AI 또는 backend 저장 흐름에 전달
4. backend 저장 시 `agent_reports.stock_code` 등에 반영

중요:

- Industry backend가 자체 문자열 파싱으로 종목을 다시 추정하지 않는다
- 종목 식별은 공통 `stock_resolver` 경계에 맡긴다
- Industry AI 내부 `COMPANIES` 10종 목록과 backend `stocks`는 장기적으로 분리된 채 존재할 수 있다
  - `COMPANIES`: 현재 AI 분석 대상 universe
  - `stocks`: backend 공통 종목 마스터

즉 `stocks`에 종목이 있다고 Industry AI가 자동으로 그 종목을 지원하는 것은 아니다.

---

## 7. 권장 데이터 매핑

Industry payload가 대략 아래 구조를 갖는다고 보고 backend는 최소 승격만 한다.

예상 매핑:

- `industry_reports.report_id` <- `payload.reportId`
- `industry_reports.question` <- `payload.question.text`
- `industry_reports.question_type` <- `payload.question.type`
- `industry_reports.answer_text` <- `payload.answer.body`
- `industry_reports.payload` <- 전체 payload
- `industry_reports.schema_version` <- `payload.schemaVersion`
- `industry_reports.status` <- backend lifecycle (`completed` 등)

추가 권장:

- `agent_reports.agent_type = "industry"`
- `agent_reports.agent_report_id = industry_reports.id`
- `agent_reports.stock_code`는 종목 context가 있을 때만 저장
- `agent_reports.stock_name`도 있을 때만 저장
- `agent_reports.question` / `answer_text` / `trace_id` / `summary` 연결

주의:

- `industry_reports.report_id`와 `industry_reports.id`를 혼동하지 말 것
- 외부 노출용은 `report_id`
- 내부 FK/논리참조용은 `id`

---

## 8. migration / schema 관련 주의

현재 `industry_reports`는 이미 존재한다.

이번 브랜치에서 먼저 할 일:

- 지금 스키마가 Industry AI의 실제 payload 저장에 충분한지 확인
- 충분하면 migration 없이 service/repository/route만 구현
- 부족하면 migration은 최소 범위로만 추가

현재 보기에 우선 필요한 건 스키마 변경보다는 저장/조회 서비스 쪽일 가능성이 높다.

즉, 팀원은 migration부터 만들기보다:

1. 현재 `industry_reports` 모델과 AI payload 구조 비교
2. 빠지는 필드가 있는지 확인
3. 정말 필요한 경우에만 migration 제안

순서로 가는 게 좋다.

---

## 9. 테스트 원칙

Industry backend 브랜치 테스트는 아래 기준을 따른다.

- 실 KIS 호출 0
- 실 DART 호출 0
- 실 Neo4j 호출 0
- AI payload는 fixture로 주입
- DB rollback 격리

권장 테스트:

- payload 저장 성공
- `report_id` / `schemaVersion` 매핑
- `agent_reports` 인덱스 생성
- 종목 context 있을 때/없을 때 저장 차이
- 조회 API
- 없는 report 404
- 삭제 시 인덱스 정리 여부

중요:

- Industry backend 브랜치는 “AI가 payload를 잘 만들었는지”를 테스트하는 곳이 아니다
- “backend가 payload를 안전하게 저장/조회하는지”만 본다

---

## 10. 팀원에게 넘길 구현 순서

권장 순서:

1. 현재 `industry_reports` 모델과 AI payload 구조 대조
2. migration 필요 여부 판단
3. repository 구현
4. service 구현
5. route 구현
6. 테스트 작성
7. README / schema 문서 반영

이번 브랜치에서 하지 말 것:

- Industry AI 로직 변경
- Neo4j 쿼리 재구현
- KIS/DART 새 수집기 추가
- Industry 전용 resolver 추가
- Industry 전용 stock master 추가

---

## 11. 완료 조건

아래를 만족하면 backend side handoff 기준 완료다.

1. Industry payload 저장 API가 동작
2. Industry report 조회 API가 동작
3. `industry_reports`와 `agent_reports` 연결이 정리됨
4. 테스트 통과
5. 문서 반영 완료
6. 종목 식별은 공통 `stocks/resolver` 재사용 원칙이 문서에 명시됨

---

## 12. 한 줄 요약

Industry backend는 새 KIS 경계를 만드는 작업이 아니라,
이미 있는 공통 `stocks/resolver`를 재사용하면서 Industry AI의 `research-report.v1` payload를
`industry_reports`에 저장/조회할 수 있게 만드는 작업이다.

