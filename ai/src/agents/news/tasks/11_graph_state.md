# TASK 11 — LangGraph 배선 & 상태 컨테이너 (graph.py · state.py)

## 0. 개요
- **목적**: 지금까지 TASK 02~09가 만든 **노드들을 실제 파이프라인으로 잇는 LangGraph 정의(`graph.py`)** 와, 노드들이 주고받는 **상태 컨테이너·키 계약(`state.py`)** 을 만든다. 두 흐름을 각각 조립한다: ① **배치 그래프**(`crawl → extract → sentiment → embedding → merge_event → importance → graph → save`, CLAUDE.md §3), ② **질의 그래프**(`query → report`, query_spec §1). `graph.py`는 Supervisor·스케줄러가 부를 **진입점**을 노출하고, `state.py`는 `state["…"]` 키들을 **단일 출처(single source of truth)** 로 타입화한다. 이 문서는 배선·상태만 담당하고, 각 단계의 실제 로직은 이미 TASK 02~09의 nodes/services에 있다(절대규칙 2: 여기도 얇게).
- **배경(왜 별도 TASK가 필요한가)**: TASK 10(스케줄러)은 "조립된 배치 앱/러너를 invoke"한다고 전제하고, TASK 09는 "`graph.py`(LangGraph 조립)은 별도"라며 미뤘다. 즉 **배선·상태를 소유하는 TASK가 없어** 배치·질의 흐름을 실제로 이을 주체가 비어 있었다(리뷰 지적). 이 TASK가 그 공백을 채운다. 또한 `state["articles"]`·`extracts_by_url`·`events_by_id`·`importance_by_event_id`·`graph_batch`·`html` 등 **키 계약이 여러 TASK에 흩어져** 있어, 여기서 한 곳에 모은다.
- **선행 작업**:
  - TASK 01(schemas: state에 담기는 모든 모델 `Article`·`ExtractResult`·`Event`·`GraphBatch`(TASK 07)·`SaveResponse`·`QueryUnderstanding`·`SubjectQueryResponse`·`Answer`·`ReportModel`).
  - TASK 02~08(배치 노드: `crawl_node`·`extract_node`·`sentiment_node`·`embedding_node`·`merge_event_node`·`importance_node`·`graph_node`·`save_node`, 그리고 TASK 08의 `BackendRecentEventProvider`·`BackendEventArticleStatsProvider`).
  - TASK 09(질의 노드: `query_node`·`report_node`).
  - TASK 10(스케줄러: `run_batch_once`가 이 문서의 **배치 앱**을 invoke. TASK 10은 이 문서에 의존).
- **산출물(파일)**:
  - `config.py`(발췌 추가) — 배선 옵션(LangGraph 사용 여부·체크포인터·recursion_limit 등 최소값). 하드코딩 금지의 귀착점.
  - `state.py`(**신규** — TASK 11 소유) — `BatchState`·`QueryState`(TypedDict, `total=False`) + **state 키 계약 표(§3.1)**. news 전용(자기완결).
  - `graph.py`(**신규** — TASK 11 소유) — `build_batch_graph()`·`build_query_graph()` + 컴파일된 앱·진입점(`run_batch(state)`·`run_query(question)`). Provider 주입 배선. Supervisor 진입점.
- **범위 밖(주의)**:
  - **각 단계의 실제 로직은 TASK 02~09**. `graph.py`는 노드를 **연결·순서 지정·Provider 주입**만 하고, 크롤링·추출·감성·병합·중요도·그래프·저장·질의·렌더 로직을 복제하지 않는다(절대규칙 2).
  - **스케줄링(언제 도는가)은 TASK 10**. 이 문서는 배치 앱을 **제공**하고, 주기 실행은 스케줄러가 한다.
  - **DB 접근·backend HTTP는 TASK 08**. `graph.py`는 backend를 직접 부르지 않고, 배치 노드에 **backend Provider(TASK 08)를 주입**할 뿐이다(절대규칙 1).
  - **Supervisor 자체·멀티에이전트 오케스트레이션은 veriθ 상위(범위 밖)**. 이 문서는 Supervisor가 호출할 **질의 진입점 시그니처**만 제공한다.

### 0.1 하위 의존성 (⚠️ 수정 시 영향 범위)
| 산출물 | 소비/연계 |
|---|---|
| `state.py`(`BatchState`/`QueryState` 키 계약) | TASK 02~09 전 노드(같은 키를 읽고 씀), 테스트 |
| 배치 앱(`run_batch`/컴파일된 그래프) | TASK 10 `run_batch_once`가 invoke |
| 질의 앱(`run_query`/컴파일된 그래프) | Supervisor 진입점, TASK 09 결과(`state["html"]`) |
| Provider 주입 배선 | TASK 05 `merge_event_node`·TASK 06 `importance_node`(주입받음), TASK 08 Provider 구현 |

## 1. 참고 문서
- `CLAUDE.md` §1(Supervisor는 graph.py만 호출·자기완결), §3(배치/질의 흐름 순서), §2-2(nodes/graph는 얇게·로직은 services), §6(폴더 역할: graph.py=LangGraph 정의·진입점, state.py=GraphState).
- `docs/pipeline_spec.md` §2(배치 흐름 순서), §11(질의 흐름), `docs/sequence.md` §1·§2(두 흐름의 노드·서비스 호출 순서).
- `docs/query_spec.md` §1(질의 4단계), §4(구현 위치).
- HANDOFF §5(폴더 구조: `graph.py`·`state.py` 최상위), §6 미확정("state.py가 news 전용인지 공유 GraphState인지 → 자기완결이면 전용").
- TASK 02~10의 노드 시그니처(`node(state) -> state`)·Provider 계약(TASK 05 §3.4·06 §3.2·08 §3.4)·스케줄러 invoke 지점(TASK 10 §3.2).

## 2. 배경 (왜)
- **왜 배선을 별도 파일(graph.py)로 두나**: 노드는 "무엇을"(각 단계), graph.py는 "어떤 순서로 잇는가"(위상)를 담당한다. 순서·분기·주입을 한 곳에 모으면 노드가 서로를 직접 부르지 않아 결합이 낮고, 스케줄러·Supervisor는 **진입점 하나**만 안다(CLAUDE.md §1).
- **왜 state를 타입화하나(dict 그대로 두지 않고)**: 노드들이 `state["extracts_by_url"]`처럼 문자열 키로 데이터를 주고받는데, 키·타입이 문서에 흩어지면 오타·타입 불일치가 런타임에야 드러난다. `state.py`에 `TypedDict`로 키 계약을 못박아 **단일 출처**로 두고, 노드는 이 타입을 참조한다. LangGraph 표준(`TypedDict` 상태)과도 맞는다.
- **왜 `total=False`인가**: 배치는 crawl→…→save로 진행하며 키가 **점진적으로** 채워진다(초기엔 `articles`만, 나중에 `graph_batch`). 모든 키를 처음부터 요구하면 안 되므로 부분 딕셔너리를 허용한다.
- **왜 news 전용 상태인가**: 이 에이전트는 자기완결이고(CLAUDE.md §1), 배치/질의 키가 news 도메인 전용이다. 공유 GraphState에 얹으면 다른 워커와 키가 충돌한다. HANDOFF §6의 "자기완결이면 전용"을 따른다. (Supervisor 경계는 진입점 in/out만 합의.)
- **왜 Provider를 graph.py에서 주입하나**: `merge_event_node`(TASK 05)·`importance_node`(TASK 06)는 `RecentEventProvider`·`EventArticleStatsProvider`를 **주입받도록** 설계됐다(테스트는 fake, 운영은 backend). 실제 backend Provider(TASK 08)를 노드에 꽂는 지점이 배선(graph.py)이다 — `functools.partial`(또는 클로저)로 노드를 `(state)->state` 형태로 감싸 LangGraph에 등록한다. 이렇게 하면 노드는 backend를 직접 import하지 않고(절대규칙 1 경계), 배선만 인프라를 안다.
- **왜 두 그래프를 분리하나**: 배치(수집·분석·저장, 백그라운드)와 질의(읽기·답변·렌더, 요청 시)는 트리거·입출력·수명이 다르다(pipeline_spec §2 vs §11). 별도 그래프로 두면 스케줄러는 배치만, Supervisor는 질의만 부른다.
- **DB 접근 금지의 귀착점**: graph.py는 노드를 잇고 Provider를 주입할 뿐, SQL·Cypher·HTTP-to-DB가 없다. backend 접근은 주입된 Provider(TASK 08)를 통해서만 노드 내부에서 일어난다.

## 3. 요구사항

### 3.1 `state.py` — 상태 키 계약 (단일 출처)
> 아래 표가 **state 키의 유일한 정의**다. 노드가 새 키를 쓰려면 여기부터 고친다. `TypedDict`, `total=False`.

**BatchState (배치 흐름)**
| 키 | 타입 | 채우는 노드 | 소비 노드 |
|---|---|---|---|
| `articles` | `list[Article]` | crawl(TASK 02) | extract·sentiment·embedding·merge·importance·graph·save |
| `extracts_by_url` | `dict[str, ExtractResult]` | extract(TASK 03) | merge_event·graph |
| `events_by_id` | `dict[str, Event]` | merge_event(TASK 05, 신규 이벤트) | importance·graph |
| `importance_by_event_id` | `dict[str, float]` | importance(TASK 06, 신규+편입) | graph·save |
| `graph_batch` | `GraphBatch` | graph(TASK 07) | save |
| `save_result` | `SaveResponse` | save(TASK 08) | (스케줄러 로깅) |

**QueryState (질의 흐름)**
| 키 | 타입 | 채우는 노드 | 소비 노드 |
|---|---|---|---|
| `question` | `str` | 진입(Supervisor 입력. 종목 프리셋도 문자열) | query |
| `understanding` | `QueryUnderstanding` | query(TASK 09, ①) | query·report |
| `query_response` | `SubjectQueryResponse` | query(②) | query·report |
| `answer` | `Answer` | query(④) | report |
| `report_model` | `ReportModel` | report(TASK 09) | report |
| `html` | `str` | report(최종 산출) | Supervisor 최종 출력 |

- 두 State는 별도 `TypedDict`(`total=False`)로 정의한다. 키·타입은 위 표와 **정확히 일치**해야 하며, TASK 02~09의 노드가 이 키를 사용한다(현재 노드 시그니처 `state: dict`는 이 TypedDict로 좁힌다).

### 3.2 `graph.py` — LangGraph 배선 & 진입점
1. **`build_batch_graph(providers=None) -> CompiledGraph`**: 배치 노드를 순서대로 등록·연결한다: `crawl → extract → sentiment → embedding → merge_event → importance → graph → save`(CLAUDE.md §3). `merge_event`·`importance`에는 **Provider를 주입**한다 — 기본은 TASK 08의 `BackendRecentEventProvider`·`BackendEventArticleStatsProvider`, 테스트는 fake를 주입(미주입 시 각 노드의 degrade 기본값, TASK 05/06). 주입은 `functools.partial(node, provider=…)`로 `(state)->state` 형태를 유지.
2. **`build_query_graph() -> CompiledGraph`**: 질의 노드 `query → report`를 연결(TASK 09). backend 접근은 `query` 노드 내부의 `query_client`(TASK 08)로만.
3. **진입점**:
   - `run_batch(state: BatchState | None = None) -> BatchState`: 초기 상태로 배치 그래프를 invoke. **TASK 10 `run_batch_once`가 이 함수(또는 컴파일된 배치 앱)를 부른다.**
   - `run_query(question: str) -> str`(또는 `QueryState`): 질의 그래프를 invoke해 `state["html"]`을 반환. **Supervisor가 이 진입점을 부른다**(CLAUDE.md §1: Supervisor는 graph.py만 호출).
4. **얇게**: graph.py는 노드 등록·엣지 정의·Provider 주입·컴파일만. 파이프라인/질의 로직을 복제하지 않는다(절대규칙 2). backend·LLM·DB를 직접 부르지 않는다(주입·노드 경유).
5. **결정성·격리**: 그래프 구조는 정적으로 정의(런타임 분기 최소). Provider·config는 인자·config에서 읽어 하드코딩하지 않는다.

### 3.3 `config.py` — 배선 옵션 (최소)
- `GRAPH_RECURSION_LIMIT`(선택), 체크포인터/영속화 사용 여부 등 LangGraph 실행 옵션. 없으면 라이브러리 기본. 배선 옵션 외 도메인 값은 각 TASK config 재사용(여기서 다시 정의하지 않는다).

## 4. 인터페이스 / 구현 규칙
> 확정 시그니처(초안). 노드·Provider 계약은 TASK 02~09를 재사용. 함수 본문(로직)은 비워 둔다. LangGraph는 예시이며 배선 라이브러리 import는 `graph.py`에 격리.

```python
# state.py — 상태 키 계약(단일 출처). TypedDict, total=False(점진 채움).
from __future__ import annotations
from typing import TypedDict
from schemas.article import Article, ExtractResult
from schemas.event import Event
from schemas.graph import GraphBatch
from schemas.response import SaveResponse, SubjectQueryResponse
from schemas.report import ReportModel
from schemas.query import QueryUnderstanding, Answer

class BatchState(TypedDict, total=False):
    articles: list[Article]
    extracts_by_url: dict[str, ExtractResult]
    events_by_id: dict[str, Event]
    importance_by_event_id: dict[str, float]
    graph_batch: GraphBatch
    save_result: SaveResponse

class QueryState(TypedDict, total=False):
    question: str
    understanding: QueryUnderstanding
    query_response: SubjectQueryResponse
    answer: Answer
    report_model: ReportModel
    html: str
```

```python
# graph.py — LangGraph 배선 & 진입점(얇게). 로직은 TASK 02~09 노드/서비스.
# ⚠️ backend·LLM·DB를 직접 부르지 않는다. merge_event·importance에 Provider(TASK 08)만 주입.
from __future__ import annotations
from state import BatchState, QueryState

def build_batch_graph(providers=None):
    """crawl → extract → sentiment → embedding → merge_event → importance → graph → save.
    merge_event·importance에 RecentEventProvider·EventArticleStatsProvider 주입
    (기본 backend, 테스트 fake). 컴파일된 배치 앱 반환."""
    ...

def build_query_graph():
    """query → report. backend 접근은 query 노드 내부 query_client로만. 컴파일된 질의 앱 반환."""
    ...

def run_batch(state: BatchState | None = None) -> BatchState:
    """배치 그래프 invoke(초기 state). TASK 10 run_batch_once가 호출."""
    ...

def run_query(question: str) -> str:
    """질의 그래프 invoke → state['html'] 반환. Supervisor 진입점(CLAUDE.md §1)."""
    ...
```

## 5. 규칙·제약 (CLAUDE.md)
- **§1 Supervisor는 graph.py만 호출.** 질의 진입점(`run_query`)을 노출하고 내부는 자기완결.
- **§2-1 DB 직접 접근 금지.** graph.py는 backend Provider(TASK 08)를 노드에 주입할 뿐 SQL·Cypher·HTTP-to-DB가 없다.
- **§2-2 nodes/graph는 얇게, 로직은 services.** graph.py는 등록·엣지·주입·컴파일만. state.py는 키 계약만.
- **§3 배치/질의 흐름 순서.** 배치=crawl→…→save, 질의=query→report를 그대로 배선.
- **§7 설정값 하드코딩 금지.** 배선 옵션은 config, 도메인 값은 각 TASK config 재사용. 배선 라이브러리 import는 graph.py에 격리(교체 가능).

## 6. 완료 조건 (DoD)
- [ ] `state.py`가 `BatchState`·`QueryState`(TypedDict, total=False)를 §3.1 표와 **정확히 일치**하는 키·타입으로 정의. state 키의 단일 출처가 됨.
- [ ] `graph.py`의 `build_batch_graph`가 `crawl → extract → sentiment → embedding → merge_event → importance → graph → save`를 순서대로 연결하고, `merge_event`·`importance`에 Provider를 주입(기본 backend, fake 교체 가능)함.
- [ ] `build_query_graph`가 `query → report`를 연결하고 backend 접근이 노드 내부 `query_client`로만 일어남.
- [ ] `run_batch`가 TASK 10 `run_batch_once`가 부를 수 있는 진입점이고, `run_query`가 Supervisor가 부를 진입점(→ `state["html"]`)임.
- [ ] graph.py가 backend·LLM·DB를 **직접 호출하지 않음**(주입·노드 경유). 파이프라인/질의 로직을 복제하지 않음(얇게).
- [ ] 배선 라이브러리 import가 `graph.py`에만 있고 config로 옵션을 읽음(하드코딩 없음).

## 7. 테스트
- **대상 파일**: `tests/test_graph.py`·`tests/test_state.py`(**신규**).
- **mock 전략**: 실제 backend·LLM·네트워크를 호출하지 않는다(CLAUDE.md: tests는 mock). 노드를 **fake/stub**로 대체해 배선(순서·주입·state 전파)만 검증한다.
  - **배치 배선**: fake 노드들로 `crawl→…→save` 순서가 지켜지고, 앞 노드가 실은 state 키를 뒤 노드가 받는지(예: `articles`→`extracts_by_url`→…→`graph_batch`→`save_result`). merge_event·importance에 **주입한 fake Provider가 실제로 노드에 전달**되는지.
  - **질의 배선**: `query→report`가 이어지고 `state["html"]`이 최종 산출되는지. `run_query`가 질문 문자열을 받아 HTML을 반환하는지.
  - **Provider 미주입 degrade**: Provider 없이 배치를 돌려도(모든 기사 신규·근사 importance) 예외 없이 완주하는지(TASK 05/06 degrade와 정합).
  - **얇음·미접근**: graph.py/state.py 어디에도 SQL·Cypher·DB 드라이버·HTTP 라이브러리 import가 없고(절대규칙 1), 파이프라인 로직 복제가 없음(노드 invoke만) 확인.
- **경계 케이스**: 빈 초기 state, 수집 0건이 끝까지 전파(각 노드 통과), 한 노드 실패 시 상위(스케줄러/질의 degrade) 처리와의 정합.
- **evals 연계**: 없음(배선은 tests 레벨). 다만 배치·질의가 실제로 이어져야 그래프 구축/질의 품질 evals가 데이터를 얻으므로, 키 계약이 바뀌면 픽스처도 갱신.
- 이 문서는 TASK 02~09의 노드와 TASK 10의 스케줄러를 잇는 **접합부**이므로, 노드 시그니처·state 키·Provider 계약이 바뀌면 함께 수정한다(로직 소유는 각 TASK, 배선·키 계약은 여기).

## 8. 구현 계약 요약 (I/O)
| 입력 | 출력 | 호출 가능 | 호출 금지 | 실패 시 |
|---|---|---|---|---|
| 초기 `BatchState` / `question` | 컴파일된 배치·질의 앱, `run_batch`/`run_query`(→`state["html"]`) | 노드(02~09) 등록·엣지, Provider(08) 주입 | backend·LLM·DB 직접 호출, 로직 복제 | Provider 미주입도 degrade로 완주 |
