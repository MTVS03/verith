"""상위 Supervisor 수동 smoke (opt-in, 실 의존성) — technical 실제 흐름 검증용.

resolve → planning → execution → technical adapter → technical output 을 **실제 주입 상태**에서 한 번
흘려본다. pytest 에 포함하지 않는다(실 네트워크). 실 KIS/OpenAI/backend 를 붙이므로 수동으로만 실행.

실행:
    cd ai
    # backend(:8000, /api/stocks/resolve)·OpenAI·KIS 접속이 준비돼 있어야 한다.
    uv run python -m src.supervisor.scripts.smoke_supervisor "LG에너지솔루션 차트 어때?"

**종목 범위:** technical 은 전체 종목 확장 구조로, 형식상 유효한(6자리) ticker 를 기본 지원한다
(`config.is_supported_ticker`, allowlist 아님). 종목명 정본은 backend canonical stock context 가 담당한다.
실효 universe 는 backend `stocks`(resolver) 데이터에 종속 — 현재 dev stocks 에 seed 된 종목만 resolved 되므로
smoke 는 seed 된 종목을 쓴다. **실증 완료 기준선은 BATTERY_TICKERS 대표주**(예: 373220 LG에너지솔루션 ·
051910 LG화학)이고, 확장 종목(예: 005930)은 backend stocks 에 seed 된 뒤 검증한다.

출력은 **secret-safe** — request_id/trace_id/as_of 와 technical 요약(status·source·final_regime 등)만
찍고, raw prompt/response·API key 는 절대 출력하지 않는다.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from src.agents.technical.services.openai_llm_client import default_openai_client
from src.supervisor.execution.adapters import ExecutionDeps, default_adapters
from src.supervisor.planning.fallback_lookup import StaticFallbackLookup
from src.supervisor.planning.resolve_client import StockResolverClient
from src.supervisor.runtime import run_analysis
from src.supervisor.schemas import SupervisorInput

def _v(x):
    """enum 이면 값만(secret-safe 표시 정리)."""
    return getattr(x, "value", x)


def _summarize_output(output) -> dict:
    """technical 출력에서 secret-safe 요약 필드만 뽑는다(raw payload 미출력).

    regime 은 top-level 이 아니라 `output.regime`(RegimeResult) 에 중첩돼 있다."""
    regime = getattr(output, "regime", None)
    return {
        "request_id": getattr(output, "request_id", None),
        "ticker": getattr(output, "ticker", None),
        "source": _v(getattr(output, "source", None)),
        "data_status": _v(getattr(output, "data_status", None)),
        "final_regime": _v(getattr(regime, "final_regime", None)),
        "daily_regime": _v(getattr(regime, "daily_regime", None)),
        "alignment_flag": _v(getattr(regime, "alignment_flag", None)),
    }


def main() -> None:
    # 기본값은 technical BATTERY_TICKERS 내부 종목(373220 LG에너지솔루션)으로 고정한다.
    query = sys.argv[1] if len(sys.argv) > 1 else "LG에너지솔루션 차트 어때?"
    print(f"[smoke] query_len={len(query)} (원문 미출력)")

    # 실 의존성 주입 — endpoint 가 하는 wiring 을 스크립트에서 재현.
    resolver = StockResolverClient()
    # canonical not_found 일 때만 쓰는 보조 lookup(ephemeral, 정본 write 없음). 기본 entries 는 비어 있어
    # 오늘 동작 무변경 — 운영에서 KIS/DART/alias 기반 client 로 교체 주입한다.
    fallback = StaticFallbackLookup()
    try:
        llm_client = default_openai_client()
    except RuntimeError:
        print("[smoke] OPENAI 설정 없음 — technical 은 실패로 격리됩니다(다른 agent 는 진행).")
        llm_client = None

    deps = ExecutionDeps(
        technical_llm_client=llm_client,
        request_id="smoke-" + datetime.now(UTC).strftime("%H%M%S"),
        trace_id="smoke-trace",
        now=datetime.now(UTC),
    )
    inp = SupervisorInput(query=query, request_id=deps.request_id, trace_id=deps.trace_id)

    execution = run_analysis(
        inp, resolver=resolver, fallback=fallback, adapters=default_adapters(), deps=deps
    )

    res = execution.resolution
    print(f"[smoke] resolution: used={res.used_stock_resolver} fallback={res.used_fallback_lookup} "
          f"status={res.status} source={res.source} persisted={res.persisted} "
          f"stock={res.stock.stock_code if res.stock else None}")
    for r in execution.results:
        line = f"  - {r.agent_type:11} {r.status:8} reason={r.reason}"
        if r.status == "success" and r.agent_type == "technical":
            line += f"  {_summarize_output(r.output)}"
        elif r.status == "failed" and r.error is not None:
            # 실패 계층 분리용 — error type/message(이미 secret-safe: 개행제거·길이상한).
            line += f"  error={r.error.type}: {r.error.message}"
        print(line)


if __name__ == "__main__":
    main()
