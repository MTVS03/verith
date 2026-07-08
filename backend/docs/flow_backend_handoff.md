# Flow Backend Handoff

`docs/flow_backend_handoff.md`

이 문서는 Flow(수급/자금흐름) 담당자가 backend 쪽 구현을 이어받을 때 참고할 handoff 문서다.
목표는 Flow AI가 이미 만드는 payload를 backend가 안전하게 저장/조회할 수 있도록
경계, 책임, 금지사항, 구현 순서를 정리하는 것이다.

상위 supervisor / chat orchestration 은 이 문서 범위 밖이다.
즉, 이 문서는 “Flow backend 저장/조회 경계”에만 집중한다.

이 문서는 backend 구현 지시와 범위를 다룬다. PostgreSQL 물리 스키마 정본은
[`schema.md`](schema.md), 마이그레이션 절차는 [`migrations.md`](migrations.md),
공통 종목 식별 경계는 [`stock_resolver.md`](stock_resolver.md), 공통 종목 마스터(KIS)는
[`stock_master_sync.md`](stock_master_sync.md)를 따른다.

---

## 1. 현재 상태 요약

repository 기준으로 확인된 사실:

- Flow AI는 이미 최종 JSON payload 를 만든다
- Flow AI는 저장을 하지 않고 payload export 만 담당한다
- Flow 는 HTML도 생성하지만, 저장 정본은 HTML 이 아니라 JSON payload 다
- backend PostgreSQL 에는 flow 3테이블이 이미 존재한다
  - `flow_reports`
  - `flow_report_interpretations`
  - `flow_report_verifications`

관련 근거:

- AI 저장 명세: [ai/src/agents/flow/docs/storage-spec.md](/Users/parkjinhee/AI/verith/ai/src/agents/flow/docs/storage-spec.md)
- backend root 테이블: [backend/db/models/flow/flow_report.py](/Users/parkjinhee/AI/verith/backend/db/models/flow/flow_report.py)
- backend 해석 테이블: [backend/db/models/flow/report_interpretation.py](/Users/parkjinhee/AI/verith/backend/db/models/flow/report_interpretation.py)
- backend 검증 테이블: [backend/db/models/flow/report_verification.py](/Users/parkjinhee/AI/verith/backend/db/models/flow/report_verification.py)

---

## 2. 이번 backend 작업의 목표

이번 Flow backend 작업의 핵심은 아래 2개다.

- Flow AI payload 를 backend 스키마 3테이블에 정확히 매핑해 저장/조회하게 만들기
- 종목 context 가 필요할 때 공통 `stocks` / `stock_resolver` 경계를 재사용하게 만들기

즉, 이번 작업의 본질은:

- 새 Flow 전용 종목 마스터를 만드는 것 아님
- 새 Flow 전용 stock resolver 를 만드는 것 아님
- Flow HTML 을 DB 에 저장하는 것 아님
- Flow 계산 로직을 backend 에서 재구현하는 것 아님

backend 는 “Flow 분석기”가 아니라 “Flow 결과 저장/조회 경계”여야 한다.

---

## 3. 저장 정본과 책임 분리

### 3.1 저장 정본

Flow 의 저장 정본은 AI 가 내보내는 payload(JSON) 이다.

즉:

- payload = 사실/검증/해석의 최종 스냅샷
- backend 는 payload 를 분해해 3테이블에 저장할 뿐, 의미를 다시 만들지 않는다
- frontend 는 저장된 JSON/필드를 읽어 다시 그린다
- HTML 은 디자인 레퍼런스일 뿐 DB 저장 대상이 아니다

### 3.2 backend 가 하지 말아야 할 것

backend 는 Flow payload 를 받아서 아래처럼 재해석하면 안 된다.

- signals 다시 계산
- verification 문장 재구성
- interpretation 다시 생성
- alignment / ownership / inst_detail 재판정
- HTML 렌더 결과 저장

이번 단계의 backend 는 `저장/조회 경계`이지, `Flow 리포트 재생성기`가 아니다.

---

## 4. 공통 종목 경계 원칙

Flow 도 종목을 다루지만, backend 에서 Flow 전용 종목 계층을 다시 만들면 안 된다.

재사용할 공통 자산:

- `stocks`
- `stock_aliases`
- `stock_resolver`
- `stock master sync`

즉, Flow 때문에 별도로:

- `flow_stocks`
- `flow_stock_resolver`
- `flow_kis_sync`

같은 것을 만들지 않는다.

상위 supervisor 가 나중에 질의에서 종목을 resolve 하더라도,
backend 저장 계층은 그 결과를 받아 저장만 하면 된다.
종목 식별/라우팅을 Flow backend 가 다시 담당하지 않는다.

---

## 5. 권장 구현 범위

이번 브랜치에서 backend 담당자가 구현하면 좋은 범위는 아래다.

### 5.1 저장 API

권장:

- `POST /flow/reports`

역할:

- Flow payload 기본 검증
- `flow_reports` / `flow_report_interpretations` / `flow_report_verifications` 저장
- `agent_reports` 인덱스 row 추가

### 5.2 조회 API

권장:

- `GET /flow/reports/{report_id}`
- `GET /reports?agent_type=flow ...`

역할:

- root + interpretation + verification 함께 조회
- “검증 없는 숫자”가 나오지 않게 세 테이블을 묶어서 반환

### 5.3 삭제 API

선택:

- `DELETE /flow/reports/{report_id}`

다른 에이전트 패턴과 정합을 맞추고 싶으면 넣을 수 있다.
다만 이번 브랜치의 핵심은 저장/조회다.

---

## 6. 권장 데이터 매핑

Flow payload version 1 기준으로 backend 는 최소 승격만 한다.

### 6.1 `flow_reports`

- `id` <- 가능하면 AI `report_id` 그대로 사용
- `ticker` <- `payload.meta.ticker`
- `stock_name` <- `payload.meta.stock_name`
- `market` <- `payload.meta.market`
- `base_date` <- `payload.meta.base_date`
- `alignment` <- `payload.signals.alignment`
- `signals` <- `payload.signals` 전체 JSON
- `trace_id` <- `payload.trace_id`
- `data_status` <- backend/AI 합의된 enum (현재 별도 확인 필요)

### 6.2 `flow_report_interpretations`

- `report_id` <- `flow_reports.id`
- `interpretation` <- `payload.interpretation`
- `interpretation_source` <- `payload.interpretation_meta.source`
- `provider` <- `payload.interpretation_meta.provider`
- `model` <- `payload.interpretation_meta.model`

### 6.3 `flow_report_verifications`

- `report_id` <- `flow_reports.id`
- `gate1_passed` <- `payload.verification.gate1.passed`
- `gate2_passed` <- `payload.verification.gate2.passed`
- `gate3_passed` <- `payload.verification.gate3.passed`
- `checks` <- verification checks/failures JSON
- `outcome` <- `payload.verification.outcome`
- `regen_count` <- `payload.verification.regen_count`

---

## 7. 특히 주의할 결정 포인트

### 7.1 report_id / PK

가장 깔끔한 방향은 `flow_reports.id` 에 AI 가 만든 `report_id` 를 그대로 넣는 것이다.

이유:

- Flow spec 에서 `report_id` 는 추적 가능한 외부 ID 역할을 한다
- 저장 시 backend 가 별도 UUID 를 새로 만들면 추적성이 끊긴다

만약 팀이 내부 PK 와 외부 report_id 를 분리하고 싶다면,
적어도 external report id 를 별도 컬럼으로 보존해야 한다.
지금처럼 조용히 새 UUID 만 만드는 방향은 피하는 게 좋다.

### 7.2 data_status

Flow AI 문서상 `data_status` 는 아직 backend 쪽 enum 합의가 선행되어야 한다.

즉 backend 팀이 먼저:

- 어떤 enum 을 쓸지
- 언제 `normal/degraded/...` 로 볼지

를 정하면, 이후 AI payload 에 맞춰 실어도 된다.
이번 브랜치에서 backend 임의 enum 을 먼저 박아넣는 건 피하는 편이 안전하다.

---

## 8. agent_reports 인덱스 권장

다른 에이전트와 정합을 맞추려면 Flow 저장 시 `agent_reports` 도 같이 만드는 것이 좋다.

권장 매핑:

- `agent_type = "flow"`
- `agent_report_id = flow_reports.id`
- `stock_code = payload.meta.ticker`
- `stock_name = payload.meta.stock_name`
- `question` = 상위 계층이 있으면 원질문, 없으면 nullable
- `answer_text` = interpretation 이 있으면 그 값, 없으면 nullable 또는 요약문
- `summary` = `{alignment, base_date, market, outcome, gate3_passed ...}` 정도의 얇은 요약
- `trace_id` = payload.trace_id

중요:

- `agent_reports` 는 검색/목록용 인덱스다
- Flow 정본은 여전히 flow 3테이블 + payload 매핑이다

---

## 9. 테스트 원칙

Flow backend 브랜치 테스트는 아래 기준을 따른다.

- 실 KIS 호출 0
- 실 OpenAI 호출 0
- AI payload 는 fixture 주입
- DB rollback 격리

권장 테스트:

- payload 저장 성공
- 3테이블 매핑 정확성
- interpretation null 의미 유지
- verification outcome / regen_count 보존
- `agent_reports` 인덱스 생성
- 조회 시 root + interpretation + verification 동시 반환
- 없는 report 404
- 삭제 시 interpretation / verification cascade 정리

중요:

- 이 브랜치는 Flow 계산이 맞는지 테스트하는 곳이 아니다
- backend 가 이미 계산된 payload 를 안전하게 저장/조회하는지만 본다

---

## 10. 팀원에게 넘길 구현 순서

추천 순서:

1. AI storage spec 과 backend flow 모델 3개를 나란히 비교
2. `POST /flow/reports` 저장 service/repository 구현
3. `agent_reports` 인덱스 연결
4. `GET /flow/reports/{report_id}` 조회 구현
5. 필요 시 `DELETE` 구현
6. fixture 기반 테스트 보강

순서를 이렇게 잡으면 migration 없이도 먼저 큰 흐름을 붙일 수 있다.

---

## 11. 이번 브랜치에서 하지 않을 것

- 상위 supervisor 구현
- Flow 종목 식별 로직 구현
- Flow 전용 KIS 호출 계층
- Flow 전용 stocks/alias/resolver
- HTML 저장
- Flow 계산/검증/해석 재구현
- frontend 렌더 구현

---

## 12. 한 줄 결론

Flow backend 는 “새 분석 로직”을 만드는 브랜치가 아니라,
**AI 가 이미 만든 Flow payload 를 공통 종목 경계를 해치지 않고 3테이블 + agent_reports 로 저장/조회하게 만드는 브랜치**로 가는 것이 맞다.
