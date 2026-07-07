# Technical Agent 통합 smoke (real KIS + Redis + OpenAI)

`docs/integration_smoke.md`

## 목적

Technical Agent의 **실제 외부 의존성 배선**(KIS 시세·Redis 캐시·OpenAI LLM·LangGraph e2e·내부
endpoint)이 살아있는지 사람이 수동으로 확인한다. 단위 테스트가 아니다 — **기본 `pytest`는 네트워크
0**이며, 이 도구는 **수동 실행 시에만** 외부 API를 호출한다.

- 스크립트: `src/agents/technical/scripts/smoke_technical_integration.py`
- pytest에 포함되지 않는다(파일명이 `test_` 아님, opt-in 테스트도 만들지 않음).

## 필요한 env (값이 아니라 존재만 확인)

`config.py` 기준 이름만 사용한다. 값은 `.env`에서만 읽고 **어디에도 출력하지 않는다**.

| 용도 | env |
|---|---|
| KIS 시세 | `KIS_API_KEY`, `KIS_API_SECRET`, `KIS_BASE_URL` |
| OpenAI | `OPENAI_API_KEY`, `OPENAI_MODEL`(예: `gpt-5.4-mini`) |
| Redis | `REDIS_URL` |

하나라도 없으면 해당 preflight는 `missing`을 찍고 **safe-fail**한다(required일 때 중단).

## 실행

```bash
cd ai

# 기본: env preflight → redis/openai/kis preflight → agent e2e → (옵션)cache 상태
uv run python src/agents/technical/scripts/smoke_technical_integration.py \
  --ticker 373220 --as-of 2026-07-06T00:00:00+09:00 --via-agent --check-cache

# endpoint(TestClient, 실제 wiring)까지
uv run python src/agents/technical/scripts/smoke_technical_integration.py \
  --ticker 373220 --as-of 2026-07-06T00:00:00+09:00 --via-agent --via-testclient --check-cache

# 특정 ticker의 D/W/M 캐시만 비우고 live KIS 경로 확인(전체 flush 아님, --yes 필수)
uv run python src/agents/technical/scripts/smoke_technical_integration.py \
  --ticker 373220 --as-of 2026-07-06T00:00:00+09:00 \
  --clear-cache-for-ticker --yes --via-agent --check-cache
```

주요 옵션: `--ticker`(기본 373220)·`--as-of`(기본 현재 UTC, 미래 금지)·`--query`·`--via-agent`(기본 on)·
`--via-testclient`(opt-in)·`--check-cache`·`--clear-cache-for-ticker`(+`--yes`)·
`--require-{redis,openai,kis}`(기본 true, `--no-require-*`로 해제)·`--timeout-seconds`(기본 55).

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
- (옵션) `endpoint`: `status=200`, `schema_ok=true`.
- 마지막 줄 `=== RESULT: PASS ===`.

## 실패 시 확인할 것

- `KIS_API_KEY`/`KIS_API_SECRET` `missing` → `.env`에 KIS 시세 자격이 없다(계좌번호와 다른 값).
- `[openai] config error` → `OPENAI_API_KEY`/`OPENAI_MODEL` 누락. `[openai] call failed=…Error` → 모델
  ID·네트워크·rate limit 확인(`smoke_openai_llm.py`로 격리 확인).
- `[redis] connected=false` → `REDIS_URL`·Redis 서버 상태.
- `[kis] fetch failed=…` → allowlist(BATTERY_TICKERS) 내 ticker인지, KIS 자격·시장 시간 확인.
- `[agent] run failed=DeadlineExceeded` → `--timeout-seconds` 상향 또는 LLM/KIS 지연 확인.

## 기본 pytest에는 포함되지 않는다

```bash
cd ai
ruff check src/agents/technical src/api src/main.py   # clean
pytest src                                            # 네트워크 0, 이 smoke는 수집되지 않음
```

opt-in pytest marker(`RUN_TECHNICAL_REAL_INTEGRATION=1`) 방식은 이번 범위 밖 — 필요해지면 후속에 추가.
