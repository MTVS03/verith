"""수동 통합 smoke — real KIS + Redis + OpenAI로 Technical Agent end-to-end 검증.

목적(단위 테스트 아님): 실제 외부 의존성 배선이 살아있는지 사람이 확인한다. 기본 `pytest`는
네트워크 0이며, 이 스크립트는 **수동 실행 시에만** KIS/Redis/OpenAI를 호출한다.

⚠️ 비용/네트워크: 실제 KIS 시세·OpenAI(토큰 비용)·Redis를 호출한다.
⚠️ env 출처: 현재 프로세스 환경변수 + `ai/.env`를 함께 쓰며 `load_dotenv(override=False)`라
**이미 export된 셸 환경변수가 `.env`보다 우선**한다(셸에 남은 자격이 실 호출을 유발할 수 있음).
secret-safe: API key·secret·token·Redis URL·raw prompt·raw response·interpretation 전문·raw candles를
**절대 출력하지 않는다**(존재 여부·개수·길이·enum·usage·duration만).
안전: allowlist 밖 ticker·미래 as_of·`--clear-cache-for-ticker` without `--yes`는 **네트워크 호출 전** 중단.

실행:
  cd ai
  uv run python src/agents/technical/scripts/smoke_technical_integration.py \
    --ticker 373220 --as-of 2026-07-06T00:00:00+09:00 --via-agent --check-cache
  # endpoint 경로까지: --via-testclient
  # 특정 ticker cache만 비우기(전체 flush 아님, --yes 필수): --clear-cache-for-ticker --yes

상세: `docs/integration_smoke.md`.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# 스탠드얼론 스크립트라 ai/ 를 sys.path에 올려 `src...` import가 되게 한다(parents[4] = ai/).
_AI_ROOT = Path(__file__).resolve().parents[4]
if str(_AI_ROOT) not in sys.path:
    sys.path.insert(0, str(_AI_ROOT))

import os  # noqa: E402

# ai/.env를 로드해 os.getenv가 .env를 반영하게 한다(config 로더도 동일하게 load_dotenv 한다).
# 실제 환경변수가 .env보다 우선(override=False). 값은 출력하지 않는다.
from dotenv import load_dotenv  # noqa: E402

_ENV_FILE = _AI_ROOT / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=False)

from src.agents.technical.config import (  # noqa: E402
    BATTERY_TICKERS,
    CACHE_KEY_BY_PERIOD,
    KIS_PERIOD_DAILY,
    KIS_PERIOD_MONTHLY,
    KIS_PERIOD_WEEKLY,
    OPENAI_API_KEY_ENV,
    OPENAI_MODEL_ENV,
    TECHNICAL_AGENT_TIMEOUT_SECONDS,
)
from src.agents.technical.agent import run_technical_agent  # noqa: E402
from src.agents.technical.observability.trace_logger import InMemoryTraceSink  # noqa: E402
from src.agents.technical.runtime.deadline import Deadline  # noqa: E402
from src.agents.technical.schemas.contracts import TechnicalAgentInput  # noqa: E402
from src.agents.technical.services.cache_service import as_of_identity, default_cache  # noqa: E402
from src.agents.technical.services.kis_client import (  # noqa: E402
    KisError,
    fetch_multi_timeframe_ohlcv,
    normalize_end_date,
)
from src.agents.technical.services.openai_llm_client import default_openai_client  # noqa: E402

# 존재 여부만 확인할 env(값은 절대 출력하지 않는다). config.py 기준 이름.
_KIS_ENV = ("KIS_API_KEY", "KIS_API_SECRET", "KIS_BASE_URL")
_OPENAI_ENV = (OPENAI_API_KEY_ENV, OPENAI_MODEL_ENV)  # OPENAI_API_KEY / OPENAI_MODEL
_REDIS_ENV = ("REDIS_URL",)
_DWM = (KIS_PERIOD_DAILY, KIS_PERIOD_WEEKLY, KIS_PERIOD_MONTHLY)


def _default_query(ticker: str) -> str:
    """기본 query는 payload ticker에서 파생한다(하드코딩 종목과 불일치 방지)."""
    return f"{ticker} 최근 기술적 흐름과 주요 리스크 관찰점을 분석해줘"


def _present(name: str) -> bool:
    return bool((os.getenv(name) or "").strip())


def _cache_keys(ticker: str) -> list[str]:
    """이 ticker의 D/W/M Redis cache key 목록(값 아님, 키 이름만 — 삭제 대상 명시용)."""
    return [CACHE_KEY_BY_PERIOD[tf].format(ticker=ticker) for tf in _DWM]


def _raw_redis():
    """preflight/조회/삭제용 raw Redis client(REDIS_URL). 없으면 None. URL은 출력하지 않는다."""
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        import redis
        return redis.Redis.from_url(url)
    except Exception as exc:  # noqa: BLE001 - 연결 실패는 상위에서 safe-fail
        print(f"[redis] client 생성 실패: {type(exc).__name__}")
        return None


# ── preflight ─────────────────────────────────────────────────────────────────
def env_preflight(args) -> bool:
    """필요한 env 존재 여부만 출력. required인데 없으면 False(중단)."""
    print("=== env preflight (존재 여부만, 값 미출력) ===")
    ok = True
    checks = [
        ("KIS", _KIS_ENV, args.require_kis),
        ("OpenAI", _OPENAI_ENV, args.require_openai),
        ("Redis", _REDIS_ENV, args.require_redis),
    ]
    for label, names, required in checks:
        missing = [n for n in names if not _present(n)]
        for n in names:
            print(f"[preflight] {n}: {'present' if _present(n) else 'missing'}")
        if missing and required:
            print(f"[preflight] {label} credentials are required for real integration smoke "
                  f"(missing: {missing}).")
            ok = False
    return ok


def redis_preflight(ticker: str) -> bool:
    """Redis 연결·ping·해당 ticker D/W/M key 존재/TTL. URL·전체 scan·flush 없음."""
    print("=== redis preflight ===")
    r = _raw_redis()
    if r is None:
        print("[redis] connected=false (REDIS_URL 미설정 또는 client 생성 실패)")
        return False
    try:
        pong = r.ping()
    except Exception as exc:  # noqa: BLE001
        print(f"[redis] connected=false ping_error={type(exc).__name__}")
        return False
    print(f"[redis] connected=true ping={bool(pong)}")
    for tf in _DWM:
        key = CACHE_KEY_BY_PERIOD[tf].format(ticker=ticker)
        try:
            exists = bool(r.exists(key))
            ttl = r.ttl(key) if exists else None
        except Exception as exc:  # noqa: BLE001
            print(f"[redis] {tf} check_error={type(exc).__name__}")
            continue
        print(f"[redis] {tf}_cache={'present' if exists else 'miss'} ttl={ttl}")
    return True


def openai_preflight(timeout: float) -> bool:
    """기존 OpenAiLlmClient로 짧은 호출. raw response/prompt 미출력 — 길이·usage·duration만."""
    print("=== openai preflight ===")
    try:
        client = default_openai_client(deadline=Deadline.after(timeout))
    except RuntimeError as exc:  # config error(키/모델 누락) — 메시지엔 secret 없음
        print(f"[openai] config error: {exc}")
        return False
    started = time.perf_counter()
    try:
        text = client.complete("연결 확인용입니다. '연결 확인 완료'라고만 한 줄로 답하세요.")
    except Exception as exc:  # noqa: BLE001 - LlmCallError 등, 메시지는 type 이름만 안전
        print(f"[openai] call failed: {type(exc).__name__}")
        return False
    duration_ms = int((time.perf_counter() - started) * 1000)
    print(f"[openai] success={bool(text and text.strip())} model={client.model} "
          f"duration_ms={duration_ms} response_chars={len(text)} usage={client.last_usage}")
    return bool(text and text.strip())


def kis_preflight(ticker: str, as_of_dt: datetime) -> bool:
    """기존 KIS fetcher로 D/W/M 조회(새 endpoint 추측 없음). daily 개수·최신 date만 출력."""
    print("=== kis preflight ===")
    try:
        end_date = normalize_end_date(as_of_dt)  # 미래 as_of 등은 ValueError (상위에서 이미 fail-fast)
        ohlcv = fetch_multi_timeframe_ohlcv(ticker, end_date=end_date)
    except (KisError, ValueError) as exc:
        print(f"[kis] fetch failed: {type(exc).__name__}")  # traceback 대신 type 이름만
        return False
    daily = list(ohlcv.get(KIS_PERIOD_DAILY, []))
    latest = daily[-1].date if daily else None
    print(f"[kis] daily_candles={len(daily)} weekly={len(ohlcv.get(KIS_PERIOD_WEEKLY, []))} "
          f"monthly={len(ohlcv.get(KIS_PERIOD_MONTHLY, []))} latest_date={latest}")
    return bool(daily)


# ── cache clear (해당 ticker D/W/M 키만) ──────────────────────────────────────
def clear_cache_for_ticker(ticker: str) -> bool:
    """해당 ticker의 D/W/M 키 3개만 삭제(전체 flush 아님). 호출 전 main에서 --yes를 확인한다."""
    print("=== clear cache for ticker (D/W/M 키만 — 전체 flush 아님) ===")
    keys = _cache_keys(ticker)
    print(f"[cache] delete 대상 keys={keys}")  # 키 이름만(secret 아님)
    r = _raw_redis()
    if r is None:
        print("[cache] Redis 미가용 — 삭제 생략")
        return False
    try:
        deleted = r.delete(*keys)
    except Exception as exc:  # noqa: BLE001
        print(f"[cache] delete_error={type(exc).__name__}")
        return False
    print(f"[cache] deleted={deleted}")
    return True


def cache_behavior(ticker: str, as_of_dt: datetime) -> None:
    """agent 실행 후 D/W/M cache status(fresh/stale/miss) + TTL. entry payload는 출력 안 함."""
    print("=== cache behavior ===")
    cache = default_cache()
    if cache is None:
        print("[cache] default_cache=None (REDIS_URL 미설정) — cache 검사 생략")
        return
    as_of_id = as_of_identity(normalize_end_date(as_of_dt))
    now = datetime.now(timezone.utc)
    r = _raw_redis()
    for tf in _DWM:
        look = cache.get(ticker, tf, as_of_id, now=now)
        key = CACHE_KEY_BY_PERIOD[tf].format(ticker=ticker)
        ttl = None
        if r is not None:
            try:
                ttl = r.ttl(key)
            except Exception:  # noqa: BLE001
                ttl = None
        print(f"[cache] {tf} status={look.status} ttl={ttl}")


# ── agent e2e ─────────────────────────────────────────────────────────────────
def agent_e2e(args, as_of_dt: datetime) -> bool:
    """real KIS + Redis + OpenAI로 run_technical_agent 실행. output 요약만(전문/원문 미출력)."""
    print("=== agent end-to-end ===")
    deadline = Deadline.after(args.timeout_seconds)
    try:
        llm = default_openai_client(deadline=deadline)
    except RuntimeError as exc:
        print(f"[agent] openai config error: {exc}")
        return False
    sink = InMemoryTraceSink()
    request_id = f"smoke-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8]}"
    payload = TechnicalAgentInput(
        request_id=request_id, ticker=args.ticker, query=args.query, as_of=as_of_dt)
    try:
        out = run_technical_agent(
            payload, llm_client=llm, cache=default_cache(), trace_sink=sink, deadline=deadline)
    except Exception as exc:  # noqa: BLE001 - 실패 원인은 type 이름만(secret 없음)
        print(f"[agent] run failed: {type(exc).__name__}")
        return False

    # 계약 필드 검증(요약만 출력, interpretation 전문·candles·prompt/response 미출력).
    checks = {
        "request_id_match": out.request_id == request_id,
        "ticker_match": out.ticker == args.ticker,
        "trace_id_present": bool(out.trace_id),
        "data_status_present": out.data_status is not None,
        "source_present": bool(out.source),
        "final_regime_present": out.regime is not None and out.regime.final_regime is not None,
        "interpretation_present": bool(out.interpretation and out.interpretation.text),
        "verification_present": out.verification is not None,
    }
    # data_collect 노드 trace로 이번 run이 실제로 KIS를 쳤는지/캐시를 썼는지 구분(source 라벨만으론 불가).
    dc = next((e for e in sink.events
               if e.get("node") == "data_collect" and e["event_type"] == "node_end"), None)
    data_source = dc["output_summary"].get("source") if dc else None  # cache / kis / cache_stale

    signal_score = out.signal.signal_score if out.signal else None
    print(f"[agent] success={all(checks.values())} request_id={out.request_id} ticker={out.ticker}")
    print(f"[agent] data_status={out.data_status.value} source={out.source} "
          f"final_regime={out.regime.final_regime.value}")
    print(f"[agent] data_collect_source={data_source}  # cache=KIS 미호출(cache hit) / kis=live 조회")
    print(f"[agent] signal_score={signal_score} charts={len(out.charts)} "
          f"interpretation_chars={len(out.interpretation.text)} trace_id={out.trace_id}")
    print(f"[agent] verification_outcome={out.verification.outcome.value} trace_events={len(sink.events)}")
    failed = [k for k, v in checks.items() if not v]
    if failed:
        print(f"[agent] FAILED checks: {failed}")
    return not failed


# ── endpoint (TestClient, 의존성 override 없이 실 wiring) ──────────────────────
def endpoint_smoke(args, as_of_dt: datetime) -> bool:
    print("=== endpoint smoke (TestClient, 실제 KIS/OpenAI/Redis wiring) ===")
    try:
        from fastapi.testclient import TestClient
        from src.main import app
    except Exception as exc:  # noqa: BLE001
        print(f"[endpoint] app import 실패: {type(exc).__name__}")
        return False
    body = {
        "request_id": f"smoke-ep-{uuid.uuid4().hex[:8]}",
        "ticker": args.ticker,
        "query": args.query,
        "as_of": as_of_dt.isoformat(),
    }
    r = TestClient(app).post("/internal/technical/analyze", json=body)
    if r.status_code != 200:
        # error envelope의 code만 출력(메시지엔 secret 없지만 code만으로 충분)
        code = r.json().get("error", {}).get("code") if r.headers.get("content-type", "").startswith(
            "application/json") else None
        print(f"[endpoint] status={r.status_code} error_code={code}")
        return False
    data = r.json()
    keys_ok = all(k in data for k in ("request_id", "ticker", "trace_id", "data_status", "source",
                                      "regime", "charts", "interpretation", "verification"))
    print(f"[endpoint] status=200 schema_ok={keys_ok} request_id={data.get('request_id')} "
          f"data_status={data.get('data_status')} charts={len(data.get('charts', []))}")
    return keys_ok


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser(description="Technical Agent real integration smoke (수동 전용)")
    p.add_argument("--ticker", default="373220", help="allowlist 내 종목(기본 373220)")
    p.add_argument("--as-of", default=None, help="ISO8601 분석 기준 시각(기본: 현재 UTC). 미래 금지")
    p.add_argument("--query", default=None, help="기본: '{ticker} 최근 기술적 흐름...' 자동 생성")
    p.add_argument("--via-agent", action="store_true", default=True, help="run_technical_agent e2e(기본 on)")
    p.add_argument("--no-via-agent", dest="via_agent", action="store_false")
    p.add_argument("--via-testclient", action="store_true", help="endpoint TestClient 경로(opt-in)")
    p.add_argument("--check-cache", action="store_true", help="Redis D/W/M status/TTL 확인")
    p.add_argument("--preflight-only", action="store_true",
                   help="Redis/OpenAI/KIS 단독 preflight만(agent/endpoint 실행 안 함)")
    p.add_argument("--clear-cache-for-ticker", action="store_true", help="해당 ticker D/W/M 키만 삭제(--yes 필요)")
    p.add_argument("--yes", action="store_true", help="파괴적 작업(cache 삭제) 확인")
    p.add_argument("--require-redis", action="store_true", default=True)
    p.add_argument("--no-require-redis", dest="require_redis", action="store_false")
    p.add_argument("--require-openai", action="store_true", default=True)
    p.add_argument("--no-require-openai", dest="require_openai", action="store_false")
    p.add_argument("--require-kis", action="store_true", default=True)
    p.add_argument("--no-require-kis", dest="require_kis", action="store_false")
    p.add_argument("--timeout-seconds", type=float, default=TECHNICAL_AGENT_TIMEOUT_SECONDS)
    args = p.parse_args()

    # 기본 query는 payload ticker에서 파생(--ticker와 질문 종목 불일치 방지).
    args.query = args.query or _default_query(args.ticker)

    # as_of 파싱(기본: 현재 UTC). 파싱 실패는 traceback 대신 명확한 메시지로.
    try:
        as_of_dt = (datetime.fromisoformat(args.as_of) if args.as_of
                    else datetime.now(timezone.utc))
    except ValueError:
        print(f"[smoke] --as-of ISO8601 파싱 실패: {args.as_of!r}")
        return 2

    print("⚠️  실제 KIS/OpenAI/Redis를 호출합니다(네트워크·토큰 비용 발생).")
    print(f"[smoke] ticker={args.ticker} as_of={as_of_dt.isoformat()} timeout={args.timeout_seconds}s "
          f"mode={'preflight-only' if args.preflight_only else 'e2e'}")

    # ── 네트워크/비용 호출 전 fail-fast (env → 입력검증 → clear-cache 게이트) ──
    # 1) env preflight — required 누락이면 즉시 중단.
    if not env_preflight(args):
        print("[smoke] 필수 env 누락으로 중단합니다.")
        return 1
    # 2) 입력 검증 — 잘못된 ticker/미래 as_of는 OpenAI/KIS 호출 전에 거절(비용·traceback 방지).
    if args.ticker not in BATTERY_TICKERS:
        print(f"[smoke] ticker {args.ticker!r} 은 allowlist(BATTERY_TICKERS) 밖입니다 — 중단(네트워크 미호출).")
        return 1
    _now = datetime.now(as_of_dt.tzinfo) if as_of_dt.tzinfo else datetime.now()
    if as_of_dt > _now:
        print("[smoke] --as-of 가 미래입니다 — 중단(네트워크 미호출).")
        return 1
    # 3) clear-cache 게이트 — --yes 없으면 파괴적 작업을 하지 않고 명확히 실패.
    if args.clear_cache_for_ticker and not args.yes:
        print("[smoke] --clear-cache-for-ticker 는 삭제 작업입니다. 삭제하려면 --yes 를 함께 지정하세요. 중단.")
        return 1
    if args.clear_cache_for_ticker:
        clear_cache_for_ticker(args.ticker)  # 위에서 --yes 확인됨

    ok = True
    # Redis preflight(비용 없음) — 항상 유용.
    if args.require_redis or args.check_cache or args.preflight_only:
        ok = redis_preflight(args.ticker) and ok

    if args.preflight_only:
        # 의존성 단독 점검 — agent/endpoint 실행 안 함(중복 호출·비용 최소화).
        if args.require_openai:
            ok = openai_preflight(min(30.0, args.timeout_seconds)) and ok
        if args.require_kis:
            ok = kis_preflight(args.ticker, as_of_dt) and ok
    else:
        # 실제 파이프라인 점검 — OpenAI/KIS는 agent e2e가 커버하므로 단독 preflight를 생략(중복 호출 방지).
        if args.via_agent:
            ok = agent_e2e(args, as_of_dt) and ok
        if args.check_cache:
            cache_behavior(args.ticker, as_of_dt)
        if args.via_testclient:
            ok = endpoint_smoke(args, as_of_dt) and ok

    print(f"=== RESULT: {'PASS' if ok else 'FAIL'} ===")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
