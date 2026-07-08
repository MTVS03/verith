# veriθ **news 에이전트** 데이터 모델 (backend 전달용)

> news 에이전트에 한정한 backend 구현 기준 문서. 백엔드 담당자가 **PostgreSQL 마이그레이션 · Neo4j 그래프 · `/news/*` 조회/저장 API**를 구현할 때 본다.
> 상세 원본: [`db/models/news/SCHEMA_SPEC.md`](models/news/SCHEMA_SPEC.md) · ai 계약 모델: `ai/src/agents/news/schemas/`.
> (technical 등 다른 에이전트의 테이블·Redis 캐시는 이 문서 범위 밖 — 각 에이전트 `docs/schema.md` 참조.)

## 저장소 구성

news 에이전트는 **두 저장소**만 쓴다. **Redis는 사용하지 않는다**(OHLCV 캐시는 technical 에이전트 소관).

| 저장소 | 담는 것 |
|---|---|
| **PostgreSQL** | 기사 원본(`news`) · 질의 리포트(`reports`) |
| **Neo4j** | Event 중심 지식그래프(Event·Company·Keyword·Person·Country·NewsRef + 관계) |

## 확정도 범례

| 표기 | 의미 |
|---|---|
| ✅ | **ai 코드·SCHEMA_SPEC으로 확정.** 그대로 구현하면 ai 계약과 맞물린다. |
| 🟡 | **제안/미확정.** 백엔드와 합의해 확정할 항목. |

- **경계 원칙:** ai news 에이전트(:9000)는 DB에 직접 접근하지 않는다. 모든 PostgreSQL·Neo4j 접근은 backend(:8000) `/news/*` HTTP API로만 이뤄진다. ai는 구조화 JSON을 반환하고 **backend가 저장·조회**한다. HTML은 ai가 만들지 않는다(출력은 JSON, frontend가 렌더).

---

## 1. 공통 기준 (Conventions)

모든 테이블·API가 공유하는 규약. 개별 테이블 정의보다 이 표가 우선한다.

| 기준 | 규칙 | 값/타입 | 비고 |
|---|---|---|---|
| **DB 분리** | 원본·리포트 = PostgreSQL / 지식그래프 = Neo4j | — | ✅ 두 저장소를 걸치는 참조(`news.event_id`→Neo4j `Event`, `NewsRef.news_id`→`news.id`)는 **DB FK가 아니라 앱이 보장하는 논리 링크** |
| **ID — 원본 기사** | 근거 추적 키. 정수 증가 | `BIGINT` PK (auto-increment) | ✅ ai `Article.id`=`news_id`. evidence 사슬의 원천이라 정수 고정 |
| **ID — 이벤트/리포트** | Event·리포트·소유 | `UUID` PK (uuid4) | ✅ `Event.canonical_id`·`report_id`·소유 컬럼. 시간정보를 ID에 넣지 않음(정렬은 `created_at`) |
| **회사 식별** | 종목코드가 아니라 **정규화된 회사명** | Neo4j `Company.key` = 이름 | ✅ news엔 ticker 컬럼이 없다. 회사는 그래프 `Company` 노드 이름으로 식별(정규화는 ai `utils.entity`) |
| **JSON 타입** | 중첩·가변 구조 저장 | `JSONB` | ✅ `report_json`·`evidence`. `JSON`이 아니라 `JSONB`(인덱싱) |
| **감성·의도 라벨** | **한글 계약값 그대로 저장** | `VARCHAR` | ✅ 감성 `긍정/중립/부정`, intent `관계/이유/요약/현황`. (technical의 영문 코드 규칙과 달리 news는 **한글 저장** — ai 계약값) |
| **시간 타입** | 모든 시각 컬럼 | `TIMESTAMPTZ` | ✅ KST(+09:00) aware 저장. naive timestamp 금지 |
| **created_at** | 저장 시각 | `TIMESTAMPTZ NOT NULL DEFAULT now()` | ✅ 시간순 정렬 기준. 모든 테이블 공통 |
| **원본 보존 · 환각 금지** | 수집 원본을 손실 없이 보존, 없는 값 지어내지 않음 | `news.content`·`summary`·`embedding` | ✅ 감성/중요도는 파생값, 원본은 그대로. 데이터 없으면 "데이터 제한"으로 둔다 |
| **7일 롤링 삭제** | `published_at` 168h 경과분 삭제 + 고아 정리 | cleanup 트리거 | ✅ Event 기사수 0이면 삭제, 고아 Keyword/Person/Country 삭제, **Company는 유지**(§2·§4) |
| **로그인 유저** | 인증된 사용자 | `users.id` UUID | 🟡 **테이블 정의는 이 문서 밖**(인증 설계 별도 문서). 리포트 귀속은 §4 |
| **익명 세션** | 비로그인 사용자 | `sessions.id` UUID (user_id NULL) | 🟡 **정의 외부.** 로그인 전 조회 이력을 세션에 귀속, 로그인 시 user로 이관(§4) |

---

## 2. Neo4j — Event 지식그래프

news의 그래프 저장소. ai는 배치마다 **"이번 델타"** (`GraphBatch` = 노드+관계)를 보내고, backend는 **정체성 키 기준 MERGE(upsert)**로 기존 그래프에 합친다. 감성 분포·기사 수는 노드에 저장하지 않고 **조회 시 실시간 집계**한다.

### 2.1 노드

| 노드(label) | 정체성 키(MERGE 기준) | 속성 | 비고 |
|---|---|---|---|
| `Event` | `key` = `canonical_id`(UUID) | `canonical_title`(신규 이벤트만), `importance`(float) | ✅ 중심 노드. 편입 이벤트 payload엔 title 없음(이름 고정) → 기존 값 유지. **`event_date`/기사수/감성은 노드에 없다**(§2.3) |
| `Company` | `key` = 정규화된 회사명 | `name` | ✅ 삭제되지 않음(Company 유지) |
| `Keyword` | `key` = 이름 | `name` | ✅ 고아 시 cleanup에서 삭제 |
| `Person` | `key` = 이름 | `name` | ✅ 고아 시 삭제 |
| `Country` | `key` = 이름 | `name` | ✅ 고아 시 삭제 |
| `Sector` | `key` = 이름 | `name` | 🟡 `BELONGS_TO` off라 **기본 미생성** |
| `NewsRef` | **저장 시 `key=url` → `news_id`로 해소** | `news_id`(int), `url`, `published_at`(ISO) | ✅ backend가 `news.url` upsert로 얻은 `news.id`로 해소(§2.4) |

> **권장 유니크 제약:** `Event.key`, `Company.key`, `Keyword.key`, `Person.key`, `Country.key`, `NewsRef.news_id`에 uniqueness constraint 생성(MERGE 정합·성능).

### 2.2 관계

| 관계 | 방향 | 비고 |
|---|---|---|
| `PARTICIPATES_IN` | `(Company)-[:PARTICIPATES_IN]->(Event)` | ✅ 여러 회사가 한 이벤트 공유 가능(질의 single/multi-hop의 핵심) |
| `HAS_NEWS` | `(Event)-[:HAS_NEWS]->(NewsRef)` | ✅ 본문은 PostgreSQL. NewsRef는 news_id 참조만 |
| `HAS_KEYWORD` | `(Event)-[:HAS_KEYWORD]->(Keyword)` | ✅ |
| `MENTIONS` | `(Event)-[:MENTIONS]->(Person)` | ✅ |
| `ABOUT` | `(Event)-[:ABOUT]->(Country)` | ✅ |
| `BELONGS_TO` | `(Company)-[:BELONGS_TO]->(Sector)` | 🟡 기본 off(회사↔섹터 매핑 부재, 3차·보류) |
| `RELATED_TO` | `(Company)-[:RELATED_TO]->(Company)` | 🟡 기본 off(공유이벤트 파생 규칙 미정) |

### 2.3 backend가 파생해야 하는 값 (노드에 없음)

`Event` 노드는 **시각·집계값을 담지 않는다.** 아래는 backend가 **member 기사(PostgreSQL)로 계산**한다:

| 파생값 | 계산 | 쓰이는 곳 |
|---|---|---|
| 이벤트 recency / `event_time` | member `news.published_at` 최대값 | `within_days` 필터, `CandidateEvent.event_time`(병합 후보) |
| centroid 임베딩 | member `news.embedding` 평균 | `/news/events/recent`(병합 후보 유사도, ai가 계산·backend는 제공만) |
| 감성 게이지(긍/중/부) | member `news.sentiment` 집계(`NULL` 제외) | 질의 응답 `gauge`·`overall_gauge`(실시간) |
| `article_count` | member `news` 총 건수 | 질의 응답 |

> Event↔기사 연결은 **두 경로**가 있다: PostgreSQL `news.event_id`(집계·SQL에 유리)와 Neo4j `Event-[:HAS_NEWS]->NewsRef`(그래프 순회). 감성 집계·기사수는 `news.event_id`로 SQL 집계하는 것이 자연스럽다.

### 2.4 저장 원자성 (★ 구현자 필독)

ai `save_batch`는 `{articles, graph_batch}`를 **한 요청**으로 보낸다. `graph_batch`의 `NewsRef`는 저장 전이라 `key=url`이다. backend는:
1. `articles`를 `news.url` **upsert**로 저장 → `url → news.id` 매핑을 얻는다.
2. 같은 요청의 `NewsRef`(및 `HAS_NEWS` 관계 끝점)를 그 `news_id`로 **해소**해 MERGE한다.
3. `news.event_id`는 `Article.event_id`(canonical_id)로 채운다.

ai는 `news_id`를 만들지 않는다(환각 금지). url→news_id 해소·두 저장소 반영은 backend 책임이다.

---

## 3. PostgreSQL 테이블

> 형식: `field | 타입 | example | 비고`.

### 3.1 `news` — 기사 원본

| field | 타입 | example | 비고 |
|---|---|---|---|
| id | BIGINT PK (auto) | `10432` | = ai `news_id`. 근거 추적 키 |
| title | TEXT NOT NULL | `"SK하이닉스, HBM3E 12단 양산"` | |
| content | TEXT | `"…본문…"` | 원본 보존. 크롤 실패 시 NULL |
| summary | TEXT | `"HBM3E 12단 양산 시작…"` | LLM(Qwen3) 통일 요약. 임베딩·병합 기준 |
| url | TEXT **UNIQUE** | `"https://.../article/123"` | 1차 중복 차단 키(upsert 대상) |
| publisher | VARCHAR | `"한국경제"` | importance 가중치 입력 |
| sentiment | VARCHAR | `"긍정"` | KR-FinBert 결과: `긍정`/`중립`/`부정`(한글 저장) |
| sentiment_score | REAL | `0.87` | KR-FinBert confidence 0~1. **importance 집계 입력**(없으면 NULL, 집계 제외) |
| embedding | vector (pgvector) | `[0.01, -0.02, …]` | arctic-embed summary 임베딩. Event centroid 계산 소스 |
| published_at | TIMESTAMPTZ | `"2026-07-06T09:12:00+09:00"` | 7일 롤링 삭제·recency 기준 |
| event_id | UUID NULL | `"7c9e…"` | = Neo4j `Event.canonical_id`. 병합 전 NULL. **논리 링크(DB FK 아님)** |
| created_at | TIMESTAMPTZ NOT NULL | `"2026-07-06T10:00:00+09:00"` | |

- **인덱스 권장:** `url`(UNIQUE), `event_id`(이벤트별 집계·조회), `published_at`(롤링 삭제).
- **pgvector:** `embedding` 저장에 확장 필요. deps에 아직 없으므로 도입 여부 확정 필요(🟡). 미도입 시 `float8[]`(ARRAY)로 저장하고 centroid는 앱에서 평균 계산.

### 3.2 `reports` — 질의 결과 리포트

| field | 타입 | example | 비고 |
|---|---|---|---|
| report_id | UUID PK | `"a1b2…"` | uuid4 |
| question | TEXT | `"삼성전자 최근 뉴스 요약해줘"` | 사용자 질문/종목 프리셋 |
| intent | VARCHAR | `"요약"` | `관계`/`이유`/`요약`/`현황`(한글, 검색·필터용) |
| answer_text | TEXT | `"최근 삼성전자는…"` | = `report_json.answer_text` 미리보기 사본 |
| evidence | JSONB | `[10432, 10455]` | 근거 news_id 목록 = `report_json.evidence_news_ids` 미러(역참조 질의용) |
| report_json | JSONB | `{ "subject": "...", "overall_gauge": {...}, "top_events": [...], "answer_text": "..." }` | **ai `ReportModel` 전체 = frontend 렌더 원본** |
| owner_user_id | UUID NULL | `"u_8f…"` | 조회 이력 귀속(§4). 로그인 소유 |
| owner_session_id | UUID NULL | `"s_2a…"` | 익명 세션 소유(§4) |
| created_at | TIMESTAMPTZ NOT NULL | `"2026-07-07T11:00:00+09:00"` | |

> **리포트 저장 엔드포인트는 현재 ai↔backend 계약(SCHEMA_SPEC §7)에 없다.** ai `run_query()`는 `report_json`을 supervisor에 반환만 하며, 이 테이블 영속화 여부·시점은 supervisor/backend 결정. 영속화 시 위 컬럼을 `report_json`에서 채운다.

---

## 4. 리포트 소유 (조회 이력 귀속) ✅ 요구 확정 / 🟡 FK 대상 외부

> **유저·세션 테이블 정의는 이 문서 범위 밖**(인증 설계 별도 문서). 다만 **조회 이력을 유저/세션에 귀속하는 요구는 확정**됐으므로 `reports`에 아래 소유 컬럼을 둔다. FK 대상(`users.id`·`sessions.id`)은 그 별도 문서가 정의한다.

| field | 타입 | example | 비고 |
|---|---|---|---|
| owner_user_id | UUID NULL | `"u_8f…"` | 로그인 사용자 소유. → `users.id`(외부 정의) |
| owner_session_id | UUID NULL | `"s_2a…"` | 익명 세션 소유. → `sessions.id`(외부 정의) |

- **둘 다 nullable.** 로그인 조회 = `owner_user_id`, 익명 조회 = `owner_session_id`. 로그인 승격 시 세션 귀속 이력을 user로 이관(백엔드 정책).
- **인덱스:** `(owner_user_id, created_at DESC)` — "내 리포트" 최신순.
- **ai 계약과 무관한 backend 소유 컬럼**이다(ai는 이 필드를 채우지 않는다 — backend가 요청 주체를 알고 저장 시 세팅).

---

## 5. `/news/*` 엔드포인트 (계약 요약)

상세 요청/응답 스키마는 [`SCHEMA_SPEC.md §7`](models/news/SCHEMA_SPEC.md), 모델은 ai `schemas/`. 저장소 매핑만 요약:

| 오퍼레이션 | 메서드·경로 | 저장소 |
|---|---|---|
| 배치 저장 | `POST /news/batch/save` | PostgreSQL(`news` upsert) + Neo4j(MERGE). 원자성 §2.4 |
| 7일 삭제 | `POST /news/cleanup` | PostgreSQL 삭제 + Neo4j CASCADE(§4·§2.3) |
| 병합 후보 | `GET /news/events/recent` | Neo4j(회사→이벤트) + PostgreSQL(centroid·event_time §2.3) |
| 중요도 통계 | `GET /news/events/stats` | PostgreSQL(`news.event_id` 집계) |
| 종목 이벤트(single-hop) | `GET /news/query/subject` | Neo4j(Company→Event) + PostgreSQL(gauge·기사·집계) |
| 공유 이벤트(multi-hop) | `GET /news/query/shared` | Neo4j(두 Company 공유 Event) + PostgreSQL |
| 이벤트별 기사(근거) | `GET /news/events/{event_id}/articles` | PostgreSQL(`news.event_id`, `ArticleRef` 반환) |

---

## 6. 백엔드 확정 필요 항목 (체크리스트)

1. ✅→구현 **`/news/*` 7개 엔드포인트** — SCHEMA_SPEC §7 계약대로. 현재 backend는 `/health`만 존재.
2. ✅ **리포트 소유 연결** — 조회 이력 귀속 확정. `reports`에 `owner_user_id`/`owner_session_id`(nullable) 구현(§4).
3. 🟡 **유저/세션 인증 설계(별도 문서)** — `users`·`sessions` 테이블·인증 프로토콜. §4 소유 컬럼의 FK 대상.
4. 🟡 **importance 재계산(cleanup)** — 삭제로 기사 집합이 바뀐 살아남은 Event의 importance 재계산 필요(SCHEMA_SPEC §5). 공식은 ai `tasks/06_importance.md`와 **단일 정의 공유** 필요 — 백엔드가 임의 공식으로 갈라지지 않도록 확정.
5. 🟡 **pgvector 확장·ANN 인덱스** — `news.embedding` 저장/유사 검색. 미도입 시 `float8[]` 폴백(§3.1).
6. 🟡 **인증·접근 통제** — 쓰기·삭제 엔드포인트(`/news/batch/save`·`/news/cleanup`)는 무인증이면 아무나 저장·삭제 유발. 외부 노출 시 내부 토큰 필수(SCHEMA_SPEC §7.1).
