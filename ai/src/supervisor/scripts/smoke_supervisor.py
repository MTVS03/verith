"""상위 Supervisor 수동 smoke (opt-in, 실 의존성) — technical 실제 흐름 검증용.

resolve → planning → execution → technical adapter → technical output 을 **실제 주입 상태**에서 한 번
흘려본다. pytest 에 포함하지 않는다(실 네트워크). 실 KIS/OpenAI/backend 를 붙이므로 수동으로만 실행.

실행:
    cd ai
    # backend(:8000, /api/stocks/resolve)·OpenAI·KIS 접속이 준비돼 있어야 한다.
    uv run python -m src.supervisor.scripts.smoke_supervisor "삼성전자 차트 어때?"

출력은 **secret-safe** — request_id/trace_id/as_of 와 technical 요약(status·source·final_regime 등)만
찍고, raw prompt/response·API key 는 절대 출력하지 않는다.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from src.agents.technical.services.openai_llm_client import default_openai_client
from src.supervisor.agent_adapters import ExecutionDeps, default_adapters
from src.supervisor.resolve_client import StockResolverClient
from src.supervisor.runtime import run_analysis
from src.supervisor.schemas import SupervisorInput

_TECH_SUMMARY_FIELDS = ("request_id", "ticker", "source", "data_status", "final_regime",
                        "daily_regime", "alignment_flag")


def _summarize_output(output) -> dict:
    """technical 출력에서 secret-safe 요약 필드만 뽑는다(raw payload 미출력)."""
    return {f: getattr(output, f, None) for f in _TECH_SUMMARY_FIELDS}


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "삼성전자 차트 어때?"
    print(f"[smoke] query_len={len(query)} (원문 미출력)")

    # 실 의존성 주입 — endpoint 가 하는 wiring 을 스크립트에서 재현.
    resolver = StockResolverClient()
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

    execution = run_analysis(inp, resolver=resolver, adapters=default_adapters(), deps=deps)

    res = execution.resolution
    print(f"[smoke] resolution: used={res.used_stock_resolver} status={res.status} "
          f"stock={res.stock.stock_code if res.stock else None}")
    for r in execution.results:
        line = f"  - {r.agent_type:11} {r.status:8} reason={r.reason}"
        if r.agent_type == "technical":
            if r.status == "success":
                line += f"  {_summarize_output(r.output)}"
            elif r.error is not None:
                line += f"  error={r.error.type}: {r.error.message}"
        print(line)


if __name__ == "__main__":
    main()
