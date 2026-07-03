# TASK 07 — 지식그래프 조립 (schemas/graph.py · services/graph_builder.py · nodes/graph_builder.py)

## 0. 개요
- **목적**: 배치 흐름의 여덟 번째 단계. importance(TASK 06)까지 끝나 각 기사에 `Article.event_id`가 배정되고 이벤트마다 `importance`가 매겨진 뒤, **이번 배치의 기사·이벤트·개체를 Neo4j 지식그래프의 노드·관계 구조로 조립**한다. 산출물은 backend가 저장할 수 있는 **in-memory 그래프 payload(`GraphBatch`)** 하나이며, `state["graph_batch"]`로 저장 단계(TASK 08)에 넘긴다. 그래프 중심 노드는 **Event**이고, 관계는 erd.dbml/SCHEMA_SPEC §3 그대로 `(Company)-[:PARTICIPATES_IN]->(Event)`, `(Event)-[:HAS_NEWS|HAS_KEYWORD|MENTIONS|ABOUT]->(…)` 이다. **이 단계는 그래프를 "조립"만 하고 "저장"하지 않는다** — 실제 Neo4j MERGE/쓰기는 TASK 08이 backend HTTP로 수행한다(절대규칙 1).
- **선행 작업**:
  - TASK 01(schemas: `Article`(`url`·`event_id`·`publisher`·엔티티는 `ExtractResult`), `Event`(`canonical_id`·`canonical_title`·`importance`·`companies`)). `schemas/graph.py`는 **TASK 01 §0에서 "TASK 07에서 정의"로 명시**되었으므로 이 문서가 신규로 만든다(TASK 01 수정 아님).
  - TASK 03(`ExtractResult`: `companies`·`people`·`industries`·`countries`·`keywords`. 이벤트에 붙일 개체의 출처. `state["extracts_by_url"]`로 기사와 짝지어 전달).
  - TASK 05(`Article.event_id` 배정 + 신규 `Event`를 `state["events_by_id"]`에 등록. 그래프의 이벤트·회사 골격).
  - TASK 06(`Event.importance` 채움 + `state["importance_by_event_id"]`(신규+편입 모두). Event 노드의 `importance` property 출처).
- **산출물(파일)**:
  - `config.py`(발췌 추가) — 그래프 조립 옵션(3차 보류 관계 토글: `GRAPH_ENABLE_BELONGS_TO`/`GRAPH_ENABLE_RELATED_TO`(기본 `False`, pipeline_spec §12) + NewsRef 참조 키 방식). 하드코딩 금지의 귀착점.
  - `schemas/graph.py`(**신규** — TASK 07 소유) — Neo4j 노드/관계 Pydantic 모델(`NodeLabel`·`RelType` Enum, `GraphNode`·`GraphRelationship`·`GraphBatch`). backend 저장 계약(payload)이자 조립 결과.
  - `services/graph_builder.py` — 순수 조립: event별 서브그래프 생성(`build_event_subgraph`) + 배치 전체 조립(`build_graph_batch`) + 노드 dedup. LLM·DB 없음.
  - `nodes/graph_builder.py` — 얇은 노드: `event_id`가 배정된 기사를 이벤트별로 묶어 `build_graph_batch`를 호출하고 `state["graph_batch"]`에 실는다.
- **범위 밖(주의)**:
  - **실제 Neo4j 저장(MERGE/CREATE)은 TASK 08**. 여기서는 backend가 upsert할 수 있는 payload(`GraphBatch`)만 만든다. Cypher·드라이버·backend HTTP를 이 단계에서 직접 부르지 않는다(절대규칙 1).
  - **기존 그래프 조회·병합은 backend(TASK 08)**. 그래프 빌더는 기존 그래프를 읽지 않는다. 이번 배치가 **추가/갱신할 노드·관계만** 기술하고, 기존과의 합치기는 backend가 **MERGE(upsert)** 로 처리한다(증분, event_merge §7 정신). 즉 이 단계는 "이번 배치 델타"만 만든다.
  - **감성 판정·분포 집계는 여기서 하지 않는다.** Event 노드에 감성 count/분포를 **저장하지 않는다**(조회 시 실시간 집계, erd.dbml/CLAUDE.md §5). `Article.sentiment`는 그래프 구조에 들어가지 않는다.
  - **importance 계산은 TASK 06**. 여기서는 이미 계산된 값을 Event property로 **소비만** 한다(재계산하지 않음).
  - **이벤트 배정·canonical 생성은 TASK 05**. 여기서는 `Article.event_id`·`Event.canonical_title`을 읽어 노드로 옮길 뿐, **이름을 바꾸지 않는다**(canonical 이름 고정, event_merge §6).
  - **7일 롤링 삭제·고아 노드(Keyword/Person/Country) 정리는 backend/scheduler(TASK 08/10)**. 이 단계는 삭제하지 않는다(추가/갱신만).
  - **`BELONGS_TO`(Sector)·`RELATED_TO`(Company↔Company)는 3차 기능(pipeline_spec §12)으로 이번 스코프에서 보류**. 이유는 §2(엔티티 매핑 부재·과결합 위험). config 토글로 두되 기본 비활성.
  - **news_id 부여는 backend(TASK 08)**. 그래프 빌드 시점엔 `Article.id`(=news_id)가 아직 없으므로 NewsRef는 **`url`(중복차단 키)로 참조**하고, TASK 08이 저장 시 news_id로 해소한다(§2).

### 0.1 하위 의존성 (⚠️ 수정 시 영향 범위)
이 단계는 분석 결과를 "그래프 구조"로 옮긴다. 아래 계약을 바꾸면 후속 TASK가 영향받는다.

| 산출물 | 소비하는 TASK |
|---|---|
| `state["graph_batch"]`(`GraphBatch`: 노드·관계 델타) | TASK 08(저장: backend HTTP로 Neo4j MERGE) |
| `schemas/graph.py`(`NodeLabel`/`RelType`/`GraphNode`/`GraphRelationship`/`GraphBatch`) | TASK 08(payload 계약), evals(그래프 구축 품질 축), 질의(TASK 09가 이 라벨·관계 타입으로 순회) |
| NewsRef 참조 키 규약(url → backend가 news_id로 해소) | TASK 08(저장 시 url↔news_id 매핑), 질의(HAS_NEWS로 근거 기사 추적) |
| Event 노드 property(`canonical_id`·`canonical_title`·`importance`) | TASK 08(저장), 09(importance순 정렬·TOP 선정), 질의(그래프 순회) |

### 0.2 정체성 규칙 (MERGE 계약) — ★가장 중요한 계약
> backend가 **MERGE(upsert)** 로 이번 배치 델타를 기존 그래프에 합치므로, "무엇이 같은 노드/관계인가"를 결정하는 **정체성 키**가 이 그래프의 핵심 계약이다. 아래 규칙을 **backend(TASK 08) MERGE·tests·질의(TASK 09) 순회가 모두 동일하게** 사용한다. 여기와 `schemas/graph.py`·erd.dbml/SCHEMA_SPEC §3이 어긋나면 노드 중복·관계 유실이 생기므로 이 표가 단일 기준(single source of truth)이다.

**노드 정체성 (`GraphNode.label` + `GraphNode.key` 로 MERGE)**

| 노드 라벨 | 정체성 키(`key`) | key 출처 | properties(값) | 비고 |
|---|---|---|---|---|
| `Event` | `canonical_id`(UUID) | TASK 05가 부여(난수 생성 아님·재사용) | `importance`; **신규만** `canonical_title` | 편입 이벤트는 `canonical_title` 미포함(이름 고정) |
| `Company` | 회사명(정규화 문자열) | `ExtractResult.companies` | `name`(=key) | 정규화는 최소(공백 trim 등)·규칙은 주석 |
| `Keyword` | 키워드 문자열 | `ExtractResult.keywords` | `name` | 빈/공백 제외 |
| `Person` | 인물명 | `ExtractResult.people` | `name` | |
| `Country` | 국가명 | `ExtractResult.countries` | `name` | |
| `Sector` | 산업명 | `ExtractResult.industries` | `name` | **3차·보류**(BELONGS_TO off면 미생성) |
| `NewsRef` | `str(url)`(1차 중복차단 UNIQUE 키) | `Article.url`(HttpUrl→str) | `url`·(선택)`published_at` | **news_id는 backend가 저장 시 url로 해소**(§2) |

**관계 정체성 (`type` + start 노드 정체성 + end 노드 정체성 으로 MERGE)**

| 관계 `type` | start (label, key) | end (label, key) | 유일성(중복 방지) |
|---|---|---|---|
| `PARTICIPATES_IN` | (`Company`, 회사명) | (`Event`, canonical_id) | `(type, start, end)` |
| `HAS_NEWS` | (`Event`, canonical_id) | (`NewsRef`, url) | `(type, start, end)` |
| `HAS_KEYWORD` | (`Event`, canonical_id) | (`Keyword`, 키워드) | `(type, start, end)` |
| `MENTIONS` | (`Event`, canonical_id) | (`Person`, 인물명) | `(type, start, end)` |
| `ABOUT` | (`Event`, canonical_id) | (`Country`, 국가명) | `(type, start, end)` |
| `BELONGS_TO` | (`Company`, 회사명) | (`Sector`, 산업명) | `(type, start, end)` — **3차·보류** |
| `RELATED_TO` | (`Company`, 회사명) | (`Company`, 회사명) | `(type, start, end)` — **3차·보류** |

- **관계는 식별 property가 없다**: 위 관계들은 방향·양끝 노드만으로 유일하다. 그래서 정체성 = **`(type, start_label, start_key, end_label, end_key)`** 이며, 같은 삼중쌍은 MERGE로 항상 1개로 수렴한다(배치 내 dedup도 이 키로 한다). 관계에 property를 추가하려면 이 표부터 갱신한다.
- **key는 안정적이어야 한다**: Event는 UUID(TASK 05 부여)라 배치·재실행에도 불변. 개체는 이름이 곧 key이므로 **이름 정규화 규칙이 곧 정체성**이다 — 정규화가 흔들리면 같은 회사가 다른 노드로 갈라진다. 그래서 정규화는 **TASK 05 `company_overlap`과 동일한 공유 유틸 `normalize_entity_name`(결정적·최소: 앞뒤/중복 공백 정리 + `㈜`/`(주)`/`（주）` 제거)** 로 통일한다. 복잡한 별칭·오타 canonical(`삼전`→`삼성전자`)은 질의측 Dictionary First가 담당하고, 그래프 빌더는 이 최소 정규화만 한다(같은 함수를 05·07이 공유해 병합 신호와 노드 key가 어긋나지 않게).
- **NewsRef만 2단계 정체성**: 그래프 빌드 시점 key=`url`, 저장 후 backend가 `news_id`로 해소한다(§2). 질의(HAS_NEWS로 근거 기사 추적)는 backend가 해소한 news_id를 쓴다. url↔news_id 매핑 계약은 TASK 08에서 확정한다.

## 1. 참고 문서
- `docs/erd.dbml` — Neo4j Event 중심 구조(Event: `id`(canonical)·`canonical_title`·`importance`), 관계 목록(`PARTICIPATES_IN`/`HAS_NEWS`/`HAS_KEYWORD`/`MENTIONS`/`ABOUT`/`BELONGS_TO`/`RELATED_TO`), NewsRef는 `news_id` 참조만·본문은 PostgreSQL, **감성 count 저장 안 함(조회 시 집계)**, 삭제 CASCADE(Company 유지).
- `backend/db/models/news/SCHEMA_SPEC.md` §3(Neo4j 노드·관계 명세 = 저장 계약의 backend측 상대), §5(삭제 규칙은 backend), §6(질의: importance순 조회·multi-hop). erd.dbml과 1:1 대응.
- `docs/pipeline_spec.md` §8(지식 그래프: Event 중심, `Company-PARTICIPATES_IN-Event`, 여러 회사가 한 이벤트 공유, Neo4j엔 news_id 참조만, Event에 importance 보관), §7(저장은 backend 경유), §10(7일 롤링은 backend), §12(단계적 구현: `RELATED_TO`·2단계 질의는 3차).
- `docs/query_spec.md` §2(그래프 순회: single-hop `(Company)-[:PARTICIPATES_IN]->(Event)`, multi-hop = 두 회사의 공유 Event, HAS_NEWS로 근거 기사 추적) — 이 단계가 만든 라벨·관계를 질의가 그대로 순회한다.
- `docs/sequence.md` §1(배치 시퀀스: importance → 그래프 → `save_client.py` 저장). §3(삭제 흐름은 backend).
- `docs/event_merge.md` §6(canonical 이름 고정: 편입 시 이름 안 바꿈), §7(증분: 전체 재구성 아님 → backend MERGE로 델타만 합침).
- `CLAUDE.md` §2-1(DB 직접 접근 금지 → payload만, 저장은 TASK 08), §2-2(nodes 얇게·로직은 services), §2-4(감성·점수는 전용 모델·계산 → 그래프에 감성 판정/분포를 만들지 않음), §2-5(환각 금지: 없는 관계를 지어내지 않음), §5(감성 count 미저장·이름 고정·7일 롤링), §7(코딩 컨벤션: 예외 로깅·skip·설정값 하드코딩 금지), §8(미확정 존중).
- TASK 01 §0(“`schemas/graph.py`는 TASK 07에서 정의”), `schemas/event.py`(`Event`), `schemas/article.py`(`Article`·`ExtractResult`).
- TASK 05 §3.6(`Article.event_id`·`state["events_by_id"]`), TASK 06 §3.4(`state["importance_by_event_id"]`: 신규+편입 모두).

## 2. 배경 (왜)
- **왜 "조립"과 "저장"을 나누나**: Neo4j 쓰기는 backend HTTP로만 한다(절대규칙 1). 그래서 이 단계는 **무엇을 저장할지(노드·관계)를 순수하게 기술한 payload**만 만들고, 실제 MERGE/CREATE는 TASK 08이 한다. 이렇게 나누면 (1) 그래프 조립 로직을 backend 없이 단위 테스트할 수 있고, (2) 절대규칙 1(DB 미접근)을 자연히 지키며, (3) 저장 방식(Cypher·배치 크기·트랜잭션)이 바뀌어도 조립 계약은 안 흔들린다.
- **왜 Event가 중심 노드인가**: 여론·사건은 "이벤트" 단위로 묶여야 종목별 흐름·TOP 이슈·관계 질문(두 회사의 공유 이벤트)에 답할 수 있다(pipeline_spec §8, query_spec §2). 그래서 회사·키워드·인물·국가·기사(NewsRef)는 **Event를 중심으로** 연결한다. `PARTICIPATES_IN`만 Company→Event 방향이고 나머지 개체 관계는 Event→개체 방향이다(erd.dbml).
- **왜 이번 배치 "델타"만 만들고 backend가 MERGE하나(증분)**: 매시간 전체 그래프를 다시 그리면 노드가 중복되고 ID·이름이 흔들린다(event_merge §7). 그래서 그래프 빌더는 이번 배치가 **추가/갱신할 노드·관계만** 기술하고, backend가 **MERGE(정체성 키 기준 upsert)** 로 기존 그래프에 합친다. 같은 회사가 여러 이벤트·여러 배치에 나와도 Company 노드는 하나로 수렴한다(관계만 늘어난다). 그래서 그래프 빌더는 기존 그래프를 조회하지 않는다(조회·상태 유지는 backend 소유).
- **왜 노드에 "정체성 키(key)"를 명시하나**: backend가 MERGE하려면 "무엇이 같은 노드인가"의 키가 필요하다. **Event=`canonical_id`(UUID, TASK 05가 부여), 개체(Company/Keyword/Person/Country/Sector)=이름 문자열, NewsRef=`url`**. 그래프 빌더는 이 키로 배치 내 노드를 먼저 dedup하고, backend는 같은 키를 MERGE 키로 써서 기존과 합친다. 키를 payload에 못박아 두면 "어느 property로 MERGE할지"를 backend가 추측하지 않는다.
- **왜 NewsRef를 news_id가 아니라 url로 참조하나**: `news_id`(=`Article.id`)는 **저장 시 backend가 부여**한다(erd.dbml PostgreSQL `id bigint increment`). 그래프 빌드 시점(저장 전)엔 아직 없다. 그래서 NewsRef의 정체성·HAS_NEWS 참조는 **`url`(1차 중복차단 UNIQUE 키)로 두고**, TASK 08이 news를 저장하며 얻은 news_id로 **해소**한다(erd.dbml: Neo4j엔 news_id 참조만, 본문은 PostgreSQL). url을 쓰는 이유는 배치 내에서 언제나 있고 유일하기 때문이다(환각 금지: 없는 id를 지어내지 않는다).
- **왜 개체를 이벤트의 "소속 기사"에서 모으나(union)**: 한 이벤트에는 여러 기사가 편입될 수 있고, 각 기사의 `ExtractResult`가 회사·인물·국가·키워드를 준다. 이벤트의 개체는 **그 이벤트에 배정된 이번 배치 기사들의 엔티티 합집합**으로 구성한다(편입 기사의 개체도 반영). `Event.companies`는 신규 이벤트의 canonical 회사지만, 관계는 member 기사 union으로 만들어야 편입까지 포함된다. **오직 추출된 개체만** 넣는다(없는 개체를 지어내지 않음, CLAUDE.md §2-5).
- **왜 편입(기존) 이벤트도 그래프에 넣되 이름은 안 바꾸나**: 이번 배치의 편입 기사도 `event_id`를 가지므로 그 이벤트에 **새 HAS_NEWS·새 개체 관계**가 생긴다. 그래서 편입 이벤트도 그래프 델타 대상이다. 다만 편입 이벤트는 `state["events_by_id"]`에 없을 수 있다(신규만 등록, TASK 05 §3.6). 이 경우 Event 노드는 **`canonical_id` + 갱신된 `importance`만** 실어 MERGE하고 **`canonical_title`은 payload에 넣지 않는다**(backend에 이미 있음, 이름 고정 event_merge §6). 신규 이벤트는 `canonical_title`까지 실은 full 노드다.
- **왜 감성을 그래프에 넣지 않나**: 감성 판정은 전용 모델(TASK 04)이 이미 했고, 감성 **분포(긍/중/부 count)** 는 Event에 저장하지 않고 조회 시 실시간 집계한다(erd.dbml/CLAUDE.md §5, 하루 수백 건이라 충분). 그래프에 감성을 박아 두면 이중 소스가 되고 롤링 삭제 때 어긋난다. 그래서 이 단계는 구조(노드·관계)만 만들고 감성 신호를 넣지 않는다.
- **왜 `BELONGS_TO`·`RELATED_TO`는 이번에 보류하나(3차)**: (1) `BELONGS_TO`(Company→Sector)는 **어느 회사가 어느 산업인지의 매핑이 추출에 없다** — `ExtractResult.companies`와 `industries`는 각각 평면 리스트라 회사↔섹터를 이으려면 근거 없는 추정(같은 기사의 회사 × 산업 전조합)이 필요하고 이는 환각·과결합이다(CLAUDE.md §2-5). (2) `RELATED_TO`(Company↔Company)는 pipeline_spec §12에서 **3차**로 명시됐고 "같은 이벤트 공유에서 파생"이라 별도 규칙이 필요하다. 두 관계는 근거 있는 매핑 규칙이 정해질 때 켠다. 그래서 `config` 토글(기본 `False`)로 두고 이번 스코프에선 만들지 않는다.
- **왜 결정적(deterministic)이어야 하나**: 같은 배치 입력이면 항상 같은 `GraphBatch`가 나와야 재현·테스트·evals가 가능하다. 그래프 빌더는 **난수·시간·LLM·UUID 생성이 없다**(canonical_id는 TASK 05가 이미 부여). 노드·관계는 **정렬된 순서**로 방출해 dedup·비교가 안정적이게 한다.
- **DB 접근 금지**: 조립은 순수 매핑만. 조회·MERGE·저장은 backend HTTP(TASK 08) (CLAUDE.md §2-1).

## 3. 요구사항

### 3.1 `config.py` — 그래프 조립 옵션 (하드코딩 금지)
1. **3차 보류 관계 토글**: `GRAPH_ENABLE_BELONGS_TO: bool = False`, `GRAPH_ENABLE_RELATED_TO: bool = False`. pipeline_spec §12(3차) + §2(매핑 부재). 기본 비활성이며, 근거 규칙 확정 시 켠다. **주석으로 "3차·보류" 명시.**
2. **NewsRef 참조 키 방식**: `GRAPH_NEWSREF_KEY: str = "url"`(빌드 시점엔 news_id 미부여 → url로 참조, backend가 저장 시 news_id 해소). 문자열 모드로 두어 향후 다른 키(예: content hash)로 교체할 여지를 남긴다.
3. 관계 타입 문자열(`PARTICIPATES_IN` 등)·노드 라벨은 **`schemas/graph.py`의 Enum**에 두고 config에 흩지 않는다(계약은 스키마, 정책값만 config). config에는 위 토글·키 방식만.

### 3.2 `schemas/graph.py` — 그래프 노드/관계 모델 (신규, TASK 07 소유)
> Neo4j 구조를 표현하는 Pydantic 모델. backend(TASK 08)가 저장할 payload 계약이자 그래프 빌더의 출력 타입. erd.dbml/SCHEMA_SPEC §3과 1:1 대응한다.

1. **`NodeLabel`(str Enum)**: `EVENT="Event"`, `COMPANY="Company"`, `KEYWORD="Keyword"`, `PERSON="Person"`, `COUNTRY="Country"`, `SECTOR="Sector"`, `NEWS_REF="NewsRef"`. erd.dbml 노드 라벨 그대로.
2. **`RelType`(str Enum)**: `PARTICIPATES_IN`(Company→Event), `HAS_NEWS`(Event→NewsRef), `HAS_KEYWORD`(Event→Keyword), `MENTIONS`(Event→Person), `ABOUT`(Event→Country), `BELONGS_TO`(Company→Sector, 3차), `RELATED_TO`(Company→Company, 3차). erd.dbml 관계 그대로.
3. **`GraphNode`**: `label: NodeLabel`, `key: str`(MERGE 정체성 키 — Event=canonical_id, 개체=이름, NewsRef=url), `properties: dict[str, Any]`(Event=`canonical_title`·`importance`; NewsRef=`url`·(선택)`published_at`; 개체=`name`). **감성 count/분포 property를 두지 않는다**(CLAUDE.md §5).
4. **`GraphRelationship`**: `type: RelType`, `start_label`/`start_key`, `end_label`/`end_key`, `properties: dict[str, Any]`(기본 빈 dict). 방향은 erd.dbml 그대로(예: PARTICIPATES_IN은 start=Company, end=Event).
5. **`GraphBatch`**: `nodes: list[GraphNode]`, `relationships: list[GraphRelationship]`. **이번 배치가 추가/갱신할 델타**. backend는 `key` 기준 MERGE(upsert)로 기존 그래프에 합친다. docstring에 "델타·MERGE 계약·감성 미포함·NewsRef는 url키(backend가 news_id 해소)"를 남긴다.
6. Pydantic v2. `properties`의 값은 JSON 직렬화 가능한 타입만(backend HTTP 계약). `datetime`은 backend 합의 포맷(ISO8601 문자열 권장)으로 넣거나 backend 직렬화에 맡긴다 — 주석으로 표기.

### 3.3 `services/graph_builder.py` — 그래프 조립 서비스 (순수·결정적)
> **⚠️ 조립 경계 규칙**: 그래프 빌더는 **입력(기사·이벤트·importance) → 출력(`GraphBatch`)** 의 순수 함수다. LLM(`services/llm.py`)·감성 모델·backend/DB를 호출하지 않는다(절대규칙 1). 기존 그래프를 읽지 않고 이번 배치 델타만 만든다(합치기는 backend MERGE).

1. **`event_node(event, importance) -> GraphNode`**: Event 노드 생성. `key=canonical_id`, `properties={canonical_title, importance}`. **편입(기존) 이벤트로 `event`가 없을 때는 §3.4-4의 규칙대로 canonical_title 없이 canonical_id+importance만** 담는 얇은 노드를 만든다(이름 고정). importance는 `state["importance_by_event_id"]` 우선, 없으면 `Event.importance`.
2. **`entity_nodes_and_rels(event_id, articles) -> tuple[list[GraphNode], list[GraphRelationship]]`**: 한 이벤트의 개체 서브그래프. 그 이벤트에 배정된 배치 기사들의 `ExtractResult`에서:
   - **회사** → `Company` 노드 + `(Company)-[:PARTICIPATES_IN]->(Event)`.
   - **키워드** → `Keyword` 노드 + `(Event)-[:HAS_KEYWORD]->(Keyword)`.
   - **인물** → `Person` 노드 + `(Event)-[:MENTIONS]->(Person)`.
   - **국가** → `Country` 노드 + `(Event)-[:ABOUT]->(Country)`.
   - 각 개체는 **member 기사 union**으로 모으고 이름 기준 distinct(같은 회사가 이벤트 내 여러 기사에 나와도 관계 1개). 빈/공백 이름은 제외(환각 금지). `BELONGS_TO`·`RELATED_TO`는 config 토글이 켜진 경우에만(기본 미생성).
3. **`news_nodes_and_rels(event_id, articles) -> tuple[list[GraphNode], list[GraphRelationship]]`**: 그 이벤트 기사마다 `NewsRef` 노드(`key=str(article.url)` — `Article.url`이 `HttpUrl`이므로 **문자열로 변환해** 키·property 일관 유지, `properties={url, (선택)published_at}`) + `(Event)-[:HAS_NEWS]->(NewsRef)`. **본문·요약·감성은 넣지 않는다**(PostgreSQL 소유). news_id는 저장 시 backend 해소(§2).
4. **`build_event_subgraph(event_id, event, articles, importance) -> tuple[list[GraphNode], list[GraphRelationship]]`**: 위 셋을 합쳐 한 이벤트의 노드·관계를 만든다.
5. **`build_graph_batch(articles, extracts_by_url, events_by_id, importance_by_event_id) -> GraphBatch`**:
   - `event_id`가 배정된 기사만 대상(병합 통과, TASK 05). **이벤트별로 묶어** 각 이벤트에 `build_event_subgraph`.
   - 신규 이벤트는 `events_by_id`에서 `Event`(full 노드), 편입 이벤트는 `events_by_id`에 없으면 얇은 노드(§3.4-4).
   - **배치 전체에서 노드를 `(label, key)`로 dedup**(여러 이벤트에 공유되는 Company·Country 등은 노드 1개, 관계는 각각). 관계도 `(type,start_key,end_key)`로 dedup. **정렬된 순서로 방출**(결정성).
   - 반환은 `GraphBatch(nodes, relationships)`.
6. **부수효과·판정 없음**: 저장·DB·모델 호출 없음(CLAUDE.md §2-1). 감성·importance·병합을 여기서 계산하지 않는다(소비만). `state` 갱신은 노드가 한다.

### 3.4 `nodes/graph_builder.py` — 그래프 노드 (얇게)
1. `state["articles"]` 중 **`event_id`가 배정된 기사**(= 병합 통과)를 대상으로, `state["extracts_by_url"]`·`state["events_by_id"]`·`state["importance_by_event_id"]`를 넘겨 `graph_builder.build_graph_batch`를 호출한다. 노드는 순서만 담당하는 얇은 껍데기(CLAUDE.md §2-2).
2. **결과 반영**: `state["graph_batch"] = batch`(TASK 08이 backend로 MERGE 저장). 노드는 backend를 직접 호출하지 않는다(절대규칙 1).
3. **편입 이벤트 처리**: 이번 배치 기사들의 `event_id` 중 `events_by_id`에 없는 것(편입)도 그래프 델타에 포함된다(§3.3-5). 노드는 이를 걸러내지 않는다(HAS_NEWS·개체 관계가 기존 이벤트에도 붙어야 함).
4. **얇은 이벤트 노드 규칙**: `events_by_id`에 없는 편입 이벤트는 `build_graph_batch` 내부에서 canonical_id+importance만의 얇은 Event 노드로 만들어진다(이름 미변경). 노드는 이 규칙을 서비스에 위임한다.
5. **실패 격리**: 한 이벤트의 서브그래프 조립이 실패해도 예외로 파이프라인을 죽이지 않는다. 로깅 후 그 이벤트만 skip(그래프에서 누락), 나머지 계속(CLAUDE.md §7).
6. **조립 로직을 노드에 두지 않는다**: 노드는 `services/graph_builder.py`만 호출한다. 노드·관계 생성·dedup은 서비스에.
7. 대상(`event_id` 배정 기사) 0건이면 예외 없이 **빈 `GraphBatch`** 를 `state["graph_batch"]`에 넣고 통과(환각 금지: 없으면 없는 대로 — CLAUDE.md §2-5). 후속·리포트가 "데이터 제한"으로 처리한다.

## 4. 인터페이스 / 구현 규칙

> 아래는 확정 시그니처(초안). 함수명·반환 타입은 이대로 구현하되, 설정값은 `config.py`에서 읽는다. 함수 본문(로직)은 비워 둔다.

```python
# config.py (발췌) — 그래프 조립 옵션. 값은 정책값(주석 표기).
GRAPH_ENABLE_BELONGS_TO: bool = False   # (Company)-[:BELONGS_TO]->(Sector) — 3차·보류(회사↔산업 매핑 부재, pipeline_spec §12)
GRAPH_ENABLE_RELATED_TO: bool = False   # (Company)-[:RELATED_TO]->(Company) — 3차·보류(공유이벤트 파생 규칙 미정)
GRAPH_NEWSREF_KEY: str = "url"          # NewsRef 참조 키. 빌드 시점 news_id 미부여 → url, backend가 저장 시 news_id 해소
```

```python
# schemas/graph.py — Neo4j 노드/관계 모델(신규, TASK 07 소유). erd.dbml/SCHEMA_SPEC §3과 1:1.
from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field

class NodeLabel(str, Enum):
    EVENT = "Event"; COMPANY = "Company"; KEYWORD = "Keyword"
    PERSON = "Person"; COUNTRY = "Country"; SECTOR = "Sector"; NEWS_REF = "NewsRef"

class RelType(str, Enum):
    PARTICIPATES_IN = "PARTICIPATES_IN"   # (Company)->(Event)
    HAS_NEWS = "HAS_NEWS"                  # (Event)->(NewsRef)
    HAS_KEYWORD = "HAS_KEYWORD"            # (Event)->(Keyword)
    MENTIONS = "MENTIONS"                  # (Event)->(Person)
    ABOUT = "ABOUT"                        # (Event)->(Country)
    BELONGS_TO = "BELONGS_TO"             # (Company)->(Sector)   ※ 3차·보류
    RELATED_TO = "RELATED_TO"            # (Company)->(Company)  ※ 3차·보류

class GraphNode(BaseModel):
    """MERGE 대상 노드. key=정체성(Event:canonical_id, 개체:이름, NewsRef:url).
    properties에 감성 count/분포를 넣지 않는다(조회 시 집계, CLAUDE.md §5)."""
    label: NodeLabel
    key: str
    properties: dict[str, Any] = Field(default_factory=dict)

class GraphRelationship(BaseModel):
    """방향은 erd.dbml 그대로. start/end는 노드의 (label,key)를 가리킨다."""
    type: RelType
    start_label: NodeLabel
    start_key: str
    end_label: NodeLabel
    end_key: str
    properties: dict[str, Any] = Field(default_factory=dict)

class GraphBatch(BaseModel):
    """이번 배치가 추가/갱신할 노드·관계 델타. backend가 key 기준 MERGE(upsert)로 합침.
    감성 미포함. NewsRef는 url 키(backend가 저장 시 news_id로 해소)."""
    nodes: list[GraphNode] = Field(default_factory=list)
    relationships: list[GraphRelationship] = Field(default_factory=list)
```

```python
# services/graph_builder.py — 그래프 조립(순수 매핑, 결정적). LLM·DB 없음.
# ⚠️ 기존 그래프를 읽지 않고 이번 배치 델타만 만든다. 저장·MERGE는 TASK 08(backend HTTP).
from __future__ import annotations
from schemas.article import Article
from schemas.event import Event
from schemas.graph import GraphNode, GraphRelationship, GraphBatch

def event_node(event: Event | None, event_id: str, importance: float | None) -> GraphNode:
    """Event 노드. key=canonical_id, props={canonical_title, importance}.
    편입(event=None) 시 canonical_title 없이 canonical_id+importance만(이름 고정, event_merge §6)."""
    ...

def entity_nodes_and_rels(
    event_id: str, articles: list[Article], extracts: list,
) -> tuple[list[GraphNode], list[GraphRelationship]]:
    """이벤트 소속 기사들의 ExtractResult에서 회사/키워드/인물/국가 노드+관계 생성(union·distinct).
    회사→PARTICIPATES_IN, 키워드→HAS_KEYWORD, 인물→MENTIONS, 국가→ABOUT.
    빈/공백 이름 제외(환각 금지). BELONGS_TO/RELATED_TO는 config 토글 켜질 때만(기본 미생성)."""
    ...

def news_nodes_and_rels(
    event_id: str, articles: list[Article],
) -> tuple[list[GraphNode], list[GraphRelationship]]:
    """기사마다 NewsRef(key=url) + (Event)-[:HAS_NEWS]->(NewsRef). 본문·요약·감성 미포함.
    news_id는 저장 시 backend가 url로 해소(§2)."""
    ...

def build_event_subgraph(
    event_id: str, event: Event | None, articles: list[Article], extracts: list,
    importance: float | None,
) -> tuple[list[GraphNode], list[GraphRelationship]]:
    """한 이벤트의 Event 노드 + 개체 서브그래프 + NewsRef를 합쳐 반환."""
    ...

def build_graph_batch(
    articles: list[Article], extracts_by_url: dict, events_by_id: dict,
    importance_by_event_id: dict,
) -> GraphBatch:
    """event_id 배정 기사를 이벤트별로 묶어 서브그래프 조립.
    - 신규 이벤트=events_by_id(full 노드), 편입=얇은 노드(canonical_id+importance).
    - 배치 전체 노드 (label,key) dedup, 관계 (type,start_key,end_key) dedup, 정렬 방출(결정성).
    - LLM·DB 없음. 감성·importance·병합 재계산 없음(소비만)."""
    ...
```

```python
# nodes/graph_builder.py — 얇은 그래프 노드
# ⚠️ backend를 직접 호출하지 않는다(payload만 만든다). 조립 로직은 services에.
from __future__ import annotations
import services.graph_builder as graph_builder

def graph_node(state: dict) -> dict:
    """event_id 배정 기사를 build_graph_batch로 조립해 state["graph_batch"]에 실는다.
    - 편입(기존) 이벤트도 델타에 포함(HAS_NEWS·개체 관계가 기존 이벤트에도 붙어야 함).
    - 한 이벤트 실패해도 로깅 후 skip, 파이프라인 계속. 대상 0건이면 빈 GraphBatch로 통과.
    """
    ...
```

### 4.1 그래프 조립 규칙 요약 (구조만·감성 미포함·환각 금지)
| 대상 | 노드/관계 | 정체성 키 · 규칙 |
|---|---|---|
| 이벤트 | `Event` 노드 | key=`canonical_id`. props=`canonical_title`(신규만)·`importance`. 감성 count 없음 |
| 회사 | `Company` + `(Company)-[:PARTICIPATES_IN]->(Event)` | key=이름. member 기사 union·distinct |
| 키워드 | `Keyword` + `(Event)-[:HAS_KEYWORD]->` | key=이름. 빈/공백 제외 |
| 인물 | `Person` + `(Event)-[:MENTIONS]->` | key=이름 |
| 국가 | `Country` + `(Event)-[:ABOUT]->` | key=이름 |
| 기사 | `NewsRef` + `(Event)-[:HAS_NEWS]->` | key=`url`(backend가 news_id 해소). 본문·요약·감성 미포함 |
| 회사↔섹터 | `(Company)-[:BELONGS_TO]->(Sector)` | **3차·보류**(매핑 부재). config 토글 기본 off |
| 회사↔회사 | `(Company)-[:RELATED_TO]->(Company)` | **3차·보류**(pipeline_spec §12). config 토글 기본 off |

- **그래프는 "저장"이 아니라 "델타 payload"**: 기존과 합치기는 backend MERGE(TASK 08). 그래프 빌더는 기존 그래프를 읽지 않는다.
- **감성은 그래프에 없다**: 판정은 TASK 04, 분포는 조회 시 집계. Event에 count/분포를 넣지 않는다.
- **이름 고정**: 편입 이벤트의 `canonical_title`을 payload에 넣지 않는다(backend에 이미 있음, 안 바꿈).
- **환각 금지**: 추출된 개체만·있는 url만. 없는 news_id·없는 관계(BELONGS_TO/RELATED_TO 매핑)를 지어내지 않는다.

## 5. 규칙·제약 (CLAUDE.md)
- **§2-1 DB 직접 접근 금지.** 그래프 빌더는 payload(`GraphBatch`)만 만들고 Neo4j MERGE/저장은 TASK 08(backend HTTP). 기존 그래프 조회도 하지 않는다(backend 소유).
- **§2-2 nodes는 얇게, 로직은 services.** 노드·관계 생성·dedup·정렬은 `services/graph_builder.py`. 노드는 묶기·state 반영만.
- **§2-4 감성·점수는 전용 모델·계산, LLM 아님.** 그래프 조립은 순수 매핑이다. LLM(`services/llm.py`) 미호출, 감성을 다시 판정하지 않음(TASK 04 결과도 그래프엔 넣지 않음).
- **§2-5 환각 금지.** 추출된 개체·있는 url만 그래프에 넣는다. news_id를 지어내지 않고 url로 참조(backend 해소). 근거 없는 BELONGS_TO/RELATED_TO를 만들지 않는다(3차·보류).
- **§5 감성 count 미저장·이름 고정.** Event 노드에 감성 분포를 저장하지 않는다(조회 시 집계). 편입 이벤트 canonical_title을 바꾸지 않는다. 7일 롤링 삭제·고아 정리는 backend/scheduler.
- **§7 예외는 로깅·skip, 파이프라인 계속. 설정값 하드코딩 금지**(3차 토글·NewsRef 키 방식은 config, 라벨·관계 타입은 schemas Enum).
- **§8 미확정 존중.** `BELONGS_TO`(회사↔산업 매핑)·`RELATED_TO`(공유이벤트 파생 규칙)는 미정 → 기본 비활성 + 주석으로 3차·보류 표기.

## 6. 완료 조건 (DoD)
- [ ] `schemas/graph.py`가 **신규 생성**되어 `NodeLabel`/`RelType`(erd.dbml 라벨·관계 그대로)·`GraphNode`(label·key·properties)·`GraphRelationship`(type·start/end)·`GraphBatch`(nodes·relationships)를 Pydantic v2로 정의. 감성 count property 없음.
- [ ] `config.py`에 `GRAPH_ENABLE_BELONGS_TO`/`GRAPH_ENABLE_RELATED_TO`(기본 `False`, 3차 주석)·`GRAPH_NEWSREF_KEY`(`"url"`)가 정의됨. 라벨·관계 타입 문자열은 config에 흩지 않고 schemas Enum에 있음.
- [ ] `services/graph_builder.py`가 `event_id` 배정 기사를 **이벤트별로 묶어** Event·Company·Keyword·Person·Country·NewsRef 노드와 `PARTICIPATES_IN`/`HAS_NEWS`/`HAS_KEYWORD`/`MENTIONS`/`ABOUT` 관계를 만든다(erd.dbml 방향·라벨 일치).
- [ ] Event 노드 key=`canonical_id`, props에 `importance`(신규는 `canonical_title`도). **편입(=events_by_id에 없는) 이벤트는 canonical_title 없이** canonical_id+importance만의 얇은 노드로 만든다(이름 고정).
- [ ] NewsRef가 **`url` 키**로 참조되고 본문·요약·감성을 넣지 않음(news_id는 backend가 저장 시 해소).
- [ ] 개체가 **member 기사 union·이름 distinct**로 모임(같은 회사 중복 기사→관계 1개). 빈/공백 이름 제외. `BELONGS_TO`/`RELATED_TO`는 config 토글 off면 **미생성**.
- [ ] `build_graph_batch`가 배치 전체 노드 `(label,key)`·관계 `(type,start_key,end_key)`로 **dedup**하고 **정렬 방출**(결정성: 같은 입력→같은 GraphBatch). 난수·시간·LLM·UUID 생성 없음.
- [ ] **그래프 조립에 LLM·backend·DB를 호출하지 않음**(순수 매핑, 절대규칙 1). 감성·importance·병합을 재계산하지 않고 소비만 함.
- [ ] `nodes/graph_builder.py`가 `event_id` 배정 기사를 `build_graph_batch`로 조립해 `state["graph_batch"]`에 실음. services만 호출.
- [ ] 편입(기존) 이벤트도 델타에 포함(HAS_NEWS·개체 관계가 기존 이벤트에 붙음). 한 이벤트 실패 시 로깅 후 skip, 나머지 계속. 대상 0건이면 **빈 GraphBatch**로 예외 없이 통과.

## 7. 테스트
- **대상 파일**: `tests/test_graph_builder.py`(**신규** — 존재하지 않으므로 생성).
- **mock 전략**: 그래프 조립은 순수 매핑이라 대부분 mock 없이 검증 가능하다(실제 backend·모델 미호출, CLAUDE.md: tests는 mock 기반). 입력은 `Article`·`ExtractResult`·`Event`·`importance_by_event_id` fixture로 구성.
  - **노드/관계 형태**: 이벤트 1개 + 회사 2·키워드 2·인물 1·국가 1·기사 2 → Event/Company/Keyword/Person/Country/NewsRef 노드와 `PARTICIPATES_IN`(회사→Event)·`HAS_NEWS`(Event→NewsRef, key=url)·`HAS_KEYWORD`/`MENTIONS`/`ABOUT`가 방향·라벨대로 생기는지.
  - **Event 노드 property**: `key=canonical_id`, `importance`가 `importance_by_event_id`에서 실리는지. **신규 이벤트는 `canonical_title` 포함**, **편입(events_by_id에 없음) 이벤트는 canonical_title 미포함**(이름 고정)인지.
  - **NewsRef url 키**: NewsRef `key=url`, 본문·요약·감성 property가 **없는지**. news_id를 지어내지 않는지.
  - **union·distinct**: 같은 회사가 이벤트 내 여러 기사에 나와도 Company 노드 1개·PARTICIPATES_IN 1개(중복 관계 없음). 서로 다른 이벤트가 같은 회사를 공유하면 Company 노드는 1개, PARTICIPATES_IN은 이벤트마다.
  - **빈 개체 제외**: 빈/공백 개체명이 노드로 새지 않는지. `ExtractResult`에 개체가 없으면 해당 관계 미생성(환각 금지).
  - **3차 토글**: `GRAPH_ENABLE_BELONGS_TO`/`RELATED_TO`가 `False`면 그 관계가 **생기지 않고**, `True`로 켜면(가능한 경우) 생기는지(기본은 미생성 검증).
  - **감성 미포함**: 어떤 노드에도 감성 count/분포/`sentiment` property가 없는지(구조만).
  - **결정성**: 같은 입력을 두 번 조립 → 노드·관계 순서·내용이 동일(정렬·dedup).
  - **편입 시나리오**: `events_by_id`에 없는 `event_id`(편입) 기사만 있어도 HAS_NEWS·개체 관계 + 얇은 Event 노드가 그 event_id로 생기는지.
  - **`graph_node`**: (1) `state["graph_batch"]`가 `GraphBatch`로 채워지는지, (2) 한 이벤트 조립 실패 시 나머지 계속, (3) 대상 0건일 때 빈 GraphBatch로 통과, (4) backend/LLM 미호출.
  - **LLM·DB 미사용**: 그래프 경로가 `services/llm.py`·backend 클라이언트를 호출하지 않음을 확인(순수 조립).
- **경계 케이스**: event_id 배정 기사 0건, 이벤트 1개에 기사 1건, 개체 전부 빈 리스트, 편입 이벤트만, 한 배치에 여러 이벤트가 회사 공유, `importance_by_event_id`에 값 없음(None property).
- **evals 연계**: 그래프 구축 품질(노드·관계 정확도·과연결/누락)은 이후 `evals/`의 그래프 축에서 정답셋 대조로 다룬다(모델 없이 결정적 채점). 여기 tests는 매핑·방향·dedup·계약 검증.
- 후속 TASK(08 저장)가 `GraphBatch`·`NodeLabel`/`RelType`·NewsRef url 키 규약을 재사용하므로, 노드/관계 계약을 바꾸면 `schemas/graph.py`부터 함께 수정한다(그리고 erd.dbml/SCHEMA_SPEC §3과 정합 유지).

## 8. 구현 계약 요약 (I/O)
| 입력 | 출력 | 호출 가능 | 호출 금지 | 실패 시 |
|---|---|---|---|---|
| `state["articles"]`·`extracts_by_url`·`events_by_id`·`importance_by_event_id` | `state["graph_batch"]`(`GraphBatch` 델타) | `services/graph_builder`(순수 매핑) | LLM, backend/DB, 감성 판정, UUID 생성 | 이벤트별 실패 skip, 0건이면 빈 `GraphBatch` |
