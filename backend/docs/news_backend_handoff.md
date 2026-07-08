# News Backend Handoff

`docs/news_backend_handoff.md`

이 문서는 News 담당자가 backend 쪽 구현을 이어받을 때 참고할 handoff 문서다.
목표는 News AI의 배치 저장 흐름과 질의 리포트 흐름을 backend 가 안전하게 받도록,
경계, 책임, 금지사항, 구현 순서를 정리하는 것이다.

상위 supervisor / chat orchestration 은 이 문서 범위 밖이다.
즉, 이 문서는 “News backend 저장/조회/정리 경계”에 집중한다.

이 문서는 backend 구현 지시와 범위를 다룬다. PostgreSQL 물리 스키마 정본은
[`schema.md`](schema.md), 마이그레이션 절차는 [`migrations.md`](migrations.md),
공통 종목 식별 경계는 [`stock_resolver.md`](stock_resolver.md), 공통 종목 마스터(KIS)는
[`stock_master_sync.md`](stock_master_sync.md)를 따른다.
Supervisor와의 전체 연결은 [`supervisor_backend_integration.md`](supervisor_backend_integration.md)를 본다.

---

## 1. 현재 상태 요약

repository 기준으로 확인된 사실:

- News AI 는 배치 흐름과 질의(리포트) 흐름이 분리되어 있다
- 배치 흐름은 기사 수집/분석 후 backend 를 통해 PostgreSQL + Neo4j 저장을 기대한다
- 질의 흐름은 저장된 데이터를 backend 에서 조회해 JSON 리포트를 만든다
- AI 는 DB 에 직접 접근하지 않고 backend HTTP 만 쓰도록 설계돼 있다
- backend PostgreSQL 에는 `news`, `news_reports` 테이블이 이미 존재한다
- Neo4j 객체는 PostgreSQL 테이블로 만들지 않고 app 계층에서 직접 다룬다

관련 근거:

- AI 파이프라인: [ai/src/agents/news/docs/pipeline_spec.md](/Users/parkjinhee/AI/verith/ai/src/agents/news/docs/pipeline_spec.md)
- 배치 저장 HTTP 계약: [ai/src/agents/news/services/backend/save_client.py](/Users/parkjinhee/AI/verith/ai/src/agents/news/services/backend/save_client.py)
- 질의 조회 HTTP 계약: [ai/src/agents/news/services/backend/query_client.py](/Users/parkjinhee/AI/verith/ai/src/agents/news/services/backend/query_client.py)
- 리포트 JSON 계약: [ai/src/agents/news/schemas/report.py](/Users/parkjinhee/AI/verith/ai/src/agents/news/schemas/report.py)
- backend 기사 원본 테이블: [backend/db/models/news/news.py](/Users/parkjinhee/AI/verith/backend/db/models/news/news.py)
- backend 리포트 테이블: [backend/db/models/news/news_report.py](/Users/parkjinhee/AI/verith/backend/db/models/news/news_report.py)

---

## 2. 현재 구현 상태와 남은 작업

News 쪽은 이 4개 문서 중 유일하게 backend 구현이 이미 꽤 진행된 상태다.

현재 repository 기준으로 **이미 구현된 것**:

- `POST /news/batch/save`
- `POST /news/cleanup`
- `GET /news/events/recent`
- `GET /news/events/stats`
- `GET /news/query/subject`
- `GET /news/query/shared`
- `GET /news/events/{event_id}/articles`
- 관련 service / repository / schema / 테스트

즉 아래 범위는 이미 develop 기준으로 **완료 또는 구현 진행 완료**로 본다.

- 기사 원본 저장
- GraphBatch 반영
- URL -> `news_id` 해소
- single-hop / multi-hop 조회
- 대표 기사 조회
- importance 재계산 및 cleanup

이 문서에서 이제 중요한 것은 “뉴스 backend를 새로 설계하는 것”이 아니라,
**이미 구현된 것 위에서 남은 작업이 무엇인지 분리해 주는 것**이다.

### 현재 남은 작업

현재 기준으로 **아직 남아 있는 것**:

- `news_reports` 저장 API
  - `POST /news/reports`
- `news_reports` 상세 조회 API
  - `GET /news/reports/{report_id}`
- 공통 report 목록 연결
  - `GET /reports?agent_type=news`
- 선택적으로 `DELETE /news/reports/{report_id}`
- 필요 시 `agent_reports` 인덱스 연결 정책 정리
- owner 필드(`owner_user_id`, `owner_session_id`) 실제 사용 정책
- 내부 인증 / 운영 설정 hardening

즉 뉴스 팀원이 **이제 안 해도 되는 것**은:

- 배치 저장 경계 재설계
- GraphBatch -> Neo4j 기본 연결 재구현
- subject/shared/recent/stats/articles 조회 재구현
- cleanup 로직 재구현

반대로 **지금부터 해야 하는 것**은:

- 질의 결과 리포트(`news_reports`) persistence
- 필요 시 `agent_reports` 검색 인덱스 연결
- Supervisor가 만든 5-card 구조와의 최종 연결

---

## 3. backend 작업의 본질

News backend의 남은 핵심은 아래 3개다.

- 배치 흐름의 기사 원본 + 그래프 델타를 backend 가 원자적으로 저장하게 만들기
- 질의 흐름이 읽는 조회 API 를 backend 에서 제공하게 만들기
- 질의 결과 JSON 리포트를 backend 에 저장/조회 가능하게 만들기

즉, 이번 작업의 본질은:

- News AI 가 생성한 구조화 결과를 backend 가 받아 저장/조회하는 것
- PostgreSQL 과 Neo4j 의 경계를 backend 가 소유하는 것
- AI 가 직접 SQL/Cypher/DB 드라이버를 만지지 않게 하는 것

---

## 4. 가장 중요한 원칙

### 3.1 AI 는 DB 에 직접 닿지 않는다

News 쪽은 이 원칙이 특히 중요하다.

AI 는:

- SQLAlchemy import 금지
- PostgreSQL driver 직접 사용 금지
- Neo4j driver 직접 사용 금지
- DB save/query/cleanup 를 모두 backend HTTP 로만 호출

즉 News backend 는 단순 옵션이 아니라, 현재 AI 설계의 핵심 경계다.

### 3.2 backend 는 저장 원자성을 책임진다

`save_batch()` 계약상, AI 는 같은 배치에서 나온:

- `articles`
- `graph_batch`

를 함께 backend 에 넘긴다.

backend 는 이 둘을 분리해서 다루면 안 된다.

이유:

- `news` row 가 먼저 저장되어 `news_id` 가 생겨야
- graph 의 `NewsRef` 가 정확한 `news_id` 와 연결될 수 있다

즉 URL -> `news_id` 해소와 PostgreSQL/Neo4j 반영 순서는 backend 책임이다.

### 4.3 상위 supervisor 는 범위 밖

뉴스가 종목 질문으로 들어오든, 자유 질문으로 들어오든,
그 라우팅/의도판단은 이 문서 범위가 아니다.

이 문서의 backend 범위는 여전히:

- 저장
- 조회
- cleanup
- report persistence

까지만 본다.

---

단, Supervisor와의 연결 관점에서는 News는 5개 agent 중 **가장 stock context 의존도가 낮은 agent**다.

즉:

- 종목형 질문이면 resolved stock context 를 받아 쓸 수 있음
- 비종목 질문이어도 실행 가능한 경우가 많음
- stock resolve 실패가 곧 news 실행 불가를 의미하지는 않음

---

## 5. 공통 종목 경계 원칙

News 는 “전체 뉴스”를 다루므로 특정 10종 종목 universe 에 묶이면 안 된다.
다만 종목이나 회사명을 식별해야 할 때는 공통 자산을 재사용하는 쪽이 맞다.

재사용할 공통 자산:

- `stocks`
- `stock_aliases`
- `stock_resolver`

즉, News 때문에 별도로:

- `news_stocks`
- `news_stock_resolver`
- `news_aliases`

같은 걸 다시 만들지 않는다.

중요:

- News backend 는 KIS 시세 분석 계층을 새로 만들 필요가 없다
- 종목 context 가 필요하면 상위 계층 또는 공통 resolver 결과를 받으면 된다
- News 자체는 기사/이벤트 중심 저장 구조가 핵심이다

---

## 6. 저장 정본과 책임 분리

### 5.1 기사 원본 정본

기사 원본 정본은 `news` 테이블이다.

최소 보관 대상:

- title
- content
- summary
- url
- publisher
- sentiment
- sentiment_score
- embedding
- published_at
- event_id (논리 링크, FK 아님)

### 5.2 리포트 정본

뉴스 질의 결과 리포트 정본은 `NewsReport.report_json` 이다.

즉:

- `report_json` = `ReportModel` 전체 JSON 정본
- `answer_text` / `intent` / `evidence` 는 검색/목록 편의를 위한 승격 필드
- frontend 는 JSON 을 읽어 렌더한다

### 5.3 backend 가 하지 말아야 할 것

backend 는 News AI 결과를 받아 아래처럼 재해석하면 안 된다.

- sentiment 다시 계산
- importance 다시 판정해서 AI 결과를 덮어쓰기
- query answer 를 다시 생성
- graph 연결을 AI payload 와 무관하게 임의 수정

다만 backend 가 직접 해야 하는 것은 있다:

- URL 기준 upsert
- `news_id` 할당
- GraphBatch 저장 순서 보장
- cleanup 시 orphan 정리

즉 News backend 는 “의미 생성”은 안 하고, “저장 일관성”은 강하게 책임진다.

---

## 7. backend API 범위

현재 AI 쪽 config 및 backend 현재 상태 기준으로 엔드포인트는 아래처럼 이해하면 된다.

### 7.1 배치 저장 / 정리

- `POST /news/batch/save`
- `POST /news/cleanup`

역할:

- 기사 원본 저장
- GraphBatch 반영
- URL -> `news_id` 해소
- 7일 롤링 삭제 트리거

상태:

- **구현됨**

### 7.2 질의 조회

- `GET /news/events/recent`
- `GET /news/events/stats`
- `GET /news/query/subject`
- `GET /news/query/shared`
- `GET /news/events/{event_id}/articles`

역할:

- 병합 후보 조회
- importance 계산 보조 통계 조회
- single-hop / multi-hop 이벤트 조회
- 이벤트별 대표 기사 조회

상태:

- **구현됨**

### 7.3 리포트 저장/조회

권장:

- `POST /news/reports`
- `GET /news/reports/{report_id}`
- `GET /reports?agent_type=news ...`

선택:

- `DELETE /news/reports/{report_id}`

리포트 저장은 배치 저장과 별도다.
배치는 원자료 저장, 리포트는 질의 결과 저장이다.

상태:

- **아직 남은 작업**

---

## 8. `news` 테이블 쪽 구현 원칙

### 7.1 URL 기준 멱등성

`news.url` 은 UNIQUE 이므로,
저장은 URL 기준 upsert 로 가는 것이 맞다.

즉 같은 기사를 다시 받아도:

- 중복 row 를 만들지 않고
- 필요한 필드만 보강/갱신
- 동일 기사에 대한 `news_id` 는 안정적으로 유지

되어야 한다.

### 7.2 event_id 는 논리 링크만 유지

`news.event_id` 는 Neo4j Event 와의 논리 링크다.

따라서:

- PostgreSQL FK 생성 금지
- Event 관련 PostgreSQL 테이블 신설 금지

가 맞다.

그래프 구조는 backend app 이 Neo4j 에 직접 저장하고,
PostgreSQL 은 기사 원본과 연결 키만 가진다.

---

## 9. `news_reports` 테이블 쪽 구현 원칙

권장 매핑:

- `report_json` <- `ReportModel` 전체 JSON
- `question` <- 사용자 질문 원문
- `intent` <- query understanding 결과 intent
- `answer_text` <- `report_json.answer_text`
- `evidence` <- `cited_event_ids`, `evidence_news_ids` 등 근거 묶음 JSON

현재 시점에서 이 섹션은 “향후 구현해야 할 남은 작업”이다.
즉 `news_reports` 저장/조회가 아직 없다면, 다음 뉴스 backend 브랜치의 중심은 여기다.

선택 필드:

- `owner_user_id`
- `owner_session_id`

는 auth / 세션 설계가 붙을 때만 의미가 생긴다.
지금 당장 필수로 채우지 않아도 된다.

---

## 10. cleanup 책임

News cleanup 은 backend 가 책임지는 것이 맞고, 현재 구현도 이 방향과 정합하다.

현재 AI 문서 기준으로 cleanup 의 의미는:

- 7일 지난 기사 삭제
- 기사 수 0 인 Event 삭제
- orphan Keyword / Person / Country 삭제
- Company 는 유지

즉 cleanup 로직은 단순 row delete 가 아니라,
PostgreSQL + Neo4j 정합성을 같이 보는 정리 작업이다.

이건 AI 스케줄러가 판단할 일이 아니라 backend 가 수행할 일이다.

---

## 11. 테스트 원칙

News backend 브랜치 테스트는 아래 기준을 따른다.

- 실 RSS 호출 0
- 실 본문 크롤링 0
- 실 LLM 호출 0
- 실 임베딩 모델 호출 0
- GraphBatch / ReportModel fixture 주입
- DB rollback 격리
- Neo4j 는 fake or test instance 분리

이미 있는 테스트:

- `POST /news/batch/save` 원자 저장 성공
- URL 중복 업서트
- URL -> `news_id` 해소 정확성
- graph 저장 실패 시 전체 실패 처리
- `POST /news/cleanup` 동작
- `GET /news/query/subject` / `shared` 조회 계약
- `GET /news/events/{event_id}/articles` 응답 계약

남은 작업에 대해 추가할 테스트:

- `POST /news/reports` 저장
- `GET /news/reports/{report_id}` 조회

중요:

- 이 브랜치는 “뉴스 분석 품질”을 테스트하는 곳이 아니다
- backend 가 저장/조회/정리를 일관되게 수행하는지만 본다

---

## 12. 팀원에게 넘길 구현 순서

추천 순서:

1. `news_reports` 모델과 AI `ReportModel` schema 를 먼저 대조
2. `POST /news/reports` 저장 service/repository 구현
3. `GET /news/reports/{report_id}` 구현
4. `GET /reports?agent_type=news` 연결 여부 결정
5. 필요 시 `DELETE /news/reports/{report_id}` 구현
6. `agent_reports` 인덱스 연결 여부 결정
7. fixture 기반 테스트 보강

이 순서가 가장 자연스럽다.
배치 저장/조회/cleanup 은 이미 들어와 있으므로, 이제 중심은 `news_reports` persistence 다.

---

## 13. 이번 브랜치에서 하지 않을 것

- 상위 supervisor 구현
- News 전용 stock resolver 제작
- News 전용 KIS 계층 제작
- AI 내부 추출/감성/임베딩 로직 수정
- PostgreSQL 에 그래프 테이블 생성
- frontend 렌더 구현

---

## 14. 한 줄 결론

News backend 는 이제 “기본 저장/조회 경계를 새로 만드는 단계”가 아니라,
**이미 구현된 기사/그래프/조회/cleanup 위에서 `news_reports` persistence 와 Supervisor 연계를 마무리하는 단계**로 보는 것이 맞다.
