# Supervisor — 상위 orchestration (planning → execution → endpoint)

`ai/src/supervisor/`

사용자 질문을 해석하고, 필요 시 backend 종목 정본으로 context 를 보강한 뒤, **5개 서브에이전트
모두**에 대해 실행 가능 여부까지 포함한 결과를 만든다. **분석기가 아니다** — 집계/랭킹/투자의견/HTML/
검증/점수는 하지 않는다. backend DB 를 직접 만지지 않고, 종목 식별은 backend HTTP 경계로만 한다.

## 계층 (책임 분리 — 흐리지 말 것)
| 계층 | 파일 | 책임 |
|---|---|---|
| planning | `supervisor.py` (+`interpret`/`policy`/`rewrite`/`resolve_client`/`schemas`) | 질문 해석 · 조건부 resolve · 5 task envelope 생성 |
| execution | `executor.py` (+`agent_adapters`/`execution_schemas`) | 5 agent fan-out 실행 · skipped/failed/success 정리 |
| runtime | `runtime.py` | planning+execution 조립(`run_analysis`) · JSON 직렬화(`to_response_dict`) |
| endpoint | `../api/supervisor.py` | 외부 HTTP 입구 + dependency wiring (얇게) |

흐름: `POST /internal/supervisor/analyze` → `run_supervisor()` → `SupervisorDecision(tasks[5])`
→ `run_tasks()` → `results[5]` → JSON.

## Endpoint
- `POST /internal/supervisor/analyze` — body `{query, request_id?, trace_id?, as_of?}` (extra forbid).
  응답: `{original_query, resolution, tasks[5], results[5], request_id, trace_id, as_of}`.
- `GET /internal/supervisor/health`.
- **내부 전용**(`/internal`) — 인증은 후속(내부망 전제). 로직 재구현 없음: endpoint 는 입력 검증 ·
  id/as_of 수용·생성 · deps 주입 · `run_analysis` 호출 · 직렬화만 한다.

## Runtime context 주입 (endpoint 가 만들고 execution 은 받기만)
- `request_id`/`trace_id`: 요청 값이 있으면 그대로, 없으면 endpoint 가 생성(uuid). adapter 내부 임시
  fallback(`supervisor-exec`)에 의존하지 않는다(방어용으로만 남김).
- `as_of`: 요청 값 또는 endpoint 의 현재 UTC 시각. **timezone-aware(UTC)** 로 `ExecutionDeps.now` 에 주입.
- `deps`(`ExecutionDeps`): technical `llm_client`(dependency 계층이 생성, config 오류면 None →
  technical 만 실패 격리) · `fetcher`/`cache`/`trace_sink`(선택) · industry `graph`/`app`(선택).
  **adapter 는 의존성 생성자가 아니다** — endpoint 가 만들어 넘긴다.

## Technical 계약 (내 소유 범위)
- **technical public contract**: `TechnicalAgentInput{ticker(6자리), query, request_id, as_of}` +
  런타임 의존성 `llm_client`(필수)·`fetcher`/`trace_sink`/`cache`/`deadline`(선택).
- **supervisor → technical 로 넘기는 것**: `ticker=context.stock_code`, `query=rewritten_query`,
  `request_id`/`trace_id`/`as_of`=runtime context, `llm_client` 등 deps=endpoint 주입.
- **adapter 가 흡수하는 차이**: 없음(technical 은 supervisor-friendly 에 가깝다). `llm_client` 미주입
  시 import 전 `AdapterConfigError` → 해당 agent 만 failed(부분 성공 유지).

## adapter 별 입력 매핑 / 흡수 차이 (thin)
| agent | 공개 입력 | 매핑 | 흡수 차이 |
|---|---|---|---|
| technical | ticker + query (+llm) | stock_code + rewritten_query | 없음 |
| fundamental | FundamentalRequest(ticker, intent…) | ticker(+corp_name=stock_name) | free query 슬롯 없음 → query 미전달, intent 등 agent 기본값. **corp_code 미조립**(후속) |
| flow | stock_name/ticker + query | context + rewritten_query | base_date 등은 flow 내부 |
| news | question | rewritten_query | 종목 context 는 보조(불필요) |
| industry | question (Neo4j graph) | rewritten_query | graph/app 은 deps 주입, 미주입 시 adapter 가 build+close |

> 장기적으로 각 agent 가 supervisor-friendly 공개 계약을 갖는 게 맞다. 이번 단계는 agent 내부를
> 수술하지 않고 차이를 **adapter 안에서만** 최소 흡수한다.

## 정책 요약
- **can_run/reason**: technical/fundamental/flow=종목 의존(resolved 여야 실행), news/industry=선택
  (종목 없이도 실행). tool-error(status=error) ≠ not_found — reason `resolver_unavailable`로 구분.
- **skipped/failed/success**: can_run=false → 호출 없이 skipped / 호출 예외 → failed(부분 성공 허용,
  error 는 secret-safe: type + 개행제거·300자 상한, traceback/raw 미노출) / 성공 → output.
- **resolve tool-error(planning) ≠ agent execution failure(execution)** — 다른 층.

## 실행/후속 (이번 단계 범위)
- **순차 실행**으로 계약·구조를 먼저 안정화. 병렬화·상위 전체 deadline·per-call timeout orchestration은
  **후속**(구조는 병렬 확장 가능하게 유지). technical 내부 `deadline` 전달 경계만 `ExecutionDeps`에 마련.
- 실 KIS/OpenAI/backend 결합은 **수동 smoke** 로만: `scripts/smoke_supervisor.py`
  (`uv run python -m src.supervisor.scripts.smoke_supervisor "삼성전자 차트 어때?"`). pytest 미포함.

## 테스트 (실 네트워크 0)
fake resolver + fake adapter/llm + sys.modules 주입 + FastAPI dependency_overrides. planning/execution/
runtime/endpoint 각 계층 단위 검증. 실 agent 흐름은 수동 smoke.
