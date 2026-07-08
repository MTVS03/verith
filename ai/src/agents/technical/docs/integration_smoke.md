# Technical Agent 통합 smoke (real KIS + Redis + OpenAI)

`docs/integration_smoke.md`

## 목적

Technical Agent의 **실제 외부 의존성 배선**(KIS 시세·Redis 캐시·OpenAI LLM·LangGraph e2e·내부
endpoint)이 살아있는지 사람이 수동으로 확인한다. 단위 테스트가 아니다 — **기본 `pytest`는 네트워크
0**이며, 이 도구는 **수동 실행 시에만** 외부 API를 호출한다.

- 스크립트: `src/agents/technical/scripts/smoke_technical_integration.py`
- pytest에 포함되지 않는다(파일명이 `test_` 아님, opt-in 테스트도 만들지 않음).

> **전체 종목 확장(현재 구조):** technical 은 `BATTERY_TICKERS` membership gate 로 종목을 막지 **않는다**.
> **형식상 유효한(6자리) ticker 를 기본 지원**하고(`config.is_supported_ticker`, §config.md 11), 종목명 정본은
> 내부 상수가 아니라 backend canonical(`TechnicalAgentInput.stock_name`) 이 담당한다. 데이터 부족·미상장은
> gate 가 아니라 `data_status` 로 표현한다. **`BATTERY_TICKERS` 는 지원 범위가 아니라 dev/smoke 표시명
> fallback** 일 뿐이다.
>
> **초기 실증 기준선(historical):** supervisor+technical real smoke 를 처음 통과시킨 종목은 2차전지 대표주
> — 373220 LG에너지솔루션·051910 LG화학(`source=KIS·data_status=normal·final_regime 산출`). 이는 "지원
> 범위가 10종"이라는 뜻이 아니라 **최초 회귀 기준선**이다. 아래 §계층별 real smoke 참고.
>
> **실효 universe:** 실제로 resolve 되는 종목은 backend `stocks`(resolver) 데이터에 종속한다. backend
> canonical stocks 가 전체 주권 universe 로 승격된 뒤에는 대표/확장 종목(예: 005930·005935)도 resolve 되며,
> smoke 도 그 종목으로 확장한다. 상위 Supervisor 경유 e2e(`resolver → planning → execution → technical`)는
> `src/supervisor/scripts/smoke_supervisor.py` 로 확인한다. 경계·정책: `src/supervisor/README.md`.

## 상위 Supervisor 경유 real smoke — 계층별 기준선 (운영 정본)

이 문서가 **real smoke 운영 정본**이다(무엇을 돌리고, 무엇을 성공으로 보고, 실패가 어느 계층인지). 두 도구를
구분한다: **① 계층 e2e** = `src/supervisor/scripts/smoke_supervisor.py`(resolve→planning→execution→technical,
아래 표 기준선) / **② technical 단독 의존성 smoke** = `smoke_technical_integration.py`(KIS·Redis·OpenAI 배선,
이 문서 나머지 절). 종목 지원은 allowlist reject 가 아니라 **형식검증 + resolver universe + `data_status`** 의
합이다 — 세 계층을 뭉뚱그리지 않는다.

```bash
cd ai
# backend(:8000 /api/stocks/resolve)·OpenAI·KIS 가 준비된 상태에서만(실 비용).
uv run python -m src.supervisor.scripts.smoke_supervisor "LG에너지솔루션 차트 어때?"
```

**계층별 smoke 기준선** (resolve 되려면 backend `stocks` 에 해당 종목이 있어야 함):

| 단계 | ticker | query | 기대 resolved | 성격 |
|---|---|---|---|---|
| 1차 회귀 | 373220 | `LG에너지솔루션 차트 어때?` | 373220 | 최초 기준선(대표주) |
| 2차 확장 | 005930 | `삼성전자 차트 어때?` | 005930 | canonical universe 확장 |
| 3차 확장/우선주 | 005935 | `삼성전자우 분석해줘` | 005935 | 우선주/애매 케이스 |

**성공 기준(계층 e2e):**
- resolver 가 **기대 stock_code 로 `resolved`**(status=resolved, stock.stock_code 일치).
- supervisor 가 **5 task 생성**(fundamental/technical/news/flow/industry fan-out).
- technical 이 **그 stock_code 로 진입**(`output.ticker` 일치).
- KIS data collect 성공(`data_status=normal`, `source=KIS`).
- `output` 구조 정상(`data_status`·`regime.final_regime`·`source` 유효 enum).
- raw secret/prompt/response·API key **미노출**(요약 필드만 출력).

**정상 실패 = 계층 분리(뭉개지 말 것).** 어느 계층이 죽었는지 아래로 읽는다:

| 증상 | 계층 | 해석 |
|---|---|---|
| resolver `not_found` | 종목 universe | backend `stocks` 에 종목 없음(seed/승격 문제). technical 문제 아님 |
| supervisor task `skipped` | planning/policy | can_run/planning 정책이 막음(종목 미해결 등) |
| technical `failed` — KIS token/fetch | 데이터 계층 | KIS 자격·시장시간·상장/거래 여부. `is_supported_ticker` reject 와 혼동 금지 |
| technical `failed` — OpenAI complete | LLM 계층 | `OPENAI_API_KEY`/모델 ID·rate limit |
| technical `failed` — `OUT_OF_SCOPE_TICKER` | 형식/정책 | 6자리 형식 위반·빈 값(allowlist 아님). resolver 를 거친 종목은 여기서 안 걸림 |
| news/flow/industry `failed` | 각 agent 환경 | Neo4j/뉴스/수급 등 **각 agent 의존성** 문제 — technical 결함이 아님 |

## 필요한 env (값이 아니라 존재만 확인)

`config.py` 기준 이름만 쓰고 **값은 어디에도 출력하지 않는다**(존재 여부만).

| 용도 | env |
|---|---|
| KIS 시세 | `KIS_API_KEY`, `KIS_API_SECRET`, `KIS_BASE_URL` |
| OpenAI | `OPENAI_API_KEY`, `OPENAI_MODEL`(예: `gpt-5.4-mini`) |
| Redis | `REDIS_URL` |

> **⚠️ env 출처(중요):** 스크립트는 **현재 프로세스의 환경변수 + `ai/.env`를 함께** 사용한다.
> `load_dotenv(override=False)`이므로 **이미 export된 셸 환경변수가 `.env`보다 우선**한다. 즉 `.env`에
> 없어도 셸에 export돼 있으면 preflight가 `present`로 잡고 **실 호출이 나간다**(비용). 실행 전
> `env | grep -E 'KIS_|OPENAI_|REDIS_'`(값 확인 시 주의) 등으로 **셸에 남은 자격을 반드시 확인**한다.

하나라도 없으면 해당 preflight는 `missing`을 찍고 **safe-fail**한다(required일 때 네트워크 호출 전 중단).

## 모드 (중복 외부 호출 최소화)

| 모드 | 실행 | 용도 |
|---|---|---|
| **기본(e2e)** | env → 입력검증 → Redis preflight → **agent e2e** → cache 상태 | 실제 파이프라인 점검. **OpenAI/KIS는 agent가 커버**하므로 단독 preflight를 생략(중복 호출 방지) |
| `--via-testclient` | 위 + endpoint(TestClient, 실 wiring) | endpoint 배선까지 점검 |
| `--preflight-only` | Redis/OpenAI/KIS **단독 preflight만**(agent/endpoint 실행 안 함) | 어느 의존성이 죽었는지 격리 점검 |

> 기본 모드는 OpenAI/KIS를 **agent 실행에서 한 번만** 친다. 의존성만 따로 찍어보려면 `--preflight-only`.

## 실행

```bash
cd ai

# 기본 e2e: env → 입력검증 → Redis → agent(real KIS+OpenAI) → cache 상태
uv run python src/agents/technical/scripts/smoke_technical_integration.py \
  --ticker 373220 --as-of 2026-07-06T00:00:00+09:00 --via-agent --check-cache

# endpoint(TestClient, 실제 wiring)까지
uv run python src/agents/technical/scripts/smoke_technical_integration.py \
  --ticker 373220 --as-of 2026-07-06T00:00:00+09:00 --via-agent --via-testclient --check-cache

# 의존성 단독 점검(agent 실행 안 함 — 중복 호출 최소)
uv run python src/agents/technical/scripts/smoke_technical_integration.py \
  --ticker 373220 --preflight-only

# 특정 ticker의 D/W/M 캐시만 비우고 live KIS 경로 확인(전체 flush 아님, --yes 필수)
uv run python src/agents/technical/scripts/smoke_technical_integration.py \
  --ticker 373220 --as-of 2026-07-06T00:00:00+09:00 \
  --clear-cache-for-ticker --yes --via-agent --check-cache
```

주요 옵션: `--ticker`(기본 373220)·`--as-of`(기본 현재 UTC, 미래 금지)·`--query`(기본 ticker에서 파생)·
`--via-agent`(기본 on)·`--via-testclient`(opt-in)·`--preflight-only`·`--check-cache`·
`--clear-cache-for-ticker`(+`--yes`, 없으면 네트워크 호출 전 실패)·`--require-{redis,openai,kis}`(기본 true,
`--no-require-*`로 해제)·`--timeout-seconds`(기본 55).

**입력 검증(fail-fast)**: 형식 오류(6자리 아님) ticker·미래 as_of는 **어떤 네트워크/비용 호출
전에** 명확한 메시지로 중단한다.

## ⚠️ 네트워크/비용 주의

- 실제 KIS 시세·**OpenAI(토큰 비용)**·Redis를 호출한다. CI/기본 pytest에서는 절대 실행하지 않는다.
- `--via-testclient`도 dependency override 없이 **실제 KIS/OpenAI/Redis**를 쓴다(opt-in 전용).

## secret 출력 금지 정책

스크립트는 다음을 **절대 출력하지 않는다**: API key/secret/token·Redis URL·raw prompt·raw OpenAI
response·interpretation 전문·raw candles. 대신 `present`/`missing`·개수·길이·enum·`usage`·`duration_ms`·
`trace_events` 수만 출력한다. 예외 메시지는 `type(exc).__name__`만 남긴다.

## Redis clear 주의

- `--clear-cache-for-ticker`는 **해당 ticker의 D/W/M 키 3개만** 삭제한다
  (`ohlcv:daily:{ticker}`·`ohlcv:weekly:{ticker}`·`ohlcv:monthly:{ticker}`).
- **`flushdb`·전체 key scan·전체 초기화는 하지 않는다.** 삭제 전 대상 키 이름을 출력하고,
  **`--yes` 없이는 삭제하지 않는다**.

## 성공 기준

- `env preflight`: 필요한 env가 모두 `present`.
- `redis`: `connected=true`, ping 성공.
- `openai`: `success=true`, 응답 비어있지 않음(model·usage·duration 출력).
- `kis`: `daily_candles > 0`, 최신 date 출력.
- `agent`: `success=true`(request_id/ticker 일치·trace_id·data_status·source·final_regime·
  interpretation·verification 존재). `charts` 개수·`signal_score`·`trace_events` 출력.
  - **`data_collect_source`**: `kis`=이번 run이 실제 KIS 조회 / `cache`=캐시 hit(KIS 미호출) /
    `cache_stale`=stale 폴백. `source` 라벨(항상 `KIS`)로는 구분이 안 되므로 이 값으로 판정한다.
    (cache hit을 보려면 1회 채운 뒤 fresh TTL 15분 안에 재실행 → `data_collect_source=cache` 확인.)
- (옵션) `endpoint`: `status=200`, `schema_ok=true`.
- 마지막 줄 `=== RESULT: PASS ===`.

## 실패 시 확인할 것

- `KIS_API_KEY`/`KIS_API_SECRET` `missing` → `.env`에 KIS 시세 자격이 없다(계좌번호와 다른 값).
- `[openai] config error` → `OPENAI_API_KEY`/`OPENAI_MODEL` 누락. `[openai] call failed=…Error` → 모델
  ID·네트워크·rate limit 확인(`smoke_openai_llm.py`로 격리 확인).
- `[redis] connected=false` → `REDIS_URL`·Redis 서버 상태.
- `[kis] fetch failed=…` → ticker 형식(6자리)·KIS 자격·시장 시간·해당 종목 상장/거래 여부 확인.
- `[agent] run failed=DeadlineExceeded` → `--timeout-seconds` 상향 또는 LLM/KIS 지연 확인.

## 기본 pytest에는 포함되지 않는다

```bash
cd ai
ruff check src/agents/technical src/api src/main.py   # clean
pytest src                                            # 네트워크 0, 이 smoke는 수집되지 않음
```

opt-in pytest marker(`RUN_TECHNICAL_REAL_INTEGRATION=1`) 방식은 이번 범위 밖 — 필요해지면 후속에 추가.
