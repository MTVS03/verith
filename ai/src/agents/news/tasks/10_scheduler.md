# TASK 10 — 배치·삭제 스케줄러 (scheduler/rss_scheduler.py · scheduler/cleanup_scheduler.py · scheduler/__init__.py · config.py 발췌)

## 0. 개요
- **목적**: 배치 흐름(수집→분석→저장)과 7일 롤링 삭제를 **"언제 도는가"**로 묶어 **주기적으로 트리거**하는 스케줄러를 만든다. 배치 파이프라인의 노드·서비스(TASK 02~08)는 이미 "무엇을 하는가"를 구현했고, TASK 10은 그것을 **매시간 자동 실행**하는 얇은 트리거 계층이다(CLAUDE.md §3·§6). 구체적으로 (1) `rss_scheduler`가 매시간 배치 한 pass(`crawl → extract → sentiment → embedding → merge_event → importance → graph → save`)를 실행하고, (2) `cleanup_scheduler`가 주기적으로 **7일 롤링 삭제를 backend에 트리거**한다(`save_client.request_cleanup()`, 실제 168h·CASCADE 삭제는 backend). 스케줄러는 **타이밍·겹침 방지·예외 격리**만 담당하고, 수집·분석·저장·삭제의 실제 로직은 nodes/services/backend에 있다(절대규칙 2: nodes/scheduler는 얇게).
- **선행 작업**:
  - TASK 02(`services/rss.py`·`nodes/crawl.py`: 배치의 첫 단계. `config.RSS_CANDIDATES`·타임아웃·재시도. TASK 02 하위의존성에 "TASK 10 scheduler가 수집 트리거" 명시).
  - TASK 03~07(`nodes/extract.py`·`sentiment.py`·`embedding.py`·`merge_event.py`·`importance.py`·`graph.py`(graph_builder): 배치 파이프라인의 나머지 단계. 스케줄러는 이 노드들을 이은 **배치 파이프라인**을 invoke만 한다).
  - TASK 08(`services/backend/save_client.py`: `save_batch()`(배치 저장)·`request_cleanup()`(삭제 트리거). **TASK 08 §0 범위 밖에 "스케줄링(매시간 트리거)은 TASK 10. TASK 08은 저장·삭제 호출 함수를 제공하고, 언제 부를지는 스케줄러가 정한다" 명시**. cleanup의 호출 주체가 이 문서).
  - `state.py`(배치 파이프라인이 쓰는 `state` 컨테이너. `run_batch_once`가 초기 `state`를 만들어 파이프라인에 넘긴다).
- **산출물(파일)**:
  - `config.py`(발췌 추가) — 스케줄 설정(주기·타임존·기동 즉시 실행·겹침 상한·misfire 유예). 하드코딩 금지의 귀착점. **주기·타임존은 운영 환경 튜닝 대상(주석 표기)**.
  - `scheduler/__init__.py` — 스케줄러 엔트리포인트 재노출(`start_all`/`run_batch_once`/`run_cleanup_once`).
  - `scheduler/rss_scheduler.py` — 배치 스케줄러: `run_batch_once()`(배치 파이프라인 한 pass 실행·결과 로깅) + `start_rss_scheduler()`(매시간 반복 트리거·겹침 방지·예외 격리).
  - `scheduler/cleanup_scheduler.py` — 삭제 스케줄러: `run_cleanup_once()`(`save_client.request_cleanup()` 호출) + `start_cleanup_scheduler()`(주기 반복 트리거).
  - (선택) `scheduler/runner.py`(또는 `__main__`) — 두 스케줄러를 함께 기동하고 graceful shutdown을 처리하는 프로세스 엔트리포인트.
- **범위 밖(주의)**:
  - **실제 수집·크롤링·추출·감성·임베딩·병합·중요도·그래프 조립·저장 로직은 배치 파이프라인(TASK 02~08)**. 스케줄러는 그 파이프라인을 **invoke만** 하고, 노드 안으로 로직을 끌어오지 않는다(절대규칙 2). 배치 노드 배선(LangGraph 조립) 자체는 배치 그래프(별도, 노드 소유 TASK) — 스케줄러는 **조립된 배치 앱/러너를 부른다**.
  - **실제 삭제(168h 경과 판정·CASCADE·고아 Keyword/Person/Country 정리·Company 유지)는 backend**(SCHEMA_SPEC §5, erd.dbml 삭제 규칙). 스케줄러는 `request_cleanup()`으로 **타이밍만** 준다. 삭제 SQL/Cypher를 이 에이전트가 쓰지 않는다(절대규칙 1).
  - **DB 직접 접근 없음.** 저장은 `nodes/save.py`→`save_client.save_batch`(backend HTTP), 삭제는 `save_client.request_cleanup`(backend HTTP). 스케줄러 어디에도 SQL·Cypher·DB 드라이버·직접 HTTP-to-DB가 없다(절대규칙 1).
  - **질의(리포트) 흐름은 사용자 요청 시(graph.py→Supervisor, TASK 09)** 실행되며 스케줄과 무관하다. 스케줄러는 **배치·삭제**만 돌린다(리포트는 저장된 데이터를 읽기만, sequence §2).
  - **backend API 계약(엔드포인트·요청/응답)은 backend 소유**(api_contract.md 미확정, CLAUDE.md §8). 스케줄러는 `save_client`·배치 노드의 함수 계약만 본다.
  - **배포·프로세스 관리(systemd·supervisor·k8s CronJob·컨테이너 재시작)는 운영 영역**. 스케줄러는 in-process 주기 실행을 제공하되, `run_batch_once`/`run_cleanup_once`를 **순수 엔트리포인트로 노출**해 외부 OS cron이 직접 호출할 수도 있게 둔다(§2 스케줄링 라이브러리 격리).

### 0.1 하위 의존성 (⚠️ 수정 시 영향 범위)
이 단계는 배치·삭제의 **실행 타이밍**을 정한다. 아래를 바꾸면 파이프라인 처리량·데이터 신선도·운영 배포가 함께 영향받는다.

| 산출물 | 소비/연계 |
|---|---|
| `run_batch_once()` / `start_rss_scheduler()` | 배치 파이프라인(TASK 02~07 노드) + 저장(TASK 08 `save_batch`), 운영 배포(프로세스 기동) |
| `run_cleanup_once()` / `start_cleanup_scheduler()` | TASK 08 `request_cleanup` → backend CASCADE 삭제(SCHEMA_SPEC §5, pipeline_spec §10) |
| 스케줄 설정(주기·타임존·겹침 상한) | 데이터 신선도(수집 간격)·서버 부하·`published_at` KST 정합(TASK 02) |
| 순수 엔트리포인트(`run_batch_once`/`run_cleanup_once`) | 외부 OS cron·CI·수동 실행이 in-process 스케줄러 없이 직접 호출 |

## 1. 참고 문서
- `docs/sequence.md` §1(배치: `rss_scheduler`가 매시간 트리거 → nodes → services → backend 저장 [HTTP]), §3(삭제: `cleanup_scheduler`가 매시간 트리거 → services → backend [HTTP], backend가 CASCADE 삭제).
- `docs/pipeline_spec.md` §2(배치 흐름: RSS 수집→…→저장, 매시간 백그라운드), §10(7일 롤링 삭제), §7(저장은 backend 경유).
- `docs/erd.dbml` — 삭제 규칙(CASCADE: `published_at < now-168h` 기사 삭제 → Event 기사수 0이면 삭제 → 고아 Keyword/Person/Country 삭제 → Company 유지). 스케줄러가 트리거하는 backend 동작의 명세.
- `backend/db/models/news/SCHEMA_SPEC.md` §5(삭제 CASCADE: 168h·고아 정리·Company 유지 — 스케줄러가 부르는 `request_cleanup`의 backend측 상대).
- `CLAUDE.md` §3(배치 흐름 순서: `scheduler → crawl → extract → sentiment → embedding → merge_event → importance → save`), §6(`scheduler/` = 매시간 배치·7일 삭제), §2-1(DB 직접 접근 금지→backend HTTP), §2-2(nodes 얇게·로직은 services — scheduler에도 적용), §2-5(환각 금지·실패를 성공으로 위장 안 함), §5(7일 롤링·Company 유지), §7(외부 호출 타임아웃·재시도·예외 로깅·skip·설정값 하드코딩 금지).
- TASK 02 §0.1(`config.RSS_CANDIDATES`/타임아웃 → TASK 10 scheduler가 수집 트리거), TASK 08 §0·§3.3(`save_batch`·`request_cleanup`, 스케줄링은 TASK 10)·§4.2(실패 처리: 저장·삭제는 정확 보고, 다음 주기 재시도).

## 2. 배경 (왜)
- **왜 배치를 스케줄러로 주기 실행하나**: 여론·이벤트는 계속 갱신되므로 뉴스를 **매시간 백그라운드로** 수집·분석·저장해 둔다(pipeline_spec §2·§12, CLAUDE.md §3). 사용자 요청(질의 흐름)은 이 저장된 데이터를 **읽어 답하고 그리기만** 하므로(sequence §2), 수집·분석과 리포트 생성을 분리하면 리포트가 크롤링·모델 추론에 묶이지 않고 빠르며, 같은 데이터로 여러 질문에 답할 수 있다. 그 "매시간 백그라운드"를 실제로 돌리는 것이 이 스케줄러다.
- **왜 스케줄러는 얇은가(절대규칙 2)**: `scheduler/`는 "언제 도는가"(타이밍·겹침·예외 격리)만 담당하고, 실제 무거운 로직(크롤링·LLM·감성·임베딩·병합·중요도·그래프·저장)은 nodes/services에 있다(CLAUDE.md §2-2·§6). 스케줄러가 하는 일은 **초기 `state`를 만들어 배치 파이프라인을 invoke**하고 결과를 로깅하는 것뿐이다. 그래야 파이프라인을 스케줄러 없이(테스트·수동·외부 cron)도 실행할 수 있다.
- **왜 겹침을 방지하나(max_instances=1)**: 크롤링·LLM 추출이 느리면 한 배치가 1시간을 넘길 수 있다. 다음 주기가 겹쳐 시작하면 같은 RSS를 중복 처리하고, 병합 후보(최근 7일 같은 회사)를 두 실행이 동시에 만지며, 서버 부하가 폭증한다. `url` UNIQUE·그래프 MERGE로 **중복 저장 자체는 막히지만**(TASK 08 idempotency) 자원 낭비와 병합 경쟁은 남는다. 그래서 **이전 배치가 진행 중이면 이번 주기를 skip**(동시 실행 상한 1)한다.
- **왜 실패해도 스케줄러 루프를 죽이지 않나(§2-5·§7)**: 한 배치(또는 한 삭제)가 예외로 스케줄러 프로세스를 죽이면 **이후 모든 주기가 멈춘다**. 그래서 `run_batch_once`/`run_cleanup_once`는 예외를 **격리·로깅**하고 스케줄러 루프는 계속 돈다. 단 실패를 성공으로 위장하지 않는다 — 저장 실패는 `SaveResponse(ok=False)`로, 삭제 실패는 `CleanupResponse(ok=False)`로 정확히 로깅한다(TASK 08 §4.2, 성공 위장 금지).
- **왜 배치 전체를 즉시 재시도하지 않고 다음 주기에 맡기나**: 개별 외부 호출(RSS·크롤링·LLM·backend)은 각자 타임아웃·재시도를 이미 갖고(TASK 02/03/08 config, CLAUDE.md §7), 저장은 idempotent(`url` unique + MERGE)라 **다음 주기 재실행이 안전**하다. 배치 전체를 즉시 재시도하면 겹침·중복 부하만 는다. 그래서 스케줄러는 배치 단위 자체 재시도 루프를 두지 않고 **다음 주기 재시도**에 맡긴다(TASK 08 §4.2 "다음 주기 재시도"와 정합).
- **왜 삭제를 스케줄러가 "트리거만" 하고 실제 삭제는 backend인가(절대규칙 1)**: 168h 경과 판정·CASCADE(기사→Event→고아 노드)·Company 유지는 **DB 로직**이라 backend 소유다(SCHEMA_SPEC §5, erd.dbml). 이 에이전트는 삭제 SQL/Cypher를 쓰지 않고(절대규칙 1) `request_cleanup()`으로 **타이밍만** 준다. "무엇을 어떻게 지우는가"는 backend, "언제 지우라 신호를 주는가"는 스케줄러(관심사 분리, TASK 08 §2).
- **왜 배치와 삭제를 두 스케줄러로 분리하나(sequence §1·§3)**: 삭제는 저장과 독립적으로 돌 수 있고, 배치가 실패한 주기에도 오래된 데이터 정리는 진행돼야 한다. 관심사·주기·실패를 분리하면 하나가 막혀도 다른 하나가 계속 돈다.
- **왜 타임존을 config로 고정하나**: `published_at`이 KST-aware이고(TASK 02) 7일 롤링·매시간 경계 판정이 여기에 맞춰지므로, 스케줄 기준 타임존이 배포 서버의 로컬 타임존에 흔들리면 안 된다. `SCHEDULER_TIMEZONE`(기본 `Asia/Seoul`)을 config에 두어 환경과 무관하게 일관시킨다(하드코딩 금지, §7).
- **왜 스케줄링 라이브러리를 격리/교체 가능하게 두나**: 주기 실행 수단은 환경마다 다르다(APScheduler in-process, OS cron, Celery beat, k8s CronJob). `run_batch_once`/`run_cleanup_once`를 **부수효과 없는 순수 엔트리포인트**로 두면, in-process 스케줄러 없이도 외부 cron이 그 함수(또는 CLI)를 직접 부를 수 있다. 스케줄링 라이브러리 import는 `start_*` 함수에만 가두어, 수단을 바꿔도 실행 로직은 그대로다(CLAUDE.md §7 정신, TASK 08이 HTTP를 `client.py`에 가둔 것과 동일).
- **DB 접근 금지의 귀착점**: 스케줄러 어디에도 DB·HTTP-to-DB 호출이 없다. 저장은 `nodes/save.py`→`save_client`, 삭제는 `save_client.request_cleanup`, 둘 다 backend HTTP다(절대규칙 1).

## 3. 요구사항

### 3.1 `config.py` — 스케줄 설정 (하드코딩 금지)
1. **주기**: `BATCH_INTERVAL_MINUTES: int = 60`(배치 실행 주기 — 매시간, pipeline_spec §2), `CLEANUP_INTERVAL_MINUTES: int = 60`(삭제 트리거 주기). **주기는 운영 튜닝 대상 → 주석 표기.** 코드에 박지 않고 config에서 읽는다(§7).
2. **타임존**: `SCHEDULER_TIMEZONE: str = "Asia/Seoul"` — 스케줄 기준 타임존(`published_at` KST와 정합, TASK 02). 배포 서버 로컬 타임존에 흔들리지 않게 config·환경변수에서 읽는다.
3. **겹침 방지**: `BATCH_MAX_INSTANCES: int = 1`(동시 실행 상한 — 이전 배치 미완료 시 이번 주기 skip, §2), `BATCH_MISFIRE_GRACE_SEC: int = 300`(지연 유예 — 이 시간을 넘겨 놓친 실행은 skip). 삭제도 동일 정책을 둔다(`CLEANUP_MAX_INSTANCES` 등, 선택).
4. **기동 정책**: `BATCH_RUN_ON_START: bool = False`(프로세스 기동 즉시 1회 배치 실행 여부 — 개발·초기 적재용), `SCHEDULER_JITTER_SEC: int = 0`(시작 시각 분산 — 동시 부하 완화, 선택).
5. RSS 후보·타임아웃·재시도(TASK 02)·backend 접속(TASK 08)·모델 설정(TASK 03)은 **각 TASK의 config를 재사용**한다(스케줄러가 다시 정의하지 않는다). 이 절은 **"언제 도는가"** 값만 소유한다.

### 3.2 `scheduler/rss_scheduler.py` — 배치 스케줄러
> 매시간 배치 한 pass를 실행하는 트리거. 파이프라인 로직은 nodes/services(TASK 02~08). 스케줄러는 타이밍·겹침·예외 격리만.

1. **`run_batch_once() -> BatchRunResult`**: 초기 `state`를 만들어 **배치 파이프라인을 한 번 invoke**한다. 파이프라인 순서는 CLAUDE.md §3: `crawl → extract → sentiment → embedding → merge_event → importance → graph → save`. 노드 배선(LangGraph 조립)은 배치 그래프(별도) — 여기서는 **조립된 배치 앱/러너를 부른다**. 결과(저장 건수·`SaveResponse.ok`)를 **로깅**하고 반환한다.
   - **예외 격리**: 파이프라인 중 한 단계가 예외를 던져도 **`run_batch_once`가 삼켜 로깅**하고(스케줄러 루프 보호) 실패를 결과에 정확히 담는다(성공 위장 금지, §2-5). 개별 기사 실패 skip·저장 실패 `ok=False`는 각 노드(TASK 02~08)가 이미 처리하므로, 여기서는 파이프라인 전체를 감싸는 최후 방어만 둔다.
   - **대상 0건**: 수집 0건이면 예외 없이 통과(환각 금지: 없으면 없는 대로, TASK 02 §3.6). backend를 굳이 부르지 않아도 되는 처리는 각 노드가 담당.
2. **`start_rss_scheduler()`**: `BATCH_INTERVAL_MINUTES`·`SCHEDULER_TIMEZONE`으로 `run_batch_once`를 **주기 반복 등록**한다. **겹침 방지**: `BATCH_MAX_INSTANCES=1`(이전 실행 미완료면 이번 주기 skip)·`BATCH_MISFIRE_GRACE_SEC`. `BATCH_RUN_ON_START`면 등록 직후 1회 실행. 스케줄링 라이브러리(APScheduler 등) import는 **이 함수에만** 가둔다(§2 격리).
3. **`run_batch_once`는 부수효과 순수 엔트리포인트**: in-process 스케줄러 없이 외부 OS cron·수동 실행이 직접 부를 수 있게, 스케줄러 상태에 의존하지 않는다. 자체 배치 재시도 루프를 두지 않는다(다음 주기 재시도, §2).
4. 파이프라인 로직·backend 호출을 **여기 복제하지 않는다** — 노드/서비스만 조립·호출한다(절대규칙 2). 스케줄러는 배선된 배치 앱을 invoke할 뿐.

### 3.3 `scheduler/cleanup_scheduler.py` — 삭제 스케줄러
> 7일 롤링 삭제를 backend에 트리거만 한다. 실제 삭제(168h·CASCADE·Company 유지)는 backend(SCHEMA_SPEC §5).

1. **`run_cleanup_once() -> CleanupResponse`**: `save_client.request_cleanup()`(TASK 08)을 호출해 7일 롤링 삭제를 backend에 **트리거**한다. 반환 `CleanupResponse(ok, deleted_articles, deleted_events, message)`를 **로깅**한다. 삭제 판정·CASCADE·고아 정리는 backend가 수행하고, 스케줄러는 **호출 타이밍만** 준다(절대규칙 1). 실패 시 `ok=False`를 정확히 로깅(성공 위장 금지, §2-5) — 다음 주기 재시도.
2. **`start_cleanup_scheduler()`**: `CLEANUP_INTERVAL_MINUTES`·`SCHEDULER_TIMEZONE`으로 `run_cleanup_once`를 주기 반복 등록. 겹침 방지·misfire 유예·예외 격리는 배치와 동일 정책. 스케줄링 라이브러리 import는 이 함수에만.
3. **DB 삭제 로직 없음**: 이 파일에 SQL·Cypher·삭제 조건(168h·고아·Company 유지)이 없다 — 전부 backend(§2, 절대규칙 1). 스케줄러는 `save_client.request_cleanup`만 부른다.
4. `run_cleanup_once`도 순수 엔트리포인트(외부 cron 직접 호출 가능). 자체 재시도 루프 없음(다음 주기 재시도).

### 3.4 `scheduler/__init__.py` · (선택) `scheduler/runner.py` — 엔트리포인트
1. **재노출**: `run_batch_once`·`run_cleanup_once`·`start_rss_scheduler`·`start_cleanup_scheduler`를 `scheduler` 패키지에서 바로 쓸 수 있게 재노출한다.
2. **(선택) `start_all()` / `main()`**: 두 스케줄러를 함께 기동하고 **graceful shutdown**(SIGINT/SIGTERM에 스케줄러 정지·진행 중 배치 완료 대기)을 처리하는 프로세스 엔트리포인트. `python -m scheduler`(또는 `runner.py`)로 실행되게 둔다. 배포(systemd·컨테이너)가 이 엔트리포인트를 기동한다(운영 영역과의 접점).
3. 엔트리포인트는 **조립·기동만** — 파이프라인/삭제 로직을 넣지 않는다(얇게).

## 4. 인터페이스 / 구현 규칙

> 아래는 확정 시그니처(초안). 함수명·반환 타입은 이대로 구현하되, 설정값은 `config.py`에서 읽는다. **파이프라인 노드·저장·삭제 계약은 TASK 02~08을 재사용**한다. 스케줄링 라이브러리(APScheduler 등)는 예시이며 `start_*`에만 가둔다. 함수 본문(로직)은 비워 둔다.

```python
# config.py (발췌) — 스케줄 설정. "언제 도는가"만 소유(수집·backend 설정은 각 TASK 재사용). 하드코딩 금지.
BATCH_INTERVAL_MINUTES: int = 60          # 배치(수집·분석·저장) 실행 주기(분) — 매시간(pipeline_spec §2). 운영 튜닝
CLEANUP_INTERVAL_MINUTES: int = 60        # 7일 롤링 삭제 트리거 주기(분). 운영 튜닝
SCHEDULER_TIMEZONE: str = "Asia/Seoul"    # 스케줄 기준 타임존(published_at KST와 정합, TASK 02)
BATCH_MAX_INSTANCES: int = 1              # 동시 실행 상한(겹침 방지: 이전 배치 미완료 시 이번 주기 skip)
BATCH_MISFIRE_GRACE_SEC: int = 300        # 지연 유예(이 시간 넘겨 놓친 실행은 skip)
BATCH_RUN_ON_START: bool = False          # 프로세스 기동 즉시 1회 배치 실행(개발·초기 적재)
SCHEDULER_JITTER_SEC: int = 0             # 시작 시각 분산(동시 부하 완화, 선택)
```

```python
# scheduler/rss_scheduler.py — 배치 스케줄러(트리거만. 파이프라인 로직은 nodes/services).
# ⚠️ DB·backend를 직접 부르지 않는다. 배치 파이프라인(TASK 02~08)을 invoke만 한다(절대규칙 1·2).
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class BatchRunResult:
    ok: bool                    # 배치 pass 전체 성공 여부(저장 ok 반영)
    collected: int              # 수집 기사 수
    saved: int                  # 저장 건수(SaveResponse.saved)
    message: str | None = None  # 실패·skip 사유(정직 보고, 성공 위장 금지)

def run_batch_once() -> BatchRunResult:
    """배치 한 pass 실행: 초기 state → 배치 파이프라인 invoke
    (crawl → extract → sentiment → embedding → merge_event → importance → graph → save, CLAUDE.md §3).
    - 파이프라인 예외를 삼켜 로깅하고 결과에 정확히 담는다(스케줄러 루프 보호, 성공 위장 금지).
    - 수집 0건이면 예외 없이 통과. 자체 재시도 루프 없음(다음 주기 재시도).
    - 부수효과 순수 엔트리포인트(외부 cron·수동 실행이 직접 호출 가능)."""
    ...

def start_rss_scheduler():
    """run_batch_once를 BATCH_INTERVAL_MINUTES·SCHEDULER_TIMEZONE으로 주기 등록.
    겹침 방지(BATCH_MAX_INSTANCES=1)·misfire 유예. BATCH_RUN_ON_START면 즉시 1회.
    ⚠️ 스케줄링 라이브러리 import는 이 함수에만(교체 가능하게 격리)."""
    ...
```

```python
# scheduler/cleanup_scheduler.py — 삭제 스케줄러(backend에 트리거만. 실제 삭제는 backend).
# ⚠️ 삭제 SQL/Cypher·168h 판정·고아 정리 없음 — 전부 backend(SCHEMA_SPEC §5, 절대규칙 1).
from __future__ import annotations
from schemas.response import CleanupResponse
import services.backend.save_client as save_client

def run_cleanup_once() -> CleanupResponse:
    """save_client.request_cleanup()로 7일 롤링 삭제를 backend에 트리거.
    - 168h·CASCADE·고아 정리·Company 유지는 backend가 수행(스케줄러는 타이밍만).
    - 실패 시 CleanupResponse(ok=False) 정확히 로깅(성공 위장 금지). 다음 주기 재시도.
    - 부수효과 순수 엔트리포인트(외부 cron 직접 호출 가능)."""
    ...

def start_cleanup_scheduler():
    """run_cleanup_once를 CLEANUP_INTERVAL_MINUTES·SCHEDULER_TIMEZONE으로 주기 등록.
    겹침 방지·misfire 유예·예외 격리는 배치와 동일. 라이브러리 import는 이 함수에만."""
    ...
```

```python
# scheduler/__init__.py · (선택) scheduler/runner.py — 엔트리포인트(조립·기동만, 얇게)
from __future__ import annotations
from scheduler.rss_scheduler import run_batch_once, start_rss_scheduler
from scheduler.cleanup_scheduler import run_cleanup_once, start_cleanup_scheduler

def start_all():
    """두 스케줄러를 함께 기동 + graceful shutdown(SIGINT/SIGTERM에 정지·진행 배치 완료 대기).
    python -m scheduler(또는 runner.py)로 실행. 배포(systemd·컨테이너)가 이 엔트리포인트를 기동.
    조립·기동만 — 파이프라인/삭제 로직은 넣지 않는다."""
    ...
```

### 4.1 스케줄 오퍼레이션 요약
| 오퍼레이션 | 함수 | 주기 | 실제 로직 소유 | 스케줄러 책임 |
|---|---|---|---|---|
| 배치 실행 | `run_batch_once` / `start_rss_scheduler` | `BATCH_INTERVAL_MINUTES`(매시간) | 배치 파이프라인 노드(TASK 02~07) + 저장(TASK 08) | 초기 state·invoke·겹침 방지·예외 격리·로깅 |
| 7일 롤링 삭제 | `run_cleanup_once` / `start_cleanup_scheduler` | `CLEANUP_INTERVAL_MINUTES` | backend(168h·CASCADE·Company 유지, SCHEMA_SPEC §5) | `request_cleanup` 트리거 타이밍·예외 격리·로깅 |

### 4.2 실패·겹침 처리 규칙
| 상황 | 처리 | 이유 |
|---|---|---|
| 배치 파이프라인 중 예외 | `run_batch_once`가 삼켜 로깅 + `BatchRunResult(ok=False, message=…)` | 스케줄러 루프 보호(§2-5·§7). 다음 주기 재시도 |
| 저장 실패(`SaveResponse.ok=False`) | 성공 위장 안 함 → 결과·로그에 실패 명시 | 데이터 미저장은 진짜 실패(TASK 08 §4.2). idempotent라 다음 주기 안전 |
| 삭제 실패(`CleanupResponse.ok=False`) | 정확히 로깅 | 삭제 누락 정직 보고. 다음 주기 재시도 |
| 이전 배치 미완료 상태로 다음 주기 도래 | 이번 주기 **skip**(`BATCH_MAX_INSTANCES=1`) | 중복 수집·병합 경쟁·부하 폭증 방지(§2). 저장은 url unique+MERGE로 어차피 멱등 |
| misfire(유예 초과 지연) | skip | 밀린 실행이 몰려 돌지 않게(`BATCH_MISFIRE_GRACE_SEC`) |
| 수집 0건 | 예외 없이 통과 | 환각 금지: 없으면 없는 대로(TASK 02 §3.6) |

- 개별 외부 호출(RSS·크롤링·LLM·backend)의 타임아웃·재시도는 **각 TASK config**(02/03/08)가 담당. 스케줄러는 배치 단위 자체 재시도 루프를 두지 않는다(다음 주기 재시도).

## 5. 규칙·제약 (CLAUDE.md)
- **§2-1 DB 직접 접근 금지.** 스케줄러에 SQL·Cypher·DB 드라이버·직접 HTTP-to-DB가 없다. 저장은 `nodes/save.py`→`save_client`, 삭제는 `save_client.request_cleanup`(둘 다 backend HTTP). 삭제 판정·CASCADE는 backend.
- **§2-2 nodes/scheduler는 얇게, 로직은 services.** 스케줄러는 타이밍·겹침·예외 격리만. 파이프라인 로직(TASK 02~08)을 복제하지 않고 invoke만 한다.
- **§2-5 환각 금지 / 정직 보고.** 배치·삭제 실패를 성공으로 위장하지 않는다(`ok=False` 로깅). 수집 0건은 없는 대로 통과.
- **§3 배치 흐름 순서.** `crawl → extract → sentiment → embedding → merge_event → importance → graph → save`를 매시간 실행. HTML은 만들지 않는다(질의 흐름 소관).
- **§5 7일 롤링·Company 유지.** 삭제는 backend CASCADE(168h·고아 정리·Company 유지)를 스케줄러가 트리거.
- **§7 외부 호출 타임아웃·재시도·예외 로깅·설정값 하드코딩 금지.** 주기·타임존·겹침 상한은 config. 개별 호출 타임아웃·재시도는 각 TASK config 재사용. 스케줄링 라이브러리는 `start_*`에 격리.

## 6. 완료 조건 (DoD)
- [ ] `config.py`에 `BATCH_INTERVAL_MINUTES`·`CLEANUP_INTERVAL_MINUTES`·`SCHEDULER_TIMEZONE`·`BATCH_MAX_INSTANCES`·`BATCH_MISFIRE_GRACE_SEC`·`BATCH_RUN_ON_START`(+ 선택 jitter)가 정의됨. 주기·타임존 하드코딩 없음("운영 튜닝" 주석).
- [ ] `scheduler/rss_scheduler.py`의 `run_batch_once`가 초기 `state`로 배치 파이프라인(crawl→…→save)을 **invoke**하고 결과(`saved`·`ok`)를 로깅·반환함. 파이프라인 예외를 삼켜 스케줄러 루프를 죽이지 않고, 실패를 성공으로 위장하지 않음. 수집 0건 통과.
- [ ] `start_rss_scheduler`가 `BATCH_INTERVAL_MINUTES`·`SCHEDULER_TIMEZONE`으로 `run_batch_once`를 주기 등록하고, **겹침 방지(`BATCH_MAX_INSTANCES=1`)·misfire 유예**를 적용함. 스케줄링 라이브러리 import가 이 함수(층)에만 있음.
- [ ] `scheduler/cleanup_scheduler.py`의 `run_cleanup_once`가 `save_client.request_cleanup()`만 호출해 삭제를 **트리거**하고 `CleanupResponse`를 로깅함. **삭제 SQL/Cypher·168h 판정이 없음**(backend 소유). 실패는 `ok=False`로 정직 보고.
- [ ] `start_cleanup_scheduler`가 `CLEANUP_INTERVAL_MINUTES`·`SCHEDULER_TIMEZONE`으로 주기 등록·예외 격리함.
- [ ] `run_batch_once`·`run_cleanup_once`가 **부수효과 순수 엔트리포인트**(in-process 스케줄러 없이 외부 cron·수동 실행이 직접 호출 가능)이며 자체 재시도 루프가 없음(다음 주기 재시도).
- [ ] `scheduler/__init__.py`(및 선택 `runner.py`)가 엔트리포인트를 재노출하고, `start_all`/`main`이 두 스케줄러 기동 + graceful shutdown을 처리함(조립·기동만, 얇게).
- [ ] 스케줄러 어디에도 DB/HTTP-to-DB 호출·파이프라인 로직 복제가 없음(배치는 노드 invoke, 삭제는 `request_cleanup`만).

## 7. 테스트
- **대상 파일**: `tests/test_rss_scheduler.py`·`tests/test_cleanup_scheduler.py`(**신규**).
- **mock 전략**: 실제 네트워크·backend·모델·실시간 대기를 호출하지 않는다(CLAUDE.md: tests는 mock 기반). 배치 파이프라인(invoke 대상)·`save_client.request_cleanup`·스케줄링 라이브러리를 mock해 고정 결과/예외를 돌려주고, 시간은 가짜 시계/즉시 트리거로 대체한다.
  - **`run_batch_once`**: (1) 파이프라인 mock이 성공 `state`(저장 `ok=True`, saved=n) → `BatchRunResult(ok=True, saved=n)`, (2) 파이프라인 한 단계가 예외 → **예외 전파 없이** `ok=False`+사유 로깅(스케줄러 루프 보호, 성공 위장 안 함), (3) 저장 `ok=False` → 결과가 `ok=False`(정직 보고), (4) 수집 0건 → 예외 없이 통과, (5) **파이프라인을 invoke만** 하고 backend·모델을 직접 호출하지 않음.
  - **`start_rss_scheduler`**: 스케줄러 mock에 `BATCH_INTERVAL_MINUTES`·`SCHEDULER_TIMEZONE`·`BATCH_MAX_INSTANCES=1`·misfire 유예가 그대로 전달되는지. `BATCH_RUN_ON_START=True`면 등록 직후 1회 실행되는지. **겹침 시(이전 실행 미완료) 다음 주기 skip**(max_instances=1) 계약이 설정되는지.
  - **`run_cleanup_once`**: (1) `request_cleanup` mock 성공 → `CleanupResponse(deleted_articles, deleted_events)` 로깅, (2) 실패 mock → `ok=False` 정직 보고(예외로 루프 안 죽임), (3) **`save_client.request_cleanup`만 호출**하고 삭제 조건(168h·고아·Company 유지)을 스케줄러가 판정하지 않음.
  - **`start_cleanup_scheduler`**: 주기·타임존·예외 격리 설정 전달 확인.
  - **DB 미접근·로직 미복제**: 스케줄러 파일 어디에도 SQL·Cypher·DB 드라이버·HTTP 라이브러리 import가 없고(절대규칙 1), 파이프라인 로직(크롤링·LLM·감성·병합·중요도·그래프)을 복제하지 않음(invoke만) 확인.
  - **순수 엔트리포인트**: `run_batch_once`/`run_cleanup_once`가 스케줄러 상태 없이 직접 호출돼도 동작(외부 cron 대체 경로).
- **경계 케이스**: 이전 배치 미완료 중 다음 트리거(skip), 파이프라인 중간 예외, 저장/삭제 `ok=False`, 수집 0건, misfire(유예 초과), graceful shutdown 중 진행 배치 완료 대기, 타임존 변경 시 트리거 시각.
- **evals 연계**: 없음(스케줄링은 tests 레벨 계약). 다만 배치가 도는 주기·성공률이 그래프 구축/질의 품질 evals의 데이터 신선도 전제이므로, 주기·실패 정책이 바뀌면 픽스처 가정도 갱신.
- 이 문서는 배치 파이프라인(TASK 02~07)과 저장·삭제(TASK 08)를 **트리거**하므로, 파이프라인 노드 계약이나 `save_client`(`save_batch`/`request_cleanup`) 계약이 바뀌면 함께 수정한다(로직 소유는 각 TASK, 실행 타이밍은 여기).
