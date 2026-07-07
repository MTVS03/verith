# TASK 05 — 임베딩 & 이벤트 병합 (services/embedder.py · services/event_merge.py · utils/similarity.py · nodes/embedding.py · nodes/merge_event.py)

## 0. 개요
- **목적**: 배치 흐름의 다섯 번째·여섯 번째 단계(임베딩 → 병합). ① 추출된 `summary`를 **arctic-embed-l-v2.0-ko**로 임베딩해 `Article.embedding`에 채우고, ② 그 임베딩 + 회사 + 시간의 **가중 점수**로 새 기사를 기존 이벤트에 **편입하거나 신규 이벤트를 생성**한다. 결과로 각 기사에 `Article.event_id`(소속 이벤트의 `canonical_id`)를 배정하고, 이번 배치에서 만들어지거나 건드린 `Event`를 후속(importance·그래프·저장)으로 넘긴다. **병합 단위는 기사 1건 → 이벤트 1개**다(한 기사가 여러 이벤트에 동시 소속되지 않는다).
- **선행 작업**:
  - TASK 01(schemas: `Article.embedding`/`event_id`, `Event`(`canonical_id`/`canonical_title`/`importance`/`companies`), `MergeCandidate`, `MergeDecision`).
  - TASK 03(`ExtractResult`: `summary`·`companies`·`events: list[EventCandidate]`(title+confidence)·`event_date`. `state["extracts_by_url"]`로 기사와 짝지어 전달됨).
  - TASK 04(감성은 병합의 입력이 아니지만, 파이프라인상 sentiment 다음 단계다. `Article.sentiment`는 병합에 쓰지 않는다).
  - ✅ **TASK 01에 반영됨**: 병합 후보 조회 결과 `CandidateEvent`는 이제 TASK 01 `schemas/event.py`에 Pydantic 모델로 정의되어 있다(서비스·백엔드 클라이언트·테스트가 같은 계약 공유). 이 문서는 그 계약을 소비한다(별도 동반 수정 불필요).
- **산출물(파일)**:
  - `config.py`(발췌 추가) — 임베딩 설정(모델·디바이스·배치·입력 상한) + 병합 설정(가중치 0.6/0.3/0.1·임계값·후보 창(7일)·시간 감쇠). 하드코딩 금지의 귀착점.
  - `schemas/event.py`(발췌 추가 — ⚠️ TASK 01) — `CandidateEvent`(후보 이벤트 조회 결과: canonical_id·companies·대표 임베딩·event_time). 병합 후보 계약.
  - `services/embedder.py` — arctic-embed-l-v2.0-ko 클라이언트 + `embed()`/`embed_batch()`. 대칭 비교라 query/document 프리픽스 없음.
  - `utils/similarity.py` — 순수 함수: 코사인 유사도, 회사 중복도, 시간 근접도.
  - `services/event_merge.py` — 후보 조회 인터페이스(`RecentEventProvider` Protocol) + 가중 점수 계산 + 병합 판정(`MergeDecision`) + 규칙 기반 canonical 생성.
  - `nodes/embedding.py` — 얇은 노드: `summary`가 있는 기사만 임베딩해 `Article.embedding`에 반영.
  - `nodes/merge_event.py` — 얇은 노드: 기사별로 후보를 받아 `MergeDecision`을 계산하고 `Article.event_id`를 배정, `Event`를 state로 넘김.
- **범위 밖(주의)**:
  - **기존 이벤트의 실제 조회(Neo4j/PostgreSQL)는 TASK 08**. 여기서는 `RecentEventProvider` **인터페이스(계약)만** 정의하고, 실제 backend HTTP 조회 구현은 TASK 08이 채운다(절대규칙 1: DB 직접 접근 금지). TASK 05는 주입된 provider를 소비만 한다.
  - **이벤트 대표 벡터(centroid)의 계산·갱신도 backend(TASK 08) 책임**. TASK 05는 조회된 centroid를 읽어 유사도만 계산하고, centroid를 만들거나 갱신하지 않는다(집계·상태 유지는 backend 소유).
  - **importance 계산은 TASK 06**. 여기서는 `Event.importance=None`으로 둔다(신규).
  - **Neo4j 노드·관계 구성은 TASK 07**, **저장은 TASK 08**.
  - **canonical_title을 LLM으로 생성하지 않는다**(CLAUDE.md §2-4). 규칙 기반(최상위 confidence `EventCandidate.title`)으로만 만든다.
  - **감성으로 병합하지 않는다**: 병합 신호는 summary 임베딩·회사·시간뿐이다(event_merge.md §3).

### 0.1 하위 의존성 (⚠️ 수정 시 영향 범위)
이 단계는 기사에 "소속 이벤트"를 부여하고 이벤트 골격을 만든다. 아래 계약을 바꾸면 후속 TASK가 영향받는다.

| 산출물 | 소비하는 TASK |
|---|---|
| `Article.embedding`(arctic 임베딩) | TASK 08(저장, pgvector), (확장) 유사 검색 |
| `Article.event_id`(= 소속 이벤트 `canonical_id`) | TASK 06(importance: 이벤트별 기사 집계), 07(그래프: HAS_NEWS), 08(저장) |
| 이번 배치의 `Event`(canonical_id·canonical_title·companies) | TASK 06(importance 부여), 07(Company-PARTICIPATES_IN-Event 등), 08(저장) |
| `MergeDecision`/`MergeCandidate`(점수·판정) | 디버깅·evals(병합 품질). 필드 변경 시 TASK 01부터 |
| `RecentEventProvider` 인터페이스 + `CandidateEvent` | TASK 08(backend 클라이언트가 이 인터페이스를 구현해 실제 조회) |

## 1. 참고 문서
- `docs/event_merge.md` — 전체 근거. §2(왜 summary로 병합), §3(가중 점수 0.6/0.3/0.1), §4(임계값·억지 편입 금지), §5(후보 축소: 동일 회사·최근 7일), §6(canonical 이름 고정·감성 평가어 금지), §7(증분편입).
- `docs/model_choice.md` §3(임베딩: arctic-embed-l-v2.0-ko, 프리픽스 없이 대칭 임베딩), §4(모델 분업).
- `docs/pipeline_spec.md` §2(배치 흐름), §6(이벤트 병합), §8(지식 그래프: Company-PARTICIPATES_IN-Event, 여러 회사가 한 이벤트 공유).
- `docs/sequence.md` §1(배치 시퀀스: embedder → event_merge).
- `docs/erd.dbml` — news `embedding`/`event_id`, Neo4j Event(`canonical_id`/`canonical_title`/`importance`).
- `CLAUDE.md` §2-1(DB 직접 접근 금지), §2-2(nodes 얇게), §2-4(감성·유사도 판정은 전용 모델·계산이지 LLM 아님), §2-5(환각 금지: 억지 병합 금지), §4(모델 스택), §5(병합 가중 점수·canonical·감성 count 미저장·7일 롤링), §7(코딩 컨벤션).
- TASK 01 `schemas/event.py`(`Event`/`MergeCandidate`/`MergeDecision`), `schemas/article.py`(`Article.embedding`/`event_id`).
- TASK 03 `schemas/article.py`(`ExtractResult`: `summary`·`companies`·`events`·`event_date`), §3.2.2(`EventCandidate` title 규칙: 회사명·감성어 금지).

## 2. 배경 (왜)
- **왜 `summary`를 임베딩하나(제목·본문 아님)**: 이벤트명은 짧아 반대 의미도 겹치고("AI 투자 확대" vs "축소"), 본문은 노이즈가 많다. LLM이 만든 **맥락 담긴 요약**을 임베딩해야 같은 사건이 안정적으로 묶인다 (event_merge.md §2). 그래서 임베딩 입력은 `Article.summary`다. (감성은 반대로 `content`를 쓴다 — TASK 04. 두 모델이 다른 입력을 쓴다.)
- **왜 arctic-embed-l-v2.0-ko이고, 왜 프리픽스가 없나**: 한국어 검색 SOTA급 + 대량 처리 강점(model_choice §3). 다만 이 단계는 **기사끼리 유사도 비교(대칭)**라 검색용 query/document 프리픽스를 붙이지 않고 모든 summary를 같은 방식으로 임베딩한다. 프리픽스를 섞으면 대칭성이 깨져 병합이 흔들린다.
- **왜 summary 유사도만으로 병합하지 않나**: summary만 보면 "삼성전자 AI 투자"와 "SK하이닉스 AI 투자"가 회사가 달라도 합쳐진다. 세 신호를 가중 결합한다 (event_merge.md §3):
  `score = 0.6·summary_similarity + 0.3·company_overlap + 0.1·time_proximity`.
  회사가 다르면 `company_overlap=0`으로 다른 회사 사건 병합을 막고, 시점이 멀면 `time_proximity`가 낮아 3개월 전 "투자 확대"와 오늘 것을 구분한다.
- **왜 최고 점수라도 임계값 미만이면 새 이벤트인가(억지 편입 금지)**: "제일 가까운 것"을 무조건 받으면 과병합이 생긴다. 임계값 미만이면 편입을 거부하고 신규 이벤트를 만든다 (event_merge.md §4, 환각/억지 금지 정신).
- **왜 후보를 동일 회사·최근 7일로 줄이나**: 모든 이벤트와 비교하면 느리다. 7일 롤링 삭제로 살아있는 이벤트가 7일치라 자연히 완화되지만, 후보 축소를 조회 인터페이스 계약에 명시한다 (event_merge.md §5).
- **왜 기존 이벤트 조회를 인터페이스(계약)로만 두나**: 실제 조회는 Neo4j/PostgreSQL이고 이는 backend HTTP로만 접근한다(절대규칙 1). backend 클라이언트는 TASK 08이다. 그래서 TASK 05는 `RecentEventProvider` **인터페이스만** 정의해 주입받고(테스트는 fake), 실제 구현은 TASK 08이 채운다. 이렇게 하면 병합 로직을 backend 없이도 단위 테스트할 수 있고, 의존성 방향이 깔끔하다.
- **왜 병합 단위가 기사 1건인가**: summary 임베딩이 **기사 단위** 벡터라, 기사 하나를 이벤트 하나에 배정하는 것이 점수 공식과 자연스럽게 맞는다. 기사가 여러 `EventCandidate`를 가져도, 그 후보들은 **canonical_title 후보와 가중**에만 쓰고 배정 자체는 기사 → 이벤트 1:1이다. (`Article.event_id`는 단일 필드다.)
- **왜 canonical을 규칙 기반으로 만드나**: 감성·유사도 외 LLM 사용을 늘리지 않는다(CLAUDE.md §2-4/§4). 신규 이벤트의 `canonical_title`은 그 기사의 `EventCandidate` 중 **최상위 confidence title**을 채택한다(이미 회사명·감성 평가어가 배제된 사건명 — TASK 03 §3.2.2). `canonical_id`는 UUID4로 생성한다. 이름은 한 번 정하면 새 기사가 조금 달라도 바꾸지 않는다 (event_merge.md §6).
- **왜 전체 재군집화를 안 하나(증분편입)**: 매시간 모든 기사를 다시 묶으면 ID·이름이 흔들린다. 새 기사만 편입/신규 생성하고 기존 이벤트는 유지한다 (event_merge.md §7).
- **DB 접근 금지**: 임베딩·병합은 모델 추론·계산만. 조회·저장은 backend HTTP(TASK 08) (CLAUDE.md §2-1).

## 3. 요구사항

### 3.1 `config.py` — 임베딩·병합 설정 (하드코딩 금지)
1. **임베딩 모델**: `EMBED_MODEL`(arctic-embed-l-v2.0-ko 식별자), `EMBED_DEVICE`(`"cpu"`/`"cuda"`), `EMBED_BATCH_SIZE`(배치 크기 — 처리량), `EMBED_MAX_INPUT_CHARS`(8K 컨텍스트 고려 입력 상한). **프리픽스 설정을 두지 않는다**(대칭 임베딩이라 query/document 프리픽스 미사용, model_choice §3). 임베딩 차원은 모델 스펙을 따르며 config에 하드코딩하지 않는다.
2. **병합 가중치**: `MERGE_W_SUMMARY=0.6`, `MERGE_W_COMPANY=0.3`, `MERGE_W_TIME=0.1`. 계수는 임시값(실데이터 튜닝, event_merge.md §3). 합이 1이 되도록 둔다(가독성).
3. **병합 임계값**: `MERGE_THRESHOLD`(이 값 미만이면 신규 이벤트). 튜닝 대상 — 주석 표기 (event_merge.md §4).
4. **후보 축소**: `MERGE_CANDIDATE_WINDOW_DAYS=7`(후보로 볼 최근 기간). 조회 인터페이스에 전달 (event_merge.md §5).
5. **시간 근접도**: `MERGE_TIME_DECAY_DAYS`(time_proximity 감쇠 스케일, 예: 7). 며칠 차이까지 가깝게 볼지의 기준.

### 3.2 `services/embedder.py` — arctic 임베딩 서비스
1. **모델 로드**: `config`의 `EMBED_MODEL`/`EMBED_DEVICE`로 arctic-embed-l-v2.0-ko를 로드한다. 무겁고 재사용되므로 **지연 로드 + 프로세스 내 1회 로드(싱글턴/모듈 캐시)**로 둔다.
2. **`embed(text)`**: 텍스트 1건(=기사 `summary`) → `list[float]` 임베딩. 입력은 `EMBED_MAX_INPUT_CHARS`로 잘라 넣는다. **query/document 프리픽스를 붙이지 않는다**(대칭 비교). 빈/None 입력은 임베딩하지 않고 "임베딩 없음"을 신호한다(환각/무의미 벡터 방지).
3. **`embed_batch(texts)`**: 여러 요약을 **배치 임베딩**해 `list[list[float]]`로 반환한다(처리량). 반환 길이·순서는 입력과 항상 일치. 배치 실패 시 각 텍스트를 `embed()`로 1건씩 fallback 재시도(실패 격리, TASK 04 §3.3 정신과 동일).
4. **부수효과 최소화**: 입력 텍스트 → 출력 벡터. 저장·DB 접근 없음 (CLAUDE.md §2-1). `Article` 갱신은 노드가 한다.
5. **유사도 판정을 여기서 하지 않는다**: embedder는 벡터만 만든다. 코사인 계산은 `utils/similarity.py`, 병합 판정은 `services/event_merge.py`.

### 3.3 `utils/similarity.py` — 유사도·중복도·근접도 (순수 함수)
1. **`cosine_similarity(a, b)`**: 두 벡터의 코사인 유사도(−1~1, 실무상 0~1로 clamp 가능). 네트워크·모델 호출 없음(순수 계산).
2. **`company_overlap(a, b)`**: 두 회사 리스트의 중복도(0~1). **Jaccard**(`|A∩B| / |A∪B|`) 권장. **한쪽이라도 비어 있으면 0**(회사 일치를 확인할 수 없으므로 병합 신호로 인정하지 않음 — 다른 회사 사건 병합 방지, event_merge.md §3).
   - **회사명 정규화 = 공유 유틸 `normalize_entity_name`(결정적·최소)**: 앞뒤/중복 공백 정리 + `㈜`/`(주)`/`（주）` 제거. **이게 전부다** — 복잡한 별칭·오타 정규화(`삼전`→`삼성전자`)는 하지 않는다. 별칭→canonical 해석은 **질의측 Dictionary First**가 담당하고, 배치측 추출 회사명은 이미 표준형에 가깝다. TASK 07(그래프 Company 노드 key)이 **같은 함수**를 써 병합 신호와 노드 정체성이 갈리지 않게 한다.
3. **`time_proximity(t1, t2)`**: 두 시각의 근접도(0~1). Δ가 커질수록 0에 수렴하는 감쇠(예: `exp(-Δdays / MERGE_TIME_DECAY_DAYS)`). **입력이 이벤트 발생 시점**임에 유의(§3.4). 한쪽이 `None`이면 시간 신호 없음으로 처리(0 또는 중립 — §3.4에서 규칙 확정).
4. 세 함수 모두 입력→출력 순수 함수로 두어 병합 로직·테스트가 재사용한다.

### 3.4 `services/event_merge.py` — 병합 서비스
> **⚠️ 조회 경계 규칙 (아키텍처 규칙)**: 기존 이벤트를 가져오는 **유일한 경로는 주입된 `RecentEventProvider`**다. 이 서비스·노드는 DB 드라이버·Cypher·backend HTTP를 직접 부르지 않는다(절대규칙 1). provider의 실제 구현은 TASK 08(backend 클라이언트)이 담당한다.

1. **후보 조회 인터페이스 `RecentEventProvider`(Protocol)**: `get_recent_events(companies: list[str], within_days: int) -> list[CandidateEvent]`. 동일 회사·최근 N일 이벤트만 반환한다(후보 축소를 인터페이스 계약으로 강제, event_merge.md §5). TASK 05는 이 시그니처만 정의하고, TASK 08이 Neo4j/PostgreSQL 조회로 구현한다. **미주입 시 기본 provider는 빈 리스트를 반환**(backend 미연결 상태에서도 파이프라인이 죽지 않고, 모든 기사가 신규 이벤트가 됨).
2. **`CandidateEvent`(schemas/event.py, ⚠️ TASK 01)**: 후보 이벤트를 점수 계산에 필요한 만큼만 담는다 → `canonical_id`, `companies`, `embedding`(**대표 벡터** = 소속 기사 summary 임베딩들의 centroid), `event_time`(이벤트 발생 시점, 없으면 최신 기사 시각). **대표 벡터(centroid)의 계산·갱신 책임은 backend(TASK 08)에 있다** — 기사가 이벤트에 편입/저장될 때 backend가 centroid를 재계산·유지한다. **TASK 05는 provider가 조회해 준 centroid를 읽기만** 하고, 여기서 centroid를 계산·갱신하지 않는다(집계·상태 유지는 backend 소유, 절대규칙 1).
3. **점수 계산 `score_candidate(article_vec, article_companies, article_time, cand) -> MergeCandidate`**:
   - `summary_similarity = cosine_similarity(article_vec, cand.embedding)`
   - `company_overlap = company_overlap(article_companies, cand.companies)`
   - `time_similarity = time_proximity(article_time, cand.event_time)`
   - `score = MERGE_W_SUMMARY·summary_similarity + MERGE_W_COMPANY·company_overlap + MERGE_W_TIME·time_similarity`
   - 세부 점수를 `MergeCandidate`에 함께 담아(디버깅) 반환한다.
4. **판정 `decide_merge(article, extract, provider) -> MergeDecision`**:
   - `article.embedding`이 없으면(요약/임베딩 실패) 병합하지 않고 skip 신호(파이프라인 계속).
   - `provider.get_recent_events(extract.companies, MERGE_CANDIDATE_WINDOW_DAYS)`로 후보를 받아 각 후보에 `score_candidate`를 적용.
   - **article_time 결정**: `extract.event_date`가 있으면 그것을, 없으면 `article.published_at`을 쓴다(둘 다 없으면 시간 신호 없음). event_date를 우선하는 이유는 TASK 03 §2(발생 시점 ≠ 발행 시점).
   - 최고 점수 후보가 `MERGE_THRESHOLD` **이상**이면 그 이벤트에 편입(`assigned_event_id=그 canonical_id`, `is_new_event=False`), **미만**이면 신규(`is_new_event=True`, `assigned_event_id=None`). `best_score`·`candidates`를 채워 반환.
5. **규칙 기반 canonical 생성(신규일 때)**:
   - `make_canonical_title(extract) -> str`: `extract.events`(EventCandidate 리스트)에서 **최상위 confidence의 title**을 선택. 리스트가 비면 폴백(예: `summary` 앞부분 또는 대표 키워드)하되 감성 평가어를 넣지 않는다(event_merge.md §6). 회사명은 이미 title에 없음(TASK 03 §3.2.2).
   - `new_event(extract) -> Event`: `canonical_id=str(uuid4())`, `canonical_title=make_canonical_title(...)`, `companies=extract.companies`, `importance=None`(TASK 06), `created_at=now`.
6. **배치 내 중복 신규 이벤트 방지(증분편입의 연장)**: 같은 배치에서 방금 만든 신규 `Event`도 이후 기사의 후보에 포함한다(그렇지 않으면 같은 배치의 동일 사건이 각각 새 이벤트가 됨). 이는 전체 재군집화가 아니라 순차 편입이다(event_merge.md §7). 구현은 노드가 이번 배치 이벤트를 누적해 provider 결과와 합쳐 후보로 넘기는 방식(§3.6).
7. **감성·importance를 계산하지 않는다**: 이 서비스는 배정·이름만. 감성은 TASK 04, importance는 TASK 06 (단일 책임).

### 3.5 `nodes/embedding.py` — 임베딩 노드 (얇게)
1. `state["articles"]`를 순회하며 **`summary`가 있는 기사만** 임베딩 대상으로 모은다(요약이 없거나 빈 기사는 skip → `embedding=None`). 노드는 순서만 담당 (CLAUDE.md §2-2).
2. 모은 요약을 `embedder.embed_batch`로 한 번에 처리하고, 결과를 원래 기사와 순서로 짝지어 `Article.embedding`에 반영한다(처리량, 계약: 순서 일치).
3. 한 기사 임베딩 실패해도 로깅 후 skip(`embedding=None`), 나머지 계속 (CLAUDE.md §7). 대상 0건이면 예외 없이 통과.
4. 모델을 직접 로드하지 않는다(로직은 `services/embedder.py`).

### 3.6 `nodes/merge_event.py` — 병합 노드 (얇게)
1. `state["articles"]`와 `state["extracts_by_url"]`(TASK 03)를 짝지어 순회한다. `embedding`이 있는 기사만 병합 대상.
2. **provider 주입**: backend 조회 provider를 주입받아 `event_merge.decide_merge`에 넘긴다. TASK 08의 backend 클라이언트가 이 provider를 구현하며, **미연결 시 기본 provider(빈 리스트)**로 동작해 모든 기사가 신규가 된다(파이프라인 안 죽음). 노드는 backend를 직접 호출하지 않는다.
3. **이번 배치 이벤트 누적**: 방금 만든 신규 `Event`를 누적 컬렉션에 넣고, 이후 기사의 후보에 provider 결과와 함께 포함한다(§3.4-6, 배치 내 중복 신규 방지).
4. **결과 반영**:
   - `Article.event_id = decision.assigned_event_id`(신규면 방금 만든 `Event.canonical_id`).
   - 신규 이벤트면 `Event`를 `state["events_by_id"]`에 등록(canonical_id 키). 편입이면 그 이벤트를 참조로 기록(회사 합집합 등 실제 갱신은 backend 저장 시, TASK 08).
   - **`Article.analysis_completed=True`**로 표시(요약·감성·임베딩·병합까지 완료된 최종 플래그, TASK 01 §3.1). 병합 skip(임베딩 없음 등)한 기사는 `False` 유지.
5. **실패 격리**: 한 기사 병합 실패해도 예외로 파이프라인을 죽이지 않는다. 로깅 후 skip, 나머지 계속 (CLAUDE.md §7).
6. 대상 0건이면 예외 없이 통과(환각 금지: 없으면 없는 대로). 후속·리포트가 "데이터 제한" 처리.

## 4. 인터페이스 / 구현 규칙

> 아래는 확정 시그니처(초안). 함수명·반환 타입은 이대로 구현하되, 설정값은 `config.py`에서 읽는다. 함수 본문(로직)은 비워 둔다.

```python
# config.py (발췌) — 임베딩·병합 설정. 값은 실데이터 튜닝 대상(주석 표기).
EMBED_MODEL: str = "arctic-embed-l-v2.0-ko"   # 한국어 검색 SOTA급(model_choice §3). 차원은 모델 스펙 따름
EMBED_DEVICE: str = "cpu"                       # 가능 시 "cuda"
EMBED_BATCH_SIZE: int = 32                      # 배치 임베딩 크기(처리량) — 튜닝 대상
EMBED_MAX_INPUT_CHARS: int = 8000               # 입력 상한(8K 컨텍스트 고려). 초과분 잘라 입력
# ⚠️ query/document 프리픽스 설정 없음 — 기사끼리 대칭 비교라 프리픽스 미사용(model_choice §3)

MERGE_W_SUMMARY: float = 0.6                    # 가중치(합=1) — 튜닝 대상(event_merge.md §3)
MERGE_W_COMPANY: float = 0.3
MERGE_W_TIME: float = 0.1
MERGE_THRESHOLD: float = 0.7                    # 미만이면 신규 이벤트(억지 편입 금지) — 튜닝 대상
MERGE_CANDIDATE_WINDOW_DAYS: int = 7            # 후보: 동일 회사·최근 N일(event_merge.md §5)
MERGE_TIME_DECAY_DAYS: float = 7.0             # time_proximity 감쇠 스케일 — 튜닝 대상
```

```python
# schemas/event.py (발췌 — TASK 01에 정의됨. 여기서는 계약 재확인)
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field

class CandidateEvent(BaseModel):
    """병합 후보 이벤트(조회 결과). RecentEventProvider가 반환, 점수 계산 입력."""
    canonical_id: str
    companies: list[str] = Field(default_factory=list)
    embedding: list[float]              # 대표 벡터(소속 기사 summary 임베딩 centroid). 계산·갱신은 backend(TASK 08) 책임, TASK 05는 읽기만
    event_time: datetime | None = None  # 이벤트 발생 시점(없으면 최신 기사 시각). time_proximity 입력
```

```python
# utils/similarity.py — 순수 계산(모델·네트워크 없음)
from __future__ import annotations
from datetime import datetime

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """두 벡터 코사인 유사도. summary_similarity에 사용."""
    ...

def company_overlap(a: list[str], b: list[str]) -> float:
    """회사 리스트 중복도(0~1, Jaccard). 한쪽이라도 비면 0(회사 일치 미확인 → 병합 신호 아님)."""
    ...

def time_proximity(t1: datetime | None, t2: datetime | None) -> float:
    """이벤트 발생 시점 근접도(0~1). Δ가 커질수록 0에 수렴(MERGE_TIME_DECAY_DAYS 감쇠).
    한쪽이 None이면 시간 신호 없음으로 처리."""
    ...
```

```python
# services/embedder.py — arctic-embed-l-v2.0-ko 임베딩 서비스
# ⚠️ query/document 프리픽스를 붙이지 않는다(대칭 비교). 유사도 계산은 여기서 하지 않는다.
from __future__ import annotations

def embed(text: str) -> list[float]:
    """summary 1건 → 임베딩 벡터.
    - 입력은 EMBED_MAX_INPUT_CHARS로 잘라 넣는다. 프리픽스 없음.
    - 빈/None은 임베딩 없음 신호(무의미 벡터 방지). 저장·부수효과 없음.
    """
    ...

def embed_batch(texts: list[str]) -> list[list[float]]:
    """여러 summary 배치 임베딩(처리량). 반환 길이·순서는 입력과 항상 일치.
    - 배치 실패 시 각 텍스트를 embed()로 1건씩 fallback(실패 격리).
    """
    ...
```

```python
# services/event_merge.py — 병합 판정 서비스
# ⚠️ 기존 이벤트 조회는 주입된 RecentEventProvider로만. DB/Cypher/backend 직접 호출 금지(절대규칙 1).
from __future__ import annotations
from typing import Protocol
from schemas.article import Article, ExtractResult
from schemas.event import Event, CandidateEvent, MergeCandidate, MergeDecision

class RecentEventProvider(Protocol):
    def get_recent_events(self, companies: list[str], within_days: int) -> list[CandidateEvent]:
        """동일 회사·최근 within_days 이벤트만 반환(후보 축소). 실제 구현은 TASK 08.
        미주입 기본 구현은 []를 반환(모든 기사가 신규 이벤트가 됨)."""
        ...

def score_candidate(
    article_vec: list[float], article_companies: list[str],
    article_time, cand: CandidateEvent,
) -> MergeCandidate:
    """0.6·summary + 0.3·company + 0.1·time 가중 점수. 세부 점수도 함께 담아 반환."""
    ...

def decide_merge(
    article: Article, extract: ExtractResult, provider: RecentEventProvider,
) -> MergeDecision:
    """기사 1건 → 편입 or 신규 판정.
    - embedding 없으면 skip 신호. article_time = event_date(우선) or published_at.
    - 후보에 score_candidate 적용, 최고점 >= MERGE_THRESHOLD면 편입, 미만이면 신규.
    """
    ...

def make_canonical_title(extract: ExtractResult) -> str:
    """신규 이벤트 대표명 = extract.events 중 최상위 confidence title.
    비면 폴백(요약 앞부분/키워드). 감성 평가어 금지, 회사명 없음(TASK 03 §3.2.2)."""
    ...

def new_event(extract: ExtractResult) -> Event:
    """canonical_id=uuid4, canonical_title=make_canonical_title, companies=extract.companies,
    importance=None(TASK 06), created_at=now."""
    ...
```

```python
# nodes/embedding.py — 얇은 임베딩 노드
from __future__ import annotations
import services.embedder as embedder

def embedding_node(state: dict) -> dict:
    """summary 있는 기사만 embed_batch로 임베딩 → Article.embedding 반영(순서 일치).
    summary 없으면 embedding=None. 실패 기사는 로깅 후 skip, 파이프라인 계속."""
    ...
```

```python
# nodes/merge_event.py — 얇은 병합 노드
# ⚠️ backend를 직접 호출하지 않는다(주입된 RecentEventProvider 사용).
from __future__ import annotations
import services.event_merge as event_merge

def merge_event_node(state: dict, provider=None) -> dict:
    """articles × extracts_by_url를 짝지어 순회하며 decide_merge.
    - provider 미주입 시 기본(빈 후보) → 모든 기사 신규. TASK 08이 backend provider 주입.
    - 이번 배치 신규 Event를 누적해 이후 기사 후보에 포함(배치 내 중복 신규 방지).
    - Article.event_id 배정, 신규 Event를 state["events_by_id"]에 등록, analysis_completed=True.
    - 한 기사 실패해도 로깅 후 skip, 파이프라인 계속.
    """
    ...
```

### 4.1 병합 판정 규칙 요약 (억지 편입·감성 병합 금지)
| 상황 | 처리 |
|---|---|
| `embedding` 없음(요약/임베딩 실패) | 병합 skip. `event_id=None`, `analysis_completed=False` |
| 최고 점수 후보 `>= MERGE_THRESHOLD` | 그 이벤트에 편입. `event_id=canonical_id`, `is_new_event=False` |
| 최고 점수 후보 `< MERGE_THRESHOLD` 또는 후보 없음 | 신규 이벤트 생성(규칙 기반 canonical). `is_new_event=True` |
| 회사가 완전히 다름 | `company_overlap=0` → 점수 하락(다른 회사 사건 병합 방지) |
| 시점이 멂 | `time_proximity`↓ → 점수 하락(과거 동명 사건 구분) |

- **감성으로 병합하지 않는다**: `Article.sentiment`는 점수 공식에 없다. 병합 신호는 summary·회사·시간뿐.
- **canonical_title에 감성 평가어 금지**: "실적 발표"(O)/"실적 호조"(X) (event_merge.md §6).
- **이름 고정**: 편입 시 기존 `canonical_title`을 바꾸지 않는다.

## 5. 규칙·제약 (CLAUDE.md)
- **§2-1 DB 직접 접근 금지.** 기존 이벤트 조회는 주입된 `RecentEventProvider`로만(실제 구현은 TASK 08 backend HTTP). 저장도 TASK 08.
- **§2-2 nodes는 얇게, 로직은 services.** 임베딩·유사도·병합 판정은 services/utils. 노드는 순회·반영만.
- **§2-4 감성·유사도는 전용 모델·계산, LLM 아님.** 병합은 임베딩 유사도·계산이고, canonical_title은 규칙 기반. LLM 호출 없음.
- **§2-5 환각/억지 금지.** 임계값 미만이면 억지로 편입하지 않고 신규 생성. 요약/임베딩 없으면 지어내지 않고 skip.
- **§5 병합 가중 점수·canonical·감성 count 미저장.** 0.6/0.3/0.1 + 임계값, canonical_id/title 고정, Event에 감성 count 없음(조회 시 집계).
- **§4 모델 스택 고정.** 임베딩은 arctic-embed-l-v2.0-ko / services/embedder.py.
- **§7 외부 호출 타임아웃·재시도, 예외 로깅·skip, 파이프라인 계속. 설정값 하드코딩 금지**(가중치·임계값·창·감쇠·모델명은 config).

## 6. 완료 조건 (DoD)
- [ ] `config.py`에 `EMBED_MODEL`(arctic)/`EMBED_DEVICE`/`EMBED_BATCH_SIZE`/`EMBED_MAX_INPUT_CHARS` + `MERGE_W_SUMMARY/COMPANY/TIME`(0.6/0.3/0.1)/`MERGE_THRESHOLD`/`MERGE_CANDIDATE_WINDOW_DAYS`(7)/`MERGE_TIME_DECAY_DAYS`가 정의됨. 프리픽스 설정·임베딩 차원 하드코딩 없음.
- [ ] `CandidateEvent`가 `schemas/event.py`에 Pydantic 모델로 추가됨(canonical_id·companies·embedding·event_time). ⚠️ TASK 01에 반영.
- [ ] `services/embedder.py`의 `embed`/`embed_batch`가 arctic 임베딩을 반환하며 **프리픽스를 붙이지 않음**. `embed_batch`는 순서·길이 일치 + 배치 실패 시 개별 fallback. 빈/None은 임베딩 없음 처리.
- [ ] `utils/similarity.py`의 `cosine_similarity`/`company_overlap`(Jaccard, 한쪽 비면 0)/`time_proximity`(감쇠, None 처리)가 순수 함수로 동작.
- [ ] `services/event_merge.py`가 `RecentEventProvider` **인터페이스만** 정의하고 backend/DB를 직접 호출하지 않음. 미주입 기본 provider는 빈 리스트 반환.
- [ ] `score_candidate`가 `0.6·summary + 0.3·company + 0.1·time`으로 계산하고 세부 점수를 `MergeCandidate`에 담음.
- [ ] `decide_merge`가 최고점 `>= MERGE_THRESHOLD`면 편입, 미만/후보없음이면 신규 판정. `article_time`은 `event_date` 우선, 없으면 `published_at`.
- [ ] 신규 이벤트의 `canonical_id`가 UUID4, `canonical_title`이 **최상위 confidence `EventCandidate.title`**(감성 평가어·회사명 없음). **LLM 미사용**(services/llm.py 미호출).
- [ ] **병합 단위가 기사 1건 → 이벤트 1개**: `Article.event_id`가 단일 배정됨(한 기사가 여러 이벤트에 배정되지 않음).
- [ ] **감성이 점수 공식에 쓰이지 않음**(summary·회사·시간만).
- [ ] `nodes/embedding.py`가 `summary` 있는 기사만 임베딩(순서 일치), `nodes/merge_event.py`가 `Article.event_id` 배정 + 신규 `Event`를 `state["events_by_id"]`에 등록 + `analysis_completed=True` 설정. 둘 다 services만 호출.
- [ ] 배치 내에서 방금 만든 신규 이벤트가 이후 기사의 후보에 포함됨(배치 내 중복 신규 방지).
- [ ] 한 기사 실패 시 로깅 후 skip, 나머지 계속. 대상 0건일 때 예외 없이 통과.

## 7. 테스트
- **대상 파일**: `tests/test_embedding.py`(존재), `tests/test_event_merge.py`(존재, 핵심 로직이라 반드시 — event_merge.md §8).
- **mock 전략**: 실제 임베딩 모델·backend를 호출하지 않는다 (CLAUDE.md: tests는 mock 기반).
  - **embedder**: arctic 호출을 mock해 고정 벡터를 돌려주고, `embed_batch`의 순서·길이 일치와 배치 실패 시 개별 fallback을 검증. 빈/None 입력이 임베딩 없음으로 처리되는지.
  - **similarity**: `cosine_similarity`(동일 벡터→1, 직교→0), `company_overlap`(부분 겹침 Jaccard 값, 한쪽 빈 리스트→0), `time_proximity`(Δ=0→1, 멀수록↓, None→시간 신호 없음). 순수 함수라 mock 불필요.
  - **event_merge(핵심)**: **fake `RecentEventProvider`**로 후보를 주입.
    - 유사·동일 회사·근접 시점 후보가 임계값 이상 → 편입(`is_new_event=False`, `assigned_event_id`=후보 id).
    - 회사 다름(overlap 0) → 점수 하락으로 신규(`is_new_event=True`).
    - 후보 없음(빈 provider) → 신규.
    - 최고점이 임계값 **바로 아래** → 신규(억지 편입 금지 경계).
    - `event_date` 있으면 그것으로, 없으면 `published_at`으로 time 계산되는지.
    - **canonical**: 신규 이벤트의 `canonical_title`이 최상위 confidence `EventCandidate.title`인지, `canonical_id`가 UUID 형식인지, 감성 평가어가 없는지.
  - **merge_event_node**: (1) 편입/신규가 `Article.event_id`에 반영되는지, (2) 신규 `Event`가 `state["events_by_id"]`에 등록되는지, (3) 같은 배치의 동일 사건 둘째 기사가 첫째가 만든 신규 이벤트에 편입되는지(배치 내 중복 방지), (4) `embedding` 없는 기사가 skip되고 `analysis_completed=False`인지, (5) 한 기사 실패 시 나머지 계속.
  - **LLM 미사용**: 병합 경로가 `services/llm.py`를 호출하지 않음을 확인(canonical은 규칙 기반).
- **경계 케이스**: 후보 0건, 임계값 경계값, 회사 리스트 빈 기사, event_date·published_at 모두 없음, 배치 내 동일 사건 다건.
- **evals 연계**: 병합 품질(과병합/과분할: ARI·purity·과병합률)은 `evals/axes/event.py` + `evals/datasets/event_goldset.jsonl`로 정답셋 대조(모델 없이 결정적, event_merge.md §9). 여기 tests는 계약·점수·판정 분기 검증.
- 후속 TASK(06 importance·07 그래프·08 저장)가 `Article.event_id`·`Event`·`RecentEventProvider`를 재사용하므로, 필드·인터페이스를 바꾸면 TASK 01부터 함께 수정한다.

## 8. 구현 계약 요약 (I/O)
| 입력 | 출력 | 호출 가능 | 호출 금지 | 실패 시 |
|---|---|---|---|---|
| `state["articles"]`·`extracts_by_url` (+ 주입 `RecentEventProvider`) | Article.`embedding`·`event_id`, `state["events_by_id"]` | `services/embedder`·`event_merge`·`utils/similarity` | canonical LLM 생성, DB/backend 직접 호출 | 임계 미만→신규, 임베딩 없음 skip, provider 미주입=모두 신규 |
