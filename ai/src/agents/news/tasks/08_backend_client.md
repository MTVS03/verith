# TASK 08 — backend HTTP 클라이언트 (services/backend/*.py · nodes/save.py)

## 0. 개요
- **목적**: 배치 흐름의 마지막 단계(**저장**)와, 앞선 TASK들이 **인터페이스로만** 정의해 둔 **조회(Provider)** 를 실제 backend(:8000) HTTP 호출로 구현한다. 이 에이전트에서 **PostgreSQL·Neo4j에 닿는 유일한 경로**다(절대규칙 1: DB 드라이버·SQL·Cypher를 이 에이전트에 직접 쓰지 않고, 전부 backend HTTP로). 구체적으로 (1) 배치 산출물(분석된 `Article` 원본 + TASK 07의 `GraphBatch`)을 backend로 보내 PostgreSQL 저장 + Neo4j MERGE, (2) 병합(TASK 05)·중요도(TASK 06)가 주입받는 `RecentEventProvider`·`EventArticleStatsProvider`의 **실제 backend 구현**, (3) 질의(리포트) 흐름의 조회(`query_client`: 종목별 이벤트 importance순·multi-hop·이벤트별 기사 요약/감성 on-demand), (4) 7일 롤링 삭제 **트리거**를 담당한다.
- **선행 작업**:
  - TASK 01(schemas: `Article`, `Event`, `CandidateEvent`(TASK 05 추가), `EventArticleStats`(TASK 06 추가), `SubjectQueryResponse`·`EventWithArticles`·`SaveResponse`·`CleanupResponse`(response.py), `ArticleRef`·`SentimentGauge`).
  - TASK 05(`RecentEventProvider` Protocol + `CandidateEvent` 계약. **여기서 backend 구현**을 채운다. centroid 계산·유지는 backend 책임).
  - TASK 06(`EventArticleStatsProvider` Protocol + `EventArticleStats` 계약. **여기서 backend 구현**을 채운다).
  - TASK 07(`GraphBatch`(노드·관계 델타) + **정체성 규칙(§0.2 MERGE 계약)** + NewsRef `url` 키 규약. 저장 시 이 계약대로 MERGE하고 `url`→`news_id`를 해소).
  - TASK 02/03/04/05(저장 대상 `Article` 필드: `title/url/publisher/content/summary/sentiment/sentiment_score/embedding/published_at/event_id/analysis_completed`).
- **산출물(파일)**:
  - `config.py`(발췌 추가) — backend 접속 설정(`BACKEND_BASE_URL` + 타임아웃·재시도) + (잠정) 엔드포인트 경로. 하드코딩 금지의 귀착점. **엔드포인트·요청/응답 계약 확정은 `verith/docs/api_contract.md`(미확정, CLAUDE.md §8)** — 여기서는 잠정값 + 클라이언트 계약만.
  - `services/backend/__init__.py` — 클라이언트·provider 재노출.
  - `services/backend/client.py` — 공용 HTTP 계층(`BackendClient`): `_request()` 하나에 타임아웃·재시도·에러 처리 격리. httpx/requests 같은 HTTP 라이브러리는 **오직 이 파일**에만.
  - `services/backend/save_client.py` — 배치 저장(`save_batch(articles, graph_batch) -> SaveResponse`) + 7일 롤링 삭제 트리거(`request_cleanup() -> CleanupResponse`).
  - `services/backend/providers.py` — `BackendRecentEventProvider`(TASK 05 `RecentEventProvider` 구현), `BackendEventArticleStatsProvider`(TASK 06 `EventArticleStatsProvider` 구현). 배치 흐름이 주입받는 조회.
  - `services/backend/query_client.py` — 질의(리포트) 흐름 조회: 종목별 이벤트(importance순)·두 회사 공유 이벤트(multi-hop)·이벤트별 기사(요약/감성) on-demand. (query_spec §4의 ②③ backend HTTP)
  - `nodes/save.py` — 얇은 저장 노드: `state["articles"]`·`state["graph_batch"]`를 `save_client.save_batch`로 넘기고 결과를 반영.
- **범위 밖(주의)**:
  - **DB 모델 정의·마이그레이션·실제 SQL/Cypher·CASCADE 삭제 로직은 backend 소유**(`backend/db/models/news`, SCHEMA_SPEC.md §5). 이 에이전트는 **HTTP 요청만** 한다. 7일 168h 경과 판정·고아 노드(Keyword/Person/Country) 정리·Company 유지는 backend가 수행하고, 여기서는 **트리거만** 한다.
  - **centroid(이벤트 대표 벡터) 계산·갱신은 backend**(TASK 05 §3.4). provider는 backend가 계산해 준 centroid를 `CandidateEvent.embedding`으로 **읽어 반환만** 한다.
  - **importance 재계산은 하지 않는다**. importance는 이미 TASK 06이 계산해 TASK 07의 `GraphBatch` Event 노드 property에 실려 있으므로(신규·편입 모두), 저장은 그 값을 **persist만** 한다(이중 소스 방지, §2).
  - **감성 분포(게이지) 집계·저장 안 함**: Event에 감성 count를 저장하지 않는다(CLAUDE.md §5). 질의 시 backend가 **실시간 집계**해 `SentimentGauge`로 돌려준다 — 이 에이전트는 집계하지 않고 받기만 한다.
  - **질문 이해(①)·그래프 탐색 설계(②)·답변 생성(④)·HTML 렌더는 질의 흐름(별도, query_spec §4의 `query_understanding.py`/`graph_query.py`/TASK 09)**. TASK 08은 그 흐름이 쓰는 **backend 조회 HTTP 계약**만 제공한다(설계·오케스트레이션은 그쪽 소관).
  - **스케줄링(매시간 트리거)은 TASK 10**. TASK 08은 저장·삭제 **호출 함수**를 제공하고, 언제 부를지는 스케줄러가 정한다.

### 0.1 하위 의존성 (⚠️ 수정 시 영향 범위)
이 단계는 파이프라인과 backend 사이의 **HTTP 계약**을 구현한다. 아래를 바꾸면 backend·후속 TASK가 함께 영향받는다.

| 산출물 | 소비/연계 |
|---|---|
| `save_batch(articles, graph_batch)` 요청 형태 | backend 저장 API(api_contract.md), TASK 07(GraphBatch·NewsRef url키), TASK 10(스케줄러가 배치 실행) |
| `BackendRecentEventProvider` | TASK 05 `nodes/merge_event.py`(주입) — 인터페이스는 TASK 05 소유, 구현만 여기 |
| `BackendEventArticleStatsProvider` | TASK 06 `nodes/importance.py`(주입) — 인터페이스는 TASK 06 소유, 구현만 여기 |
| `query_client`(종목/공유이벤트/기사요약 조회) | TASK 09(리포트: `SubjectQueryResponse`→`ReportModel`), 질의 흐름(②③) |
| `request_cleanup()` | TASK 10(cleanup 스케줄러가 트리거), SCHEMA_SPEC §5(backend가 실제 삭제) |
| backend 접속·엔드포인트 설정(config) | api_contract.md(계약 확정), 배포 환경 |

## 1. 참고 문서
- `docs/sequence.md` §1(배치: … importance → 그래프 → `save_client.py` 저장 [HTTP]), §2(질의: `query_client.py`로 Neo4j 순회·PostgreSQL 요약 조회 [HTTP]), §3(삭제: cleanup_scheduler → services → backend [HTTP], backend가 CASCADE 삭제).
- `docs/pipeline_spec.md` §7(저장은 backend 경유: PostgreSQL 원본 + Neo4j 그래프, DB 직접 접근 금지·HTTP만), §8(Neo4j Event 중심·news_id 참조만), §10(7일 롤링 삭제), §11(질의: Neo4j 뼈대 → PostgreSQL 요약, importance순).
- `backend/db/models/news/SCHEMA_SPEC.md` §1(PostgreSQL news 컬럼: `event_id`·`embedding`(pgvector)·`sentiment`…), §3(Neo4j 노드·관계 = MERGE 상대), §5(삭제 CASCADE: 168h·고아 정리·Company 유지), §6(조회: importance순·multi-hop·news_id→요약/감성·감성 실시간 집계).
- `docs/erd.dbml` — PostgreSQL `news`(url unique = 1차 중복차단·저장 idempotency 근거, `event_id`), Neo4j 관계·`_import_note`(감성 count 미저장·조회 시 집계), 삭제 규칙.
- `docs/query_spec.md` §2(single/multi-hop), §3(news_id→요약·감성·출처·published_at, 감성 실시간 집계), §4(구현 위치: `services/backend/query_client.py`가 ②③ HTTP), §7(news는 DB 직접 접근 금지·backend 클라이언트로만).
- `CLAUDE.md` §2-1(**DB 직접 접근 금지 → 이 폴더가 유일 경로**), §2-2(nodes 얇게·로직은 services), §2-5(환각 금지: 저장 실패를 성공으로 위장하지 않음), §5(감성 count 미저장·7일 롤링·Company 유지), §7(외부 호출 타임아웃·재시도·예외 로깅·skip·설정값 하드코딩 금지), §8(**api_contract.md 미확정**, DB 모델은 backend 소유).
- TASK 01 `schemas/response.py`(`SubjectQueryResponse`/`EventWithArticles`/`SaveResponse`/`CleanupResponse`), `report.py`(`ArticleRef`/`SentimentGauge`), `event.py`(`Event`/`CandidateEvent`/`EventArticleStats`), `article.py`(`Article`).
- TASK 05 §3.4(`RecentEventProvider`·`CandidateEvent`·centroid는 backend 책임), TASK 06 §3.2-4(`EventArticleStatsProvider`·`EventArticleStats`), TASK 07 §0.2(정체성 규칙·NewsRef url키)·§3(GraphBatch).

## 2. 배경 (왜)
- **왜 backend 클라이언트가 유일한 DB 경로인가**: 절대규칙 1 — 이 에이전트(ai, :9000)는 PostgreSQL·Neo4j에 직접 붙지 않는다. DB 소유·모델·마이그레이션은 backend(:8000)에 있고(SCHEMA_SPEC 경계), 에이전트는 backend HTTP로만 저장·조회한다. 그래서 SQL·Cypher·드라이버가 이 에이전트 어디에도 없고, **오직 `services/backend/`** 에만 HTTP 호출이 모인다. 이렇게 하면 DB 스키마가 바뀌어도 에이전트는 HTTP 계약만 보면 되고, 보안·권한 경계가 backend에 일원화된다.
- **왜 HTTP 라이브러리를 `client.py` 한 곳에 격리하나**: 타임아웃·재시도·에러 변환·(공통) 인증 헤더를 한 곳(`_request`)에 두면, save/query/provider가 각자 재시도 로직을 복제하지 않는다(단일 책임, CLAUDE.md §7). HTTP 클라이언트 교체(requests↔httpx, 동기↔비동기)도 이 파일만 고치면 된다.
- **왜 두 저장소를 한 번의 `save_batch`로 묶나(원자성 계약)**: 한 배치의 산출물은 PostgreSQL 원본(news)과 Neo4j 그래프(GraphBatch)로 나뉘지만 **하나의 일관된·원자적 저장**이어야 한다. `save_batch`는 **하나의 배치를 원자 단위로 backend에 넘기는 계약**이며, `articles`와 `graph_batch`는 **같은 실행에서 나온 짝**이어야 한다(§3.3 ★). 특히 NewsRef가 `news_id`로 이어지려면 news가 먼저 저장돼 `news_id`가 생겨야 하는데, 서로 다른 배치의 articles/graph를 섞으면 url→news_id 해소가 어긋나 그래프가 존재하지 않는 기사를 가리키게 된다. 그래서 에이전트는 둘을 **함께** 넘기고, **url→news_id 해소와 두 저장소 반영 순서는 backend가** 책임진다(TASK 07이 NewsRef를 `url` 키로 둔 이유). 엔드포인트가 1개(트랜잭션)냐 2개(news→graph)냐는 backend 결정(api_contract.md)이며, 에이전트는 **`save_batch` 하나의 계약**만 본다. 어느 경우든 에이전트는 `news_id`를 만들지 않는다(환각 금지).
- **왜 `url` unique + MERGE로 저장이 idempotent인가**: 배치가 재실행되거나 같은 기사가 다시 들어와도 중복 저장되면 안 된다. PostgreSQL은 `url` UNIQUE(1차 중복차단, erd.dbml)로, Neo4j는 TASK 07 정체성 키 기준 **MERGE(upsert)** 로 멱등성을 확보한다. 그래서 save는 "insert or update"이지 맹목 insert가 아니다 — 이 계약을 backend에 명시적으로 요구한다.
- **왜 importance를 저장에서 다시 계산하지 않나(이중 소스 방지)**: importance는 TASK 06이 계산해 TASK 07의 `GraphBatch` Event 노드 property로 이미 실려 있다(신규는 full 노드, 편입은 canonical_id+importance 얇은 노드). 저장은 그 property를 MERGE로 반영만 하면 **신규·편입 이벤트 모두**에 importance가 반영된다. 저장이 importance를 또 계산·주입하면 소스가 둘이 되어 어긋난다. 그래서 `save_batch`는 `graph_batch`를 그대로 persist한다(계산 없음).
- **왜 감성 분포를 저장하지 않고 조회 시 받나**: Event에 감성 count를 저장하지 않는다(CLAUDE.md §5, erd.dbml). 저장은 기사별 `Article.sentiment`(원본)만 PostgreSQL에 넣고, **분포(긍/중/부)는 질의 시 backend가 실시간 집계**해 `SentimentGauge`로 돌려준다(하루 수백 건이라 충분). 그래서 이 에이전트는 게이지를 만들지 않고 `query_client`가 받기만 한다.
- **왜 Provider 인터페이스는 TASK 05/06이 정의하고 구현만 여기서 하나(의존성 방향)**: 병합·중요도 로직은 backend 없이 단위 테스트돼야 하므로, TASK 05/06은 `Protocol`만 정의하고 fake로 테스트했다. 실제 조회(Neo4j/PostgreSQL)는 절대규칙 1대로 backend HTTP라 **구현을 TASK 08이 채운다**. 인터페이스(계약) 소유는 소비자(TASK 05/06)에게, 구현은 backend 경계(TASK 08)에 두어 의존성 방향이 안쪽(도메인)→바깥(인프라)으로 흐른다.
- **왜 backend 미연결 시 provider가 예외 대신 degrade하나**: TASK 05 §3.4·TASK 06 §2가 "미주입/미연결에서도 파이프라인이 죽지 않는다"를 계약으로 뒀다(신규 이벤트는 정확, 편입은 근사). 그래서 backend provider도 HTTP 실패 시 **예외로 배치를 죽이지 않고 로깅 후 빈 결과(`[]`/`None`)로 degrade**한다 — 병합은 모든 기사를 신규로, importance는 배치 기사만으로 근사 계산. **트레이드오프**(backend가 불안정하면 일시적 과분할·근사 importance)를 감수하고 가용성을 택한다(CLAUDE.md §7 정신). 반면 **저장(`save_batch`) 실패는 degrade하지 않는다** — 데이터가 안 남는 진짜 실패이므로 `SaveResponse(ok=False)`로 정확히 보고하고 로깅한다(성공으로 위장 금지, §2-5).
- **왜 저장/삭제 트리거는 여기, 스케줄은 TASK 10인가**: "무엇을 어떻게 저장·삭제하는가"(HTTP 계약)는 backend 경계인 이 파일의 책임이고, "언제 매시간 도는가"는 스케줄러(TASK 10)의 책임이다. 7일 롤링 삭제도 여기선 `request_cleanup()` **호출**만 만들고, 실제 168h·CASCADE는 backend가, 트리거 타이밍은 스케줄러가 맡는다(관심사 분리, sequence §3).
- **DB 접근 금지의 귀착점**: 이 폴더 밖 어디에도 DB·HTTP-to-DB 호출이 없어야 한다. 노드·다른 서비스는 `services/backend/`만 통해 저장·조회한다.

## 3. 요구사항

### 3.1 `config.py` — backend 접속 설정 (하드코딩 금지)
1. **접속**: `BACKEND_BASE_URL: str`(예: `"http://localhost:8000"`). 배포 환경에 따라 바뀌므로 config·환경변수에서 읽는다(코드 하드코딩 금지).
2. **외부 호출 안전장치**: `BACKEND_TIMEOUT`(초), `BACKEND_MAX_RETRIES`, `BACKEND_RETRY_BACKOFF`(초). 모든 backend 호출에 적용(CLAUDE.md §7). 저장·조회·삭제 공통.
3. **엔드포인트 경로(잠정)**: `BACKEND_SAVE_PATH`·`BACKEND_CLEANUP_PATH`·`BACKEND_QUERY_SUBJECT_PATH`·`BACKEND_QUERY_SHARED_PATH`·`BACKEND_EVENT_ARTICLES_PATH`·`BACKEND_RECENT_EVENTS_PATH`·`BACKEND_EVENT_STATS_PATH` 등. **⚠️ 실제 경로·요청/응답 스키마는 `verith/docs/api_contract.md`에서 확정(미확정, CLAUDE.md §8)** — 여기서는 잠정값 + 주석으로 "api_contract.md에서 확정" 표기. 경로 문자열을 코드 여기저기 흩지 않고 config에 모은다.
4. (선택) `BACKEND_SAVE_BATCH_SIZE` — 저장 payload가 지나치게 클 때 분할 전송 상한(초기 폭주 방지). 미설정 시 한 번에.

### 3.2 `services/backend/client.py` — 공용 HTTP 계층
> **⚠️ HTTP 경계 규칙**: httpx/requests 등 HTTP 라이브러리는 **오직 이 파일**에서만 import한다. save/query/provider는 이 `BackendClient`만 쓴다. DB 드라이버·SQL·Cypher는 어디에도 없다(절대규칙 1).

1. **`BackendClient`**: `BACKEND_BASE_URL` 기준 세션/커넥션을 들고, `_request(method, path, json=None, params=None)` 하나로 모든 호출을 처리한다. **타임아웃·재시도(지수 backoff)·상태코드 검사·JSON 파싱**을 여기 격리한다(CLAUDE.md §7).
2. **에러 처리**: HTTP 오류(타임아웃·연결 실패·4xx/5xx)는 삼키지 말고 로깅하고, 호출측이 분기할 수 있도록 **정의된 예외(예: `BackendError`)로 변환**해 올린다(원시 라이브러리 예외를 그대로 흘리지 않음 — 상위 계층이 라이브러리에 결합되지 않게).
3. **부수효과 격리**: 이 파일은 순수 HTTP만. 도메인 로직(스키마 조립·판정)을 넣지 않는다.
4. **인증 헤더·공통 헤더(User-Agent 등)를 여기서 일괄 부착.** 인증 방식은 잠정 "내부망 전용" 전제로 미확정이나(SCHEMA_SPEC §7.1, CLAUDE.md 미확정), 쓰기·삭제 엔드포인트가 있으므로 **인증 헤더 주입 지점(예: `BACKEND_AUTH_TOKEN` config)을 `_request`에 미리 마련**해 둔다(토큰 도입 시 이 한 곳만 채우면 되게). 토큰 값은 하드코딩 금지 → config/환경변수. 확정 전에는 비워 두고 내부망 전제로 운용.

### 3.3 `services/backend/save_client.py` — 배치 저장 + 삭제 트리거
> **★ 원자성 계약**: `save_batch()`는 **하나의 배치(batch)를 원자적(atomic) 단위로 backend에 전달하는 계약**이다. `articles`와 `graph_batch`는 **반드시 동일한 배치에서 생성된 결과**여야 하며(같은 실행의 `state["articles"]`·`state["graph_batch"]`), backend는 이를 **하나의 저장 작업**으로 처리한다. 이 계약이 있어야 url→news_id 해소(§2)와 그래프-원본 정합이 보장된다. 서로 다른 배치의 산출물을 섞어 넘기지 않는다(정합 붕괴·부분 저장 방지).

1. **`save_batch(articles, graph_batch) -> SaveResponse`**:
   - 입력: 분석 완료된 `Article` 리스트(원본·요약·감성·임베딩·`event_id` 포함) + TASK 07의 `GraphBatch`(노드·관계 델타). **둘은 같은 배치에서 나온 짝**이다(위 원자성 계약).
   - PostgreSQL news 저장 + Neo4j 그래프 MERGE를 **backend에 요청**한다. **url→news_id 해소·두 저장소 반영 순서는 backend 책임**(§2). 에이전트는 `news_id`를 만들지 않는다.
   - **idempotency 요구**: `url` UNIQUE + 그래프 MERGE로 재실행에도 중복이 안 생기게(backend에 명시). importance는 `graph_batch` Event property로 반영(재계산 없음, §2).
   - 반환 `SaveResponse(ok, saved, message)`. 저장 실패는 **degrade하지 않고** `ok=False`로 정확히 보고 + 로깅(성공 위장 금지, §2-5).
   - **저장 대상 필드**(SCHEMA_SPEC §1): `title·content·summary·url·publisher·sentiment·sentiment_score·embedding·published_at·event_id(=canonical_id str, TASK 01 §3.2)·created_at`. `analysis_completed=False`(병합 skip)인 기사 취급 정책(저장 제외 or 원본만 저장)은 주석으로 명시하되 **감성 없는(None) 기사도 원본은 저장 가능**(분포 집계에서 None 제외는 조회 시).
2. **`request_cleanup() -> CleanupResponse`**: 7일 롤링 삭제를 backend에 **트리거**만 한다. 168h 경과 판정·CASCADE(Event 기사수 0이면 삭제·고아 Keyword/Person/Country 삭제·**Company 유지**)는 backend가 수행(SCHEMA_SPEC §5). 반환 `CleanupResponse(ok, deleted_articles, deleted_events, message)`. 호출 주체는 TASK 10 cleanup 스케줄러.
3. 저장·삭제 외 판단(집계·병합·중요도)을 여기 섞지 않는다(단일 책임). HTTP는 `BackendClient`로만.

### 3.4 `services/backend/providers.py` — 배치 조회 Provider (TASK 05/06 구현)
> 인터페이스(계약)는 TASK 05(`RecentEventProvider`)·TASK 06(`EventArticleStatsProvider`) 소유. 여기서는 그 **backend HTTP 구현**만 채운다. 두 노드(`merge_event`·`importance`)에 주입된다.

1. **`BackendRecentEventProvider`** — `get_recent_events(companies, within_days) -> list[CandidateEvent]`:
   - backend에 "동일 회사·최근 `within_days`일 이벤트"를 조회 요청(후보 축소는 인터페이스 계약, event_merge §5). 결과를 `CandidateEvent`(`canonical_id`·`companies`·`embedding`(centroid)·`event_time`)로 매핑.
   - **centroid는 backend가 계산·유지**한 값을 읽어 담기만 한다(TASK 05 §3.4). 여기서 centroid를 계산하지 않는다.
   - **HTTP 실패 시 degrade**: 로깅 후 `[]` 반환(backend 미연결에서도 병합이 죽지 않고 모든 기사가 신규 — TASK 05 §3.4). 예외로 배치를 죽이지 않는다.
2. **`BackendEventArticleStatsProvider`** — `get_event_article_stats(event_id) -> EventArticleStats | None`:
   - backend에 그 이벤트의 **누적 기사 통계**(이미 저장된 것)를 조회 요청. `EventArticleStats`(`article_count`·`publishers`(원자료, distinct 계약)·`sentiment_magnitude_sum`·`sentiment_count`·`updated_at`)로 매핑. 가중치는 agent가 적용하므로 backend는 원자료만 반환(TASK 06 §3.3).
   - **HTTP 실패/미존재 시 degrade**: 로깅 후 `None` 반환(편입 이벤트는 배치 기사만으로 근사, 신규는 영향 없음 — TASK 06 §2).
3. 두 provider 모두 조회 결과를 스키마로 매핑만 하고, 가중·판정·계산은 하지 않는다(그건 TASK 05/06 서비스). HTTP는 `BackendClient`로만.

### 3.5 `services/backend/query_client.py` — 질의(리포트) 흐름 조회
> query_spec §4의 ②③ backend HTTP. 리포트(TASK 09)가 소비할 조회만. 질문 이해(①)·답변 생성(④)·렌더는 질의 흐름 소관(범위 밖).

1. **`get_events_by_subject(companies, within_days) -> SubjectQueryResponse`**: single-hop(`(Company)-[:PARTICIPATES_IN]->(Event)`) 이벤트를 **importance 내림차순**으로 조회. 각 이벤트에 근거 기사(`ArticleRef`=**news_id**+summary+url) 소수 + **실시간 집계된 `SentimentGauge`** + `article_count`(총 건수)를 담아 `EventWithArticles` 리스트로. **`ArticleRef.news_id`가 있어야** ④ 답변생성이 근거 news_id 사슬(TASK 09 §0.2)을 만들 수 있다. **"없는 종목" vs "뉴스 0건"** 구분 위해 `subject_found` 채움(TASK 01 §3.4). 감성 분포는 backend가 집계(감성 None 제외).
2. **`get_shared_events(company_a, company_b, within_days) -> SubjectQueryResponse`**(또는 동등): multi-hop — 두 회사가 함께 `PARTICIPATES_IN`한 **공유 이벤트**(관계 질문 핵심, query_spec §2). importance순.
3. **`get_articles_by_event(event_id, limit) -> list[ArticleRef]`**: ③ 추가 근거 조회 — 한 이벤트(`event_id`=canonical_id)에 `HAS_NEWS`로 이어진 기사를 요약·감성·출처·published_at과 함께 `ArticleRef`(**news_id**+summary+url) 리스트로 조회(query_spec §3). **`limit`으로 개수를 제어**(Top-N 조정은 DTO 재배포 없이 이 인자로 — 정렬은 published_at desc 등, backend가 규칙 명시). ②의 `EventWithArticles.articles`(대표 소수, news_id 포함)로 일반 리포트 근거는 이미 닫히므로, 이 함수는 **대표 소수를 넘는 깊은 근거가 필요할 때만 on-demand로** 쓴다(§0.2 리뷰 지적을 이 분리로 닫음). **"대표 기사 조회"(get_events_by_subject)와 "근거 조회"(이 함수)를 분리**해 이벤트 DTO에 전체 news_id를 상시 싣지 않는다. bare news_id가 아니라 `ArticleRef`를 돌려주므로 id→기사 왕복이 없다.
4. 관련도(랭킹) 점수는 **미확정 → 잠정 importance순**(pipeline_spec §11, query_spec §6). 정렬 기준을 코드에 박지 말고 backend/후속 튜닝에 맞춰 둔다. HTTP는 `BackendClient`로만.

### 3.6 `nodes/save.py` — 저장 노드 (얇게)
1. `state["articles"]`(분석 완료)와 `state["graph_batch"]`(TASK 07)를 `save_client.save_batch`로 넘긴다. 노드는 순서만 담당하는 얇은 껍데기(CLAUDE.md §2-2). HTTP·매핑 로직은 `services/backend/`에.
2. **결과 반영**: `SaveResponse`를 로깅/`state`에 반영(예: `state["save_result"]`). `ok=False`면 실패를 명확히 남긴다(성공 위장 금지). 파이프라인(배치)은 다음 실행에서 재시도되므로 여기서 무리하게 되돌리지 않는다.
3. **실패 격리**: 저장 호출이 실패해도 예외로 스케줄러 루프 전체를 죽이지 않는다 — 로깅 후 `ok=False`로 통과(TASK 10이 다음 주기 재시도). 단 저장 실패를 성공으로 만들지 않는다.
4. 대상 0건(`articles` 없음·`graph_batch` 비었음)이면 예외 없이 통과(환각 금지: 없으면 없는 대로). backend를 부르지 않아도 된다.
5. backend를 직접(HTTP) 부르지 않는다 — `save_client`만 호출한다(절대규칙 1의 경계 유지).

## 4. 인터페이스 / 구현 규칙

> 아래는 확정 시그니처(초안). 함수명·반환 타입은 이대로 구현하되, 설정값은 `config.py`에서 읽는다. **엔드포인트·요청/응답 상세는 api_contract.md에서 확정**(미확정). 함수 본문(로직)은 비워 둔다.

```python
# config.py (발췌) — backend 접속 설정. 엔드포인트는 api_contract.md에서 확정(잠정값).
BACKEND_BASE_URL: str = "http://localhost:8000"   # 배포 환경별. env/config에서 읽음(하드코딩 금지)
BACKEND_TIMEOUT: float = 10.0                     # backend 호출 타임아웃(초)
BACKEND_MAX_RETRIES: int = 2                      # 재시도 횟수
BACKEND_RETRY_BACKOFF: float = 1.0                # 재시도 간 대기(초)
BACKEND_SAVE_BATCH_SIZE: int | None = None        # 저장 payload 분할 상한(None=한 번에)
# ⚠️ 잠정 경로 — verith/docs/api_contract.md에서 확정
BACKEND_SAVE_PATH: str = "/news/batch/save"
BACKEND_CLEANUP_PATH: str = "/news/cleanup"
BACKEND_RECENT_EVENTS_PATH: str = "/news/events/recent"     # 병합 후보(TASK 05)
BACKEND_EVENT_STATS_PATH: str = "/news/events/stats"        # 중요도 통계(TASK 06)
BACKEND_QUERY_SUBJECT_PATH: str = "/news/query/subject"     # 종목 single-hop
BACKEND_QUERY_SHARED_PATH: str = "/news/query/shared"       # 공유 이벤트 multi-hop
BACKEND_EVENT_ARTICLES_PATH: str = "/news/events/{event_id}/articles"   # 이벤트별 기사(요약/감성) on-demand, ?limit=N
```

```python
# services/backend/client.py — 공용 HTTP 계층
# ⚠️ httpx/requests는 오직 이 파일. DB 드라이버·SQL·Cypher 없음(절대규칙 1).
from __future__ import annotations
from typing import Any

class BackendError(Exception):
    """backend HTTP 실패를 감싸는 예외(원시 라이브러리 예외를 상위로 흘리지 않음)."""

class BackendClient:
    def __init__(self, base_url: str | None = None) -> None:
        """BACKEND_BASE_URL/타임아웃/재시도로 세션 구성."""
        ...
    def _request(self, method: str, path: str,
                 json: Any | None = None, params: dict | None = None) -> Any:
        """모든 backend 호출의 단일 경로. 타임아웃·재시도(backoff)·상태검사·JSON 파싱.
        실패 시 로깅 후 BackendError로 변환해 올린다."""
        ...
```

```python
# services/backend/save_client.py — 배치 저장 + 삭제 트리거
# ⚠️ DB 직접 접근 금지. url→news_id 해소·두 저장소 반영 순서는 backend 책임. HTTP는 BackendClient로만.
from __future__ import annotations
from schemas.article import Article
from schemas.graph import GraphBatch
from schemas.response import SaveResponse, CleanupResponse

def save_batch(articles: list[Article], graph_batch: GraphBatch) -> SaveResponse:
    """분석된 news 원본(PostgreSQL) + GraphBatch(Neo4j MERGE)를 backend에 저장.
    - url UNIQUE + 그래프 MERGE로 idempotent. importance는 graph_batch Event property로 반영(재계산 없음).
    - NewsRef는 url 키 → backend가 저장 시 news_id로 해소(TASK 07).
    - 저장 실패는 degrade하지 않고 SaveResponse(ok=False)로 보고 + 로깅(성공 위장 금지)."""
    ...

def request_cleanup() -> CleanupResponse:
    """7일 롤링 삭제 트리거만. 168h 판정·CASCADE(고아 정리·Company 유지)는 backend(SCHEMA_SPEC §5).
    호출 주체는 TASK 10 cleanup 스케줄러."""
    ...
```

```python
# services/backend/providers.py — 배치 조회 Provider (TASK 05/06 인터페이스의 backend 구현)
# ⚠️ 인터페이스 소유는 TASK 05/06. 여기는 HTTP 구현만. HTTP 실패 시 degrade(예외로 배치 안 죽임).
from __future__ import annotations
from schemas.event import CandidateEvent, EventArticleStats

class BackendRecentEventProvider:  # implements services.event_merge.RecentEventProvider (TASK 05)
    def get_recent_events(self, companies: list[str], within_days: int) -> list[CandidateEvent]:
        """동일 회사·최근 within_days 이벤트 조회 → CandidateEvent(centroid는 backend 계산값을 읽기만).
        HTTP 실패 시 로깅 후 [] (모든 기사 신규, TASK 05 §3.4)."""
        ...

class BackendEventArticleStatsProvider:  # implements services.importance.EventArticleStatsProvider (TASK 06)
    def get_event_article_stats(self, event_id: str) -> EventArticleStats | None:
        """이벤트 누적 기사 통계 조회(원자료: publishers distinct·감성 합/개수).
        HTTP 실패/미존재 시 로깅 후 None (편입은 배치만으로 근사, TASK 06 §2)."""
        ...
```

```python
# services/backend/query_client.py — 질의(리포트) 흐름 조회 (query_spec §4 ②③)
# ⚠️ 감성 분포는 backend가 실시간 집계해 반환(이 에이전트는 집계 안 함, CLAUDE.md §5).
from __future__ import annotations
from schemas.report import ArticleRef   # ArticleRef는 schemas/report.py 소유(단일 경로, TASK 01 §3.3)
from schemas.response import SubjectQueryResponse

def get_events_by_subject(companies: list[str], within_days: int) -> SubjectQueryResponse:
    """single-hop 종목 이벤트를 importance순으로. 이벤트별 ArticleRef 소수 + SentimentGauge(실시간 집계)
    + article_count. subject_found로 '없는 종목' vs '뉴스 0건' 구분."""
    ...

def get_shared_events(company_a: str, company_b: str, within_days: int) -> SubjectQueryResponse:
    """multi-hop — 두 회사가 함께 PARTICIPATES_IN한 공유 이벤트(관계 질문). importance순."""
    ...

def get_articles_by_event(event_id: str, limit: int) -> list[ArticleRef]:
    """이벤트(canonical_id)에 HAS_NEWS로 이어진 기사 → ArticleRef(news_id+summary+url).
    limit으로 개수 제어(Top-N은 인자로 조정). 대표 소수(EventWithArticles.articles) 밖
    깊은 근거가 필요할 때만 on-demand. 대표 기사 조회와 근거 조회를 분리(§3.5-3)."""
    ...
```

```python
# nodes/save.py — 얇은 저장 노드
# ⚠️ backend를 직접(HTTP) 부르지 않는다. save_client만 호출(절대규칙 1 경계).
from __future__ import annotations
import services.backend.save_client as save_client

def save_node(state: dict) -> dict:
    """state["articles"] + state["graph_batch"]를 save_client.save_batch로 저장.
    - SaveResponse를 state["save_result"]에 반영. ok=False면 실패를 명확히 로깅(성공 위장 금지).
    - 저장 실패해도 스케줄러 루프를 죽이지 않음(다음 주기 재시도). 대상 0건이면 예외 없이 통과.
    """
    ...
```

### 4.1 backend 오퍼레이션 요약 (절대규칙 1 — 유일 경로)
| 오퍼레이션 | 함수 | 방향 | backend 책임 |
|---|---|---|---|
| 배치 저장 | `save_client.save_batch(articles, graph_batch)` | 쓰기 | news upsert(url unique) + 그래프 MERGE + url→news_id 해소 + importance persist |
| 7일 롤링 삭제 | `save_client.request_cleanup()` | 쓰기 | 168h 판정·CASCADE·고아 정리·Company 유지 |
| 병합 후보 조회 | `BackendRecentEventProvider.get_recent_events` | 읽기 | 동일회사·최근N일 이벤트 + centroid 계산·유지 |
| 중요도 통계 조회 | `BackendEventArticleStatsProvider.get_event_article_stats` | 읽기 | 이벤트 누적 원자료(publishers·감성 합/개수) |
| 종목 이벤트(single-hop) | `query_client.get_events_by_subject` | 읽기 | importance순 + 감성 실시간 집계 |
| 공유 이벤트(multi-hop) | `query_client.get_shared_events` | 읽기 | 두 회사 공유 Event 순회 |
| 이벤트별 기사(근거) | `query_client.get_articles_by_event(event_id, limit)` | 읽기 | event_id→기사(요약/감성/출처), on-demand·대표 소수 밖 |

### 4.2 실패 처리 규칙 (degrade vs 정확 보고)
| 호출 | backend 실패 시 | 이유 |
|---|---|---|
| `save_batch` | **degrade 금지** → `SaveResponse(ok=False)` + 로깅 | 데이터 미저장은 진짜 실패(성공 위장 금지, §2-5). 다음 주기 재시도 |
| `request_cleanup` | `CleanupResponse(ok=False)` + 로깅 | 삭제 누락도 정확히 보고. 다음 주기 재시도 |
| `get_recent_events` | 로깅 후 `[]` (degrade) | 병합이 안 죽고 모든 기사 신규(TASK 05 §3.4) — 가용성 우선 |
| `get_event_article_stats` | 로깅 후 `None` (degrade) | 편입 importance는 배치만으로 근사(TASK 06 §2) |
| `query_client.*` | `BackendError` 전파(또는 빈 응답+`subject_found`) | 리포트가 "데이터 제한"으로 처리(TASK 09, 절대규칙 5) |

- 모든 호출은 `config`의 타임아웃·재시도 적용(CLAUDE.md §7). 원시 라이브러리 예외는 `BackendError`로 변환.
- **degrade는 조회(가용성 우선)에만**, 쓰기(저장·삭제)는 정확히 실패 보고. 이 구분을 지킨다.

## 5. 규칙·제약 (CLAUDE.md)
- **§2-1 DB 직접 접근 금지.** 이 폴더가 PostgreSQL·Neo4j에 닿는 **유일 경로**이며, 그마저도 backend HTTP다. SQL·Cypher·드라이버가 에이전트에 없다. HTTP 라이브러리는 `client.py`에만.
- **§2-2 nodes는 얇게, 로직은 services.** `nodes/save.py`는 `save_client`만 호출. HTTP·매핑·재시도는 `services/backend/`.
- **§2-5 환각 금지 / 정직 보고.** 저장 실패를 성공으로 위장하지 않는다(`ok=False`). `news_id`를 지어내지 않고 backend가 url로 해소. 조회 결과 없음은 `subject_found`·빈 결과로 정확히 전한다(리포트가 "데이터 제한").
- **§5 감성 count 미저장·7일 롤링·Company 유지.** 저장은 기사별 감성 원본만, 분포는 조회 시 backend 집계. 삭제는 backend CASCADE, Company 유지.
- **§7 외부 호출 타임아웃·재시도, 예외 로깅. 설정값 하드코딩 금지**(BASE_URL·타임아웃·재시도·엔드포인트는 config, 계약은 api_contract.md).
- **§8 미확정 존중.** api_contract.md(엔드포인트·요청/응답)는 미확정 → config 잠정값 + 주석. DB 모델은 backend 소유(SCHEMA_SPEC), 여기서 정의하지 않는다. 질의 관련도(랭킹)는 잠정 importance순.

## 6. 완료 조건 (DoD)
- [ ] `config.py`에 `BACKEND_BASE_URL`/`BACKEND_TIMEOUT`/`BACKEND_MAX_RETRIES`/`BACKEND_RETRY_BACKOFF`(+ 잠정 엔드포인트 경로, "api_contract.md 확정" 주석)가 정의됨. BASE_URL·경로 하드코딩 없음.
- [ ] `services/backend/client.py`가 **HTTP 라이브러리를 격리**하고, `_request`가 타임아웃·재시도(backoff)·상태검사·JSON 파싱을 처리하며 실패를 `BackendError`로 변환함. DB 드라이버·SQL·Cypher 없음.
- [ ] `save_client.save_batch(articles, graph_batch)`가 news(PostgreSQL) + `GraphBatch`(Neo4j MERGE)를 backend에 저장 요청하고 `SaveResponse`를 반환함. **url→news_id 해소·저장 순서는 backend 책임**, 에이전트는 news_id를 만들지 않음. importance는 graph_batch property로 반영(재계산 없음).
- [ ] **원자성 계약**: `save_batch`가 **같은 배치에서 생성된** `articles`·`graph_batch` 짝을 **하나의 저장 작업**으로 넘김(서로 다른 배치 산출물을 섞지 않음). 이 계약이 문서(§3.3 ★)와 `nodes/save.py`(같은 state의 둘을 함께 전달)에 반영됨.
- [ ] 저장이 **idempotent**(url unique + MERGE)임을 계약으로 요구하고, 저장 실패는 `ok=False`로 보고(성공 위장 없음).
- [ ] `save_client.request_cleanup()`이 7일 롤링 삭제를 **트리거만** 하고 `CleanupResponse`를 반환함(168h·CASCADE·Company 유지는 backend).
- [ ] `BackendRecentEventProvider`가 TASK 05 `RecentEventProvider`를 구현(동일회사·최근N일 → `CandidateEvent`, centroid는 backend 값 읽기만), **HTTP 실패 시 `[]` degrade**.
- [ ] `BackendEventArticleStatsProvider`가 TASK 06 `EventArticleStatsProvider`를 구현(누적 원자료 `EventArticleStats`, publishers는 원자료), **HTTP 실패/미존재 시 `None` degrade**.
- [ ] `query_client`가 종목 이벤트(importance순·single-hop)·공유 이벤트(multi-hop)·`get_articles_by_event(event_id, limit)`(이벤트별 기사 on-demand)를 조회하고, **감성 분포는 backend 실시간 집계 결과(`SentimentGauge`)를 받기만** 함. `subject_found`로 없는종목/0건 구분.
- [ ] `nodes/save.py`가 `save_client`만 호출하고 backend를 직접(HTTP) 부르지 않음. 대상 0건이면 예외 없이 통과. 저장 실패해도 스케줄러 루프를 죽이지 않음.
- [ ] **degrade는 조회에만, 쓰기(저장·삭제)는 정확히 실패 보고**(§4.2 표대로).
- [ ] 이 폴더 밖 어디에도 DB/HTTP-to-backend 호출이 없음(노드·타 서비스는 `services/backend/`만 사용).

## 7. 테스트
- **대상 파일**: `tests/test_backend_client.py`(**신규**), 필요 시 `tests/test_save_node.py`.
- **mock 전략**: 실제 backend·네트워크를 호출하지 않는다(CLAUDE.md: tests는 mock 기반). `BackendClient._request`(또는 HTTP 라이브러리)를 mock해 고정 응답/예외를 돌려준다.
  - **`client._request`**: 타임아웃·5xx·연결 실패 mock에서 재시도 후 `BackendError`로 변환되는지. 2xx JSON이 파싱되는지. 재시도 횟수가 `BACKEND_MAX_RETRIES`를 지키는지.
  - **`save_batch`**: (1) 성공 응답 → `SaveResponse(ok=True, saved=n)`, (2) 실패(5xx/타임아웃) → `ok=False`(예외를 삼켜 성공으로 만들지 않음, 로깅), (3) 요청 payload에 `articles`와 `graph_batch`가 모두 포함되고 **news_id를 에이전트가 만들지 않음**(url 기반)인지, (4) 대상 0건 처리.
  - **`request_cleanup`**: 성공 → `CleanupResponse(deleted_articles, deleted_events)`, 실패 → `ok=False`. 에이전트가 삭제 판정을 하지 않음(트리거만) 확인.
  - **`BackendRecentEventProvider`**: 정상 응답 → `CandidateEvent` 매핑(centroid 포함, 계산 안 함), **HTTP 실패 → `[]`**(degrade, 예외 전파 안 함). TASK 05 fake 자리에 이 구현을 끼워도 `decide_merge`가 동작하는지(계약 호환).
  - **`BackendEventArticleStatsProvider`**: 정상 → `EventArticleStats`(publishers 원자료·감성 합/개수), 미존재/실패 → `None`(degrade). TASK 06 `compute_importance`와 계약 호환.
  - **`query_client`**: `get_events_by_subject`가 importance순·`SentimentGauge`(집계는 backend가 준 값)·`subject_found`를 담아 `SubjectQueryResponse`로 매핑하는지. `get_shared_events`가 multi-hop 파라미터를 싣는지. `get_articles_by_event(event_id, limit)`가 `limit`을 싣고 `ArticleRef` 리스트로 매핑하는지. **에이전트가 감성 분포를 스스로 집계하지 않음** 확인.
  - **`save_node`**: `save_client.save_batch`만 호출(backend 직접 호출 없음), `ok=False`도 로깅 후 통과(루프 안 죽음), 0건 통과.
  - **DB 미접근**: 테스트/구현 어디에도 SQL·Cypher·DB 드라이버 import가 없음(절대규칙 1). HTTP는 `client.py`에만.
- **경계 케이스**: 저장 payload 0건, `graph_batch` 비었음, backend 연결 실패(전 오퍼레이션), `within_days` 경계, news_id 리스트 빈 값, 대용량 payload 분할(`BACKEND_SAVE_BATCH_SIZE`) 시 순서·완전성.
- **evals 연계**: 없음(통합 계약은 tests 레벨). 다만 저장→조회 왕복이 그래프 구축/질의 품질 evals의 전제이므로, 계약이 바뀌면 evals 픽스처(backend mock)도 갱신.
- 이 문서는 여러 TASK의 인터페이스(05/06 Provider, 07 GraphBatch, 01 응답 스키마)를 **구현**하므로, backend 계약(api_contract.md)이나 그 인터페이스가 바뀌면 **해당 TASK와 함께** 수정한다(계약 소유는 각 TASK, 구현은 여기).

## 8. 구현 계약 요약 (I/O)
| 입력 | 출력 | 호출 가능 | 호출 금지 | 실패 시 |
|---|---|---|---|---|
| `state["articles"]`·`graph_batch` / 조회 파라미터 | `SaveResponse` / Provider·`query_client` 응답(schemas) | `services/backend/client`(HTTP만) | SQL·Cypher·DB 드라이버, HTTP를 client 밖에서 | **쓰기=`ok=false` 정확 보고**, **읽기=degrade(`[]`/`None`)** (§4.2) |
